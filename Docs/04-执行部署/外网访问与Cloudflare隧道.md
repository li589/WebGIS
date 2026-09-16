# 外网访问与 Cloudflare 隧道

> 状态：已落地（2026-09-16）。适用阶段：开发第一阶段末尾 —— **局域网访问保留**，
> 后端已绑定 `api.<domain>` 隧道供微信小程序开发测试。
> 本文档记录拓扑、端口暴露面、本次安全修改，以及三条**已核实为非问题**的历史怀疑项
> （附代码依据，避免后续重复排查）。

## 1. 接入拓扑

本机是**双入口**形态：Web 走网关，小程序直连后端。

```
            外网 / 真机 / 体验版
                    │  HTTPS
        ┌───────────┴────────────┐
        │                        │
  web.<domain>             api.<domain>
        │                        │
        └────── cloudflared ─────┘        （出站长连接，无需开放入站端口）
                  │  127.0.0.1
   ┌──────────────┴───────────────┐
   │                              │
[cgda-gateway-nginx :5175]   [FastAPI :8000]
   binds 0.0.0.0 ──┬── 静态 dist、/feedback/、/api、/auth、/agent 等
                   │
   LAN 设备 ────────┘  http://<LAN-IP>:5175      ← 局域网访问由此保留

小程序（微信开发者工具）── http://127.0.0.1:8000（直连后端，**不过网关**）
```

要点：**网关不控制后端端口**。5175 与 8000 是两个独立监听面，隧道分别指向它们；
小程序链路绕开网关，因此后端自身就是该链路的唯一防线（见 §5）。

## 2. 端口暴露面（依 compose 实测）

| 服务 | 绑定 | 外部可达 | 来源 |
|---|---|---|---|
| 网关 nginx | `0.0.0.0:5175` | ✅ 局域网 + 隧道 | `Code/infra/gateway/docker-compose.yml` |
| 后端 FastAPI | `127.0.0.1:8000` | 仅本机与隧道（cloudflared 从本机连接） | `BACKEND_HOST` 默认值 |
| Redis | `127.0.0.1:16379` | ❌ | `Code/backend/docker-compose.yml` |
| MinIO | `127.0.0.1:9100` / `9101` | ❌ | 同上 |
| Open-Meteo | `127.0.0.1:8080` | ❌ | 同上 |

> 若日后要收敛暴露面，可把网关改绑 `127.0.0.1:5175` 并只保留隧道 ——
> **但那会失去局域网访问**，需显式决策。当前按需求保留 `0.0.0.0`。

## 3. 本次修改（2026-09-16）

1. **`Code/weixin/miniprogram/services/api.js` 去除硬编码凭据**
   原文件把 `baseUrl` / `admin` / `cgda-dev-admin` 写死在源码里且**已入库**，
   而该口令同时是后端管理员密码 —— 配合已上线的 `api.<domain>` 隧道，等于把
   admin 登录凭据公开挂在仓库里。现改为：
   - `services/config.js`（入库）：默认值，不含任何凭据；
   - `services/config.local.js`（**gitignore**）：真实 `baseUrl` / 账号 / 口令；
   - 缺失时回退默认配置并打印告警；`login()` 增加空凭据守卫，不会发空登录请求。
2. **轮换后端凭据**：`Code/backend/.env` 的 `BACKEND_ADMIN_PASSWORD`、`BACKEND_API_KEY`
   换为强随机值（旧值已随 api.js 入库，作废）；**并用运行期脚本轮换库中账号口令**
   （见 §4，仅改 `.env` 不会生效）。`BACKEND_ENV` **保持 development**，原因见 §6。
3. **新增 `Test/debug/_auth.py`**，`Test/debug/` 下 16 个诊断脚本不再硬编码口令，
   统一改读 `_auth.admin_password()`（优先级：环境变量 → `Code/backend/.env`）。
4. **`.gitignore`** 新增 `Code/weixin/miniprogram/services/config.local.js`。
5. **新增 `Code/backend/scripts/rotate_user_passwords.py`** —— 运行期口令轮换与泄漏审计，
   见 §4。

## 4. 口令真源与轮换（重要，曾踩坑）

