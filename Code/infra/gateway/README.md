# Nginx Gateway（演示 / 对外同域入口）

| 剖面 | 对外端口 | 前端 | 后端 |
|------|----------|------|------|
| **dev（默认）** | Vite `:5175` | `npm run dev` / `launch.py start` | FastAPI `:8000`（Vite path proxy） |
| **gateway** | Nginx `:5175` | 静态 `Code/frontend/dist` | FastAPI `:8000`（Nginx 反代，同路径无 `/api` 前缀） |

## 状态

- **默认 `launch.py start` 不启动 Nginx**（避免与 Vite 抢 5175）。
- 显式启动：`Env\Python312\python.exe launch.py start gateway`
- 停止：`launch.py stop gateway`（或 `launch.py stop` 会一并停 gateway）

## Windows 注意

Docker Desktop 与启动终端须以**管理员身份**运行，否则可能镜像无法访问 / volume 挂载失败。

## 前置条件

1. 运行栈：Redis / MinIO（`launch.py start docker`）
2. FastAPI 在宿主机 `:8000` 可访问
3. 前端已构建：`Code/frontend/dist/index.html`（`start gateway` 若缺失会尝试 `npm run build`）

## 手动 compose

```powershell
cd Code\infra\gateway
# 先确保 dist 存在
docker compose -p gateway up -d
docker compose -p gateway ps
docker compose -p gateway down
```

## 路径约定

反代前缀与 [`Code/frontend/vite.config.ts`](../../frontend/vite.config.ts) 的 `server.proxy` 对齐，例如 `/weather`、`/workflow-runs`、`/unified-tiles`、`/config` 等。
