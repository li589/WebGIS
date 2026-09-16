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
小程序链路绕开网关，因此后端自身就是该链路的唯一防线（见 §4）。

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
2. **轮换 `Code/backend/.env` 凭据**：`BACKEND_ADMIN_PASSWORD`、`BACKEND_API_KEY`
   换为强随机值（旧值已随 api.js 入库，作废）。`BACKEND_ENV` **保持 development**，
   原因见 §5。
3. **新增 `Test/debug/_auth.py`**，`Test/debug/` 下 16 个诊断脚本不再硬编码口令，
   统一改读 `_auth.admin_password()`（优先级：环境变量 → `Code/backend/.env`）。
4. **`.gitignore`** 新增 `Code/weixin/miniprogram/services/config.local.js`。

> 凭据轮换需重启后端才生效：`python launch.py restart backend`。

## 4. 三条已核实为「非问题」的历史怀疑项

以下三项曾在评审中被列为高风险，**经代码核实均不成立**。记录依据以免重复排查。

| 怀疑项 | 结论 | 依据 |
|---|---|---|
| 隧道伪装成 loopback，绕过 `dev_bypass_allowed` / 登录页预填 | **不成立** | `Code/backend/start_fastapi.py` 的 `uvicorn.run()` 未传 `proxy_headers` / `forwarded_allow_ips`，走 uvicorn 默认 `proxy_headers=True` + `forwarded_allow_ips="127.0.0.1"`。cloudflared 从本机发起的请求带 `X-Forwarded-For`，uvicorn 因而将 `request.client.host` 还原为**真实公网 IP**（非 loopback），`deps.dev_bypass_allowed()` 与 `auth_router.get_auth_config()` 的 prefill 均不触发 |
| `BACKEND_TRUST_PROXY=false` 使限流塌缩为单桶 | **不成立** | `app/api/rate_limit.py::client_ip()` 在 `trust_proxy=False` 时返回 `request.client.host`，而该值已被 uvicorn 按上一条还原为真实 IP，限流按真实来源计数。**保持 `false` 是正确选择**：它是纵深防御 —— 一旦 uvicorn 的 proxy 信任被关闭，XFF 不会被无条件信任 |
| 局域网用户经 5175 拿到登录页预填口令 | **不成立** | `Code/infra/gateway/nginx.conf` 已设置 `X-Real-IP $remote_addr` 与 `X-Forwarded-For $proxy_add_x_forwarded_for`，uvicorn 据此还原为 LAN IP（非 loopback），prefill 返回 `None` |

## 5. 何时切 `production`（切换清单）

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

## 6. 待办（需人工操作/决策）

1. **轮换 cloudflared 隧道 token** —— token 已在会话记录中明文出现（含 account tag
   与 tunnel id）。建议到 Cloudflare Zero Trust → Networks → Tunnels 重建隧道或重置
   凭证，新 token 只落本机启动脚本/服务，**禁止入库**。
2. **小程序合法域名** —— 真机/体验版需在微信后台把 `api.<domain>` 加入 request
   白名单；`project.config.json` 的 `urlCheck=false` 只对开发者工具生效。
3. **评估 `api.<domain>` 的 origin 指向** —— 现为直连 `:8000`，建议改为指向网关
   `:5175`，使小程序请求同样经过网关的 CSP / 限流 / request-id 统一处理；
   若维持直连，则后端是唯一防线，务必保证凭据强度（本次已轮换）。
4. **备份提醒** —— 凭据轮换后，旧备份里的口令已失效；`I:` 数据根与 `.env` 需另行留存。

## 7. 验证命令

```bash
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
