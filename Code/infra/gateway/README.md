# Nginx Gateway（默认同域入口）

| 剖面 | 对外端口 | 前端 | 后端 |
|------|----------|------|------|
| **gateway（默认）** | Nginx `:5175` | 静态 `Code/frontend/dist` | FastAPI `:8000`（Nginx 反代，同路径无 `/api` 前缀） |
| **vite（开发 HMR）** | Vite `:5175` | `npm run dev` / `launch.py start --vite` | FastAPI `:8000`（Vite path proxy） |

`start` / `restart`（全量）**默认启 Gateway**；与 Vite 互斥（同端口 5175）。

## 状态

- **默认 `launch.py start` / `restart` 会启动 Nginx Gateway**（需 Docker；Windows 需管理员）。
- 本地改前端要热更新：`Env\Python312\python.exe launch.py start --vite`（会先停 Gateway）。
- 仅 Gateway：`launch.py start gateway`（`--rebuild-frontend` 强制 `npm run build`）。
- 停止：`launch.py stop gateway`（或 `launch.py stop` 一并停）。

## Windows 注意

Docker Desktop 与启动终端须以**管理员身份**运行，否则可能镜像无法访问 / volume 挂载失败。

### Docker Hub 镜像加速（推荐）

本机 Docker Desktop 的 `~/.docker/daemon.json`（Settings → Docker Engine）可配 `registry-mirrors`，使 `docker pull nginx:…` 等官方名自动走加速，无需改 compose。示例（按可达性择优）：

```json
"registry-mirrors": [
  "https://docker.1ms.run",
  "https://docker.m.daocloud.io",
  "https://docker.xuanyuan.me",
  "https://hub.rat.dev"
]
```

改完后执行 `docker desktop restart`，再用 `docker info` 确认 **Registry Mirrors** 已列出上述地址。

若未配加速且本机拉不到 `nginx:1.27-alpine`（Docker Hub 超时），可临时用镜像站拉取后打同名 tag：

```powershell
docker pull docker.m.daocloud.io/library/nginx:1.27-alpine
docker tag docker.m.daocloud.io/library/nginx:1.27-alpine nginx:1.27-alpine
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

上游 FastAPI 不可用时，API 反代返回 [`maintenance/html/50x.html`](maintenance/html/50x.html)（502/503/504）；SPA 路由仍走 `index.html`。

## 前台维护模式（升级 / 修 bug）

静态错误页与维护开关统一放在 [`maintenance/`](maintenance/)：

```text
maintenance/
  on                 # 开关（gitignore）
  html/
    maintenance.html
    50x.html
```

升级或紧急修复时，可打开 **纯 HTML 维护页**（不依赖 Vue、不展示源码/堆栈），同时让 API 继续服务后台任务：

| 步骤 | 操作 |
|------|------|
| 启用 | 创建空文件 `maintenance/on`，再 `docker exec cgda-gateway-nginx nginx -s reload` |
| 关闭 | 删除 `maintenance/on`，再 reload |
| 预览 | 访问 `/maintenance.html` |

详见 [`maintenance/README.md`](maintenance/README.md)。