**`BACKEND_ADMIN_PASSWORD` 只在用户表为空时用于初始播种**（`app/services/auth_bootstrap.py`
的 `bootstrap_auth()`）；对**已存在**的用户它**完全无效**。因此在已初始化的库上改 `.env`
口令是「表面功夫」——库里的 `password_hash` 不变，泄漏的旧口令依然可登录。

> 实测记录（2026-09-16）：改 `.env` 并重启后端后，库中 4 个账号
> （`admin` / `admin01` / `admin02` / `onlyread`）**仍全部接受 `cgda-dev-admin`**，
> 新 `.env` 口令一个都不接受 —— 其中 `admin01`/`admin02` 还是 admin 角色，
> 即泄漏当时并未被关闭。这直接说明「改 .env + 重启」不足以完成轮换。

**正确语义**：库是运行期口令的真源；`.env` 只负责首次播种与开发预填。
轮换必须走运行期接口，与 `PATCH /auth/users/{id}` 同一代码路径：

```bash
cd Code/backend
# 1) 审计：哪些账号仍接受泄漏口令（exit 3 = 存在风险账号，可用于巡检）
python scripts/rotate_user_passwords.py list --probe cgda-dev-admin

# 2) 轮换所有仍接受该口令的账号（自动生成强随机口令并打印）
python scripts/rotate_user_passwords.py rotate --all --probe cgda-dev-admin

# 3) 复核
python scripts/rotate_user_passwords.py list --probe cgda-dev-admin   # 期望 exit 0
```

轮换结果写入本地凭据文件 `Code/backend/.env.dev-accounts`（由 `.gitignore` 的 `.env.*`
规则覆盖，不入库）。

**必须同时吊销会话**：`update_user(password=...)` 只改 `password_hash`，**不会**让已签发
会话失效 —— 鉴权只看用户是否存在与 `enabled`（`credential_resolver._resolve_session`
→ `_live_user`），会话本身存于 Redis/SQLite。所以「只改口令不吊销会话」= 攻击者此前用
泄漏口令建立的会话**依然有效**，属假修复。（API 层 `PATCH /auth/users/{id}` 会吊销，
但直接改库不会。）脚本已默认处理：

```bash
# 轮换时自动吊销会话与 API token（--keep-sessions 可跳过）
python scripts/rotate_user_passwords.py rotate --all --probe cgda-dev-admin

# 若口令已改而漏了吊销，用此补救；复核会话已清空
python scripts/rotate_user_passwords.py revoke-sessions --all
```

本机执行记录（2026-09-16）：轮换后复核发现 admin 名下仍有 **5 个未过期会话**（Redis，
TTL≈24h），已用 `revoke-sessions --all` 清空。」

**不采用「每次启动用 env 覆盖库中口令」的原因**：管理员若在界面上改过密码，重启会被
`.env` 悄悄回滚，属于更危险的隐性行为。env 与运行期修改不应互相打架。

## 5. 三条已核实为「非问题」的历史怀疑项

以下三项曾在评审中被列为高风险，**经代码核实均不成立**。记录依据以免重复排查。

| 怀疑项 | 结论 | 依据 |
|---|---|---|
| 隧道伪装成 loopback，绕过 `dev_bypass_allowed` / 登录页预填 | **不成立** | `Code/backend/start_fastapi.py` 的 `uvicorn.run()` 未传 `proxy_headers` / `forwarded_allow_ips`，走 uvicorn 默认 `proxy_headers=True` + `forwarded_allow_ips="127.0.0.1"`。cloudflared 从本机发起的请求带 `X-Forwarded-For`，uvicorn 因而将 `request.client.host` 还原为**真实公网 IP**（非 loopback），`deps.dev_bypass_allowed()` 与 `auth_router.get_auth_config()` 的 prefill 均不触发 |
| `BACKEND_TRUST_PROXY=false` 使限流塌缩为单桶 | **不成立** | `app/api/rate_limit.py::client_ip()` 在 `trust_proxy=False` 时返回 `request.client.host`，而该值已被 uvicorn 按上一条还原为真实 IP，限流按真实来源计数。**保持 `false` 是正确选择**：它是纵深防御 —— 一旦 uvicorn 的 proxy 信任被关闭，XFF 不会被无条件信任 |
| 局域网用户经 5175 拿到登录页预填口令 | **不成立** | `Code/infra/gateway/nginx.conf` 已设置 `X-Real-IP $remote_addr` 与 `X-Forwarded-For $proxy_add_x_forwarded_for`，uvicorn 据此还原为 LAN IP（非 loopback），prefill 返回 `None` |

