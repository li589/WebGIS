# 微信小程序本地反代（不改小程序代码）

同伴电脑上把 `http://localhost:8000` 转到远端 Cloudflare 隧道后端，小程序仍写 `localhost:8000`，无需改仓库配置。

```text
微信开发者工具 / 小程序
        │  http://localhost:8000
        ▼
同伴本机反代（本目录脚本）
        │  HTTPS
        ▼
https://api.cgdas.dpdns.org   ← 后端同学 Cloudflare 隧道
        ▼
后端同学电脑 FastAPI :8000
```

## 前提

1. **后端同学**：FastAPI 在跑，且隧道路由 `api.cgdas.dpdns.org` → `http://localhost:8000` 已生效。  
   先自测：浏览器打开 `https://api.cgdas.dpdns.org/health`。
2. **同伴**：本机 **8000 端口未被占用**（不要再起一份本地后端）。
3. 微信开发者工具勾选：**详情 → 本地设置 → 不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书**。
4. 小程序 `baseUrl` 保持：`http://localhost:8000`。

> **真机预览**：手机访问的是手机自己的 localhost，用不了同伴电脑上的反代。真机请临时把 baseUrl 设为 `https://api.cgdas.dpdns.org`（本地私有配置，勿提交 GitHub），或继续用模拟器。

## 默认目标

| 项 | 默认值 |
|----|--------|
| 本地监听 | `127.0.0.1:8000` |
| 上游 | `https://api.cgdas.dpdns.org` |

可用环境变量覆盖（三套方案通用约定）：

- `CGDA_PROXY_TARGET`：上游根 URL（无尾斜杠）
- `CGDA_PROXY_PORT`：本地端口（默认 `8000`）

---

## 方案 A：Caddy（推荐，几乎零环境依赖）

1. 下载 [Caddy Windows amd64](https://caddyserver.com/download)，把 `caddy.exe` 放到**本目录**（与 `Caddyfile` 同级）。  
   `caddy.exe` 体积大且因人而异，**不要提交进 Git**（本目录 `.gitignore` 已忽略）。
2. 需要改上游主机名时，编辑 `Caddyfile` 里的 `api.cgdas.dpdns.org`。
3. 在本目录打开 PowerShell：

```powershell
.\start-caddy.ps1
```

或：

```powershell
.\caddy.exe run --config .\Caddyfile
```

4. 浏览器打开 http://localhost:8000/health 。窗口保持开着。

停止：在窗口里 `Ctrl+C`。

---

## 方案 B：Node 脚本

需要已安装 [Node.js](https://nodejs.org/)。

```powershell
.\start-node.ps1
```

或：

```powershell
node .\api-proxy.mjs
```

自定义上游示例：

```powershell
$env:CGDA_PROXY_TARGET = "https://api.cgdas.dpdns.org"
$env:CGDA_PROXY_PORT = "8000"
node .\api-proxy.mjs
```

---

## 方案 C：Python 脚本

优先用仓库自带解释器（在仓库根执行）：

```powershell
..\..\Env\Python312\python.exe Tools\miniprogram-local-proxy\api_proxy.py
```

或在本目录：

```powershell
.\start-python.ps1
```

若无仓库环境，系统 `python` / `py` 亦可（需 Python 3.10+）。

---

## 不要用

- `npx local-cors-proxy ... --proxyPartial ""`：会报 `Cannot read properties of null (reading 'replace')`。
- 默认带 `/proxy` 前缀的 CORS 代理：会迫使小程序改路径，违背「不改代码」。

---

## 联调检查

| 步骤 | 谁 | 做什么 |
|------|----|--------|
| 1 | 后端同学 | `https://api.cgdas.dpdns.org/health` 能开 |
| 2 | 同伴 | 反代窗口在跑，`http://localhost:8000/health` 能开 |
| 3 | 同伴 | 小程序 baseUrl = `http://localhost:8000`，已勾「不校验合法域名」 |

两边 `/health` 都通而小程序仍失败 → 查小程序请求路径是否多写了 `/api` 等前缀（CGDA 后端路径通常无 `/api` 总前缀，以实际接口为准）。

## 文件一览

| 文件 | 作用 |
|------|------|
| `Caddyfile` | Caddy 反代配置 |
| `start-caddy.ps1` | 启动 Caddy |
| `api-proxy.mjs` | Node 反代 |
| `start-node.ps1` | 启动 Node 反代 |
| `api_proxy.py` | Python 反代 |
| `start-python.ps1` | 启动 Python 反代（优先 Env/Python312） |
| `.gitignore` | 忽略本地下载的 `caddy.exe` 等 |
