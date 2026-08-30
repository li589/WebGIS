# Tools/

本目录仅存放**外部工具、临时工具、主线以外的辅助脚本**（数据下载、校验、一次性迁移、本地排查等）。

## 禁止

- **禁止**存放项目主体功能与运行时模块（后端/前端/算法包业务代码、服务入口、运行时必需依赖）。
- **禁止**把 `Tools/` 当作服务启动或 API 的硬依赖路径。
- 运行时第三方二进制若必须随仓库分发，放在对应工程目录（例如后端：`Code/backend/vendor/`），不要放在这里。

## 允许

- 数据下载 / 同步 / 扫描 / 校验脚本
- overlay 资产审计与导出等运维辅助
- 一次性重组、排查、报告与测试夹具（`test_data/`、`reports/`、`logs/`）
- 微信小程序联调：本机 `:8000` → Cloudflare 隧道后端反代（不改小程序代码）见 `miniprogram-local-proxy/`

## 相关

| 用途 | 正确位置 |
|------|----------|
| 后端 RAR 解压用控制台 UnRAR | `Code/backend/vendor/unrar/` |
| 本地 Python 运行时 | `Env/Python312/` |
| FastAPI / Celery / 数据导入主链 | `Code/backend/` |
| 前端主链 | `Code/frontend/` |
| 算法包主链 | `Code/algorithms/` |

日常联调请用仓库根 `start.bat` / `Env\Python312\python.exe launch.py`，不要依赖本目录脚本启停主服务（`restart_backend.py` 等仅为遗留辅助）。