## 6. 何时切 `production`（切换清单）

当前**刻意不切**：`BACKEND_ENV=development` 在本阶段是必要的。切到 `production`
会一次性关闭下列开发便利，其中第一条与「需要局域网访问」直接冲突：

| 受控点 | production 行为 | 影响 |
|---|---|---|
| `ssrf.default_allow_private()` | 阻断 RFC1918 | ❌ 局域网/NAS 数据源不可用 |
| `layer_router` 目录 | 隐藏 `status=placeholder` | ❌ 实验室占位层不可见 |
| `workflow_definition_router` | 隐藏 `executable=False` stub | ❌ 面板节点减少（可用 `BACKEND_NODE_STUBS_VISIBLE=true` 单独保留） |
| 写/登录/天气瓦片 IP 限流 | 生效 | ⚠️ 多设备高频联调易 429 |
| CSP / HSTS 响应头 | 注入 | ⚠️ 需评估 |
| `deps.dev_bypass_allowed` | 关闭 | ✅ 净影响为 0（当前 `api_keys_enabled=true`，旁路本就不生效） |

**切换前置条件**：① 不再需要局域网数据源；② 联调期占位层/stub 不再需要；
③ 多设备高频联调结束；④ HSTS/CSP 影响已评估。
**切换动作**：`.env` 设 `BACKEND_ENV=production` → `python launch.py restart backend`。

## 7. 待办（需人工操作/决策）

1. **轮换 cloudflared 隧道 token** —— token 已在会话记录中明文出现（含 account tag
   与 tunnel id）。建议到 Cloudflare Zero Trust → Networks → Tunnels 重建隧道或重置
   凭证，新 token 只落本机启动脚本/服务，**禁止入库**。
2. **小程序合法域名** —— 真机/体验版需在微信后台把 `api.<domain>` 加入 request
   白名单；`project.config.json` 的 `urlCheck=false` 只对开发者工具生效。
3. **评估 `api.<domain>` 的 origin 指向** —— 现为直连 `:8000`，建议改为指向网关
   `:5175`，使小程序请求同样经过网关的 CSP / 限流 / request-id 统一处理；
   若维持直连，则后端是唯一防线，务必保证凭据强度（本次已轮换）。
4. **备份提醒** —— 凭据轮换后，旧备份里的口令已失效；`I:` 数据根与 `.env` 需另行留存。

## 8. P2 加固落地清单（2026-09-16 鉴权评审后续）

