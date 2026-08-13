# 前台维护模式（Gateway）

本目录同时存放：

| 路径 | 作用 |
|------|------|
| `on` | 维护开关（空文件；**不入库**） |
| `html/maintenance.html` | 升级/修 bug 时展示的纯 HTML 页（不依赖 Vue） |
| `html/50x.html` | 上游 FastAPI 502/503/504 时的错误页 |

存在 `on` 时，Nginx 对 **SPA / 静态资源** 返回 `503` 并展示 `html/maintenance.html`。

**API 反代不中断**（`/workflow-runs`、`/auth`、`/weather` 等），便于升级或修 bug 时让后台任务跑完。

## 启用

```powershell
New-Item -ItemType File -Force Code\infra\gateway\maintenance\on | Out-Null
docker exec cgda-gateway-nginx nginx -s reload
```

## 关闭

```powershell
Remove-Item -Force Code\infra\gateway\maintenance\on
docker exec cgda-gateway-nginx nginx -s reload
```

## 预览

不创建 `on` 也可直接打开：`http://localhost:5175/maintenance.html`（gateway 剖面）。

## 与 Vite 开发剖面

日常 `launch.py start` / `restart` **默认走 Gateway**。本地 HMR：`launch.py start --vite`（会停 Gateway）。若在 Vite 下不想看到红屏源码叠加层，可设 `VITE_HIDE_ERROR_OVERLAY=1`。
