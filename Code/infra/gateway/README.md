# Nginx Gateway（默认同域入口）

| 剖面 | 对外端口 | 前端 | 后端 |
|------|----------|------|------|
| **gateway（默认）** | Nginx `:5175` | 静态 `Code/frontend/dist` | FastAPI `:8000`（Nginx 反代） |
| **gateway + HMR（`--vite`）** | Nginx `:5175` | 反代本机 Vite `:5174`（HMR / WS） | FastAPI `:8000`（Nginx 反代） |
| **frontend only** | Vite `:5175` | `launch.py start frontend`（直连，停 Gateway） | Vite path proxy → `:8000` |

`start` / `restart`（全量）**默认启静态 Gateway**；`start --vite` = **同域入口不变**，背后挂 Vite HMR（不再互斥停 Gateway）。

## 状态

- **默认 `launch.py start` / `restart` 会启动 Nginx Gateway**（需 Docker；Windows 需管理员）。
- 本地前端热更新：`Env\Python312\python.exe launch.py start --vite`（入口仍 `http://localhost:5175`）。
- 仅静态 Gateway：`launch.py start gateway`（`--rebuild-frontend` 强制 `npm run build`）。
- 配置热重载：`launch.py reload gateway`（`nginx -t` + `nginx -s reload`，不重建容器）。
- 停止：`launch.py stop gateway`（或 `launch.py stop` 一并停）。

### 静态剖面缓存契约

- `index.html` / `/`：`Cache-Control: no-store`（rebuild 后浏览器总能拿到新 chunk 引用）。
- `/assets/*`：content-hash 可 `immutable`；**缺失文件必须真 404**，禁止 SPA `try_files` 回退成 HTML（否则动态 import 报 Failed to fetch module）。
- 前端 `importLazyChunk` 对 stale chunk 最多硬刷新一次。
- 联调分层与排障顺序：仓库根 [`Docs/07-工程保障/联调缓存与生效边界.md`](../../../Docs/07-工程保障/联调缓存与生效边界.md)。`launch.py start`/`restart` 默认按矩阵清理本地编译缓存，**永不**自动 `flush`。

### HMR 剖面（手动 compose）

```powershell
cd Code\infra\gateway
# 先在本机启动 Vite :5174（VITE_BEHIND_GATEWAY=1）
docker compose -p gateway -f docker-compose.yml -f docker-compose.hmr.yml up -d --force-recreate
```

切回静态：

```powershell
docker compose -p gateway -f docker-compose.yml up -d --force-recreate
```

## Windows 注意

Docker Desktop 与启动终端须以**管理员身份**运行，否则可能镜像无法访问 / volume 挂载失败。

### Docker 镜像加速（可选）

本机 Docker Desktop 的 `~/.docker/daemon.json`（Settings → Docker Engine）可配 `registry-mirrors`，使 `docker pull nginx:…` 等官方名自动走加速，无需改 compose：

```json
"registry-mirrors": ["https://<你选定的镜像加速地址>"]
```

**安全提示（2026-08-20 审计）**：请自行选择**可信任**的镜像加速源——第三方 mirror 对镜像内容无签名校验，存在投毒/篡改风险（供应链攻击面）。生产环境建议直连 Docker Hub 或自建内网 registry。改完后执行 `docker desktop restart`，用 `docker info` 确认 Registry Mirrors 已生效。

若未配加速且本机拉不到 `nginx:1.27-alpine`（Docker Hub 超时），可在**隔离开发机**上临时用镜像站拉取后打同名 tag（不要在生产机执行）：

```powershell
docker pull <镜像站>/library/nginx:1.27-alpine
docker tag <镜像站>/library/nginx:1.27-alpine nginx:1.27-alpine
```

## 前置条件

1. 运行栈：Redis / MinIO（`launch.py start docker`，或全量 start 自带）
2. FastAPI 在宿主机 `:8000` 可访问
3. 前端已构建：`Code/frontend/dist/index.html`（缺失或 `--rebuild-frontend` 时会 `npm run build`）

## 手动 compose

```powershell
cd Code\infra\gateway
# 先确保 dist 存在
docker compose -p gateway up -d
docker compose -p gateway ps
docker compose -p gateway down
```

## 路径约定

反代前缀与 [`Code/frontend/vite.config.ts`](../../frontend/vite.config.ts) 的 `server.proxy` 对齐，例如 `/weather`、`/workflow-runs`、`/unified-tiles`、`/config`、`/auth`、`/overlay-tiles`、`/health` 等。

### 错误页定向矩阵（2026-08-20 审计后全覆盖）

| 场景 | 状态码 | 响应 |
|------|--------|------|
| 后端宕机/超时（nginx 自生，API 与前台均适用） | 502 / 503 / 504 | `50x.html` |
| 前台 SPA/静态资源故障（浏览器导航场景） | 500 / 501 / 502 / 504 / 505 | `50x.html` |
| 上传体超限（API XHR 场景） | 413 | JSON `{"detail": …}`（`@json413`，保持前端错误契约） |
| 上传体超限（浏览器表单直发场景） | 413 | `413.html` |
| 维护模式开启（仅前台） | 503 | `maintenance.html`（API 反代不受影响） |
| SPA 深链接刷新 | — | `try_files` 兜底 `index.html` 200（`Cache-Control: no-store`） |
| 缺失的 Vite `/assets/*`（旧 hash） | 404 | **不**回退 SPA；`immutable` 长缓存（有 hash 才可） |

**设计决策**：API 反代**不开** `proxy_intercept_errors`——应用层错误 JSON（`request_id` / `error_code` / `Retry-After`）原样透传，由前端 `_http.ts` 统一解析；`error_page` 仅接管 nginx 自生错误。注意 `error_page` 不跨级继承，各 location 显式声明完整集合。

### 安全响应头

统一片段 [`snippets/security-headers.conf`](snippets/security-headers.conf)（CSP / nosniff / Referrer-Policy）。**nginx 继承规则**：location 内出现任一 `add_header` 即不再继承 server 级安全头——凡含 `add_header` 的 location 必须重新 `include` 该片段。

### 已知暴露面（已接受）

- 网关端口 `5175` 绑定 `0.0.0.0`（局域网可达）：内网部署假设下已接受（用户决策 2026-08-20）；网关自身为明文 HTTP，TLS 由部署拓扑承担。
- `client_max_body_size 200m`：与大文件导入需求匹配，超限走 413 定向。

另有**问题反馈中心** `http://localhost:5175/feedback/`（纯静态、非 Vue、不依赖后端；维护期/宕机期可用），详见 [`maintenance/README.md`](maintenance/README.md)。

## 前台维护模式（升级 / 修 bug）

静态错误页与维护开关统一放在 [`maintenance/`](maintenance/)：

```text
maintenance/
  on                 # 开关（gitignore）
  html/
    maintenance.html
    50x.html
    413.html
snippets/
  security-headers.conf   # 安全响应头统一片段（含 add_header 的 location 须 include）
```

升级或紧急修复时，可打开 **纯 HTML 维护页**（不依赖 Vue、不展示源码/堆栈），同时让 API 继续服务后台任务：

| 步骤 | 操作 |
|------|------|
| 启用 | 创建空文件 `maintenance/on`，再 `launch.py reload gateway`（或 `docker exec cgda-gateway-nginx nginx -s reload`） |
| 关闭 | 删除 `maintenance/on`，再 reload |
| 预览 | 访问 `/maintenance.html` |

详见 [`maintenance/README.md`](maintenance/README.md)。