| 编号 | 问题 | 修复 | 位置 |
| --- | --- | --- | --- |
| P2-1 | 口令强度只在 API 层（Pydantic）校验，直接调仓储（脚本/迁移/其它入口）可绕过 | 策略下沉到 `passwords.validate_password()`，在 `create_user` / `update_user` 强制校验：≥8 位 + ≥2 类字符 + 不在弱口令黑名单 + 不含用户名 | `app/services/passwords.py`、`user_repository.py` |
| P2-2 | 登录只按 **IP** 限流：换 IP 轮试不触发；且 `development/test` 整体旁路 → 本部署等于无登录限流 | 新增**账号维度**失败锁定：连续 N 次失败锁 M 分钟，默认全环境生效；管理员可解锁，改口令自动解锁 | `app/services/login_lockout.py`、`auth_router.login`、`POST /auth/users/{id}/unlock` |
| P2-3 | SQLite 会话副本仅惰性删除 → 过期死行堆积（实测残留 8 月行） | 新增 `purge_expired_sessions()`：启动强制跑一次 + `create_session` 节流（1 小时）触发；补 `idx_sessions_expires` 索引 | `user_repository.py`、`session_service.py`、`main.py` |
| P2-4 | `LOOPBACK_IPS` 里的 `"localhost"` **永不命中**（`request.client.host` 恒为 IP 字面量），是"看起来保护了"；且未覆盖 `::ffff:127.0.0.1` | 改为 `is_loopback_host()`：支持主机名、`::ffff:` 映射、`127.0.0.0/8` | `credential_resolver.py`、`auth_router.get_auth_config` |
| P2-5 | `BACKEND_API_KEY_ROLE` 非 `admin` 的值被**静默降级为 standard**（写错的 `operator`、本意降权的 `demo` 都会变成 standard） | 白名单 `admin|standard|demo`；未知值 ERROR 日志 + 回落 standard；`admin` 启动时 WARNING 点明影响面 | `credential_resolver.py`、`effective_config.assert_service_key_role_policy()` |
| 主题-1 | 主题 logo 的 SVG 以 `image/svg+xml` 直出，登录页公开渲染 → 存储型 XSS | 双层：上传时拒绝含脚本载体的 SVG（best-effort）+ 下发时强制 `CSP: sandbox`（主防线） | `theme_repository.assert_svg_safe()`、`auth_router.get_theme_logo` |
| 主题-2 | `await file.read()` 无界读入内存，2 MiB 校验在读完之后 → 大文件可打爆进程 | 分块读取（64 KiB）+ 边读边判，超限即 413 | `auth_router.upload_theme_logo` |

### 相关环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BACKEND_PASSWORD_MIN_LENGTH` | `8` | 口令最短长度（P2-1） |
| `BACKEND_LOGIN_LOCKOUT_ENABLED` | `1` | 账号失败锁定总开关；DoS 应急可置 `0` |
| `BACKEND_LOGIN_LOCKOUT_THRESHOLD` | `5` | 连续失败多少次触发锁定 |
| `BACKEND_LOGIN_LOCKOUT_MINUTES` | `15` | 锁定时长（分钟）；锁定期间继续失败会续满窗口 |
| `BACKEND_API_KEY_ROLE` | `standard` | 服务密钥角色：`admin` / `standard` / `demo` |

### 账号锁定的已知取舍（DoS vs 爆破）

账号维度锁定**对所有用户名生效**（含不存在的账号），否则「锁定 = 账号存在」会变成
**用户名枚举预言机**。代价：攻击者可连续输错把某个账号锁住，形成拒绝服务。
缓解手段：

1. 阈值 5 次 / 15 分钟足够宽容，正常误操作不会触发；
2. 管理员可 `POST /auth/users/{id}/unlock` 即时解锁；
3. 改口令会自动清零失败计数；
4. 紧急情况可设 `BACKEND_LOGIN_LOCKOUT_ENABLED=0` 重启关闭。

### 服务密钥绑成 admin 的影响面（P2-5）

`BACKEND_API_KEY_ROLE=admin` 时，那把 **共享静态** 的 `X-API-Key` 拥有完整管理员权限：
增删用户、改主题、改配置。它的使用**无法归因到具体的人**，且会散落在 `.env`、
小程序本地配置、运维脚本里。仅在机器对机器确需管理员权限时才使用，并定期轮换
`BACKEND_API_KEY`。本项目当前为 `standard`。

## 9. 验证命令


```bash
# 口令泄漏审计（exit 3 = 仍有账号接受该口令）
cd Code/backend && python scripts/rotate_user_passwords.py list --probe cgda-dev-admin

# 网关基础设施冒烟（17 项断言）
python Test/standalone/gateway_smoke.py --base http://127.0.0.1:5175

# 旧口令必须失效（期望 401）
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"cgda-dev-admin"}'

# 新口令应可登录（期望 200）
python -c "import json,urllib.request,sys;sys.path.insert(0,'Test/debug');from _auth import admin_password as p;r=urllib.request.Request('http://127.0.0.1:8000/auth/login',method='POST');r.add_header('Content-Type','application/json');print(urllib.request.urlopen(r,json.dumps({'username':'admin','password':p()}).encode()).status)"

# 经隧道访问不应看到预填（期望 dev_prefill 为 null）
curl -s https://api.<domain>/auth/config
```
