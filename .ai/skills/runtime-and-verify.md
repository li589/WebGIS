# 技能：运行时与验证命令映射（防“环境幽灵问题”）

> 场景：任何需要启动服务、跑测试、提交代码，或定位「为什么本地跑不起来/依赖对不上」的时刻。
> 适用工具：后端 / 前端 / 算法包 / CI。

## 1. 唯一运行时（最高优先级）

- 后端 / 算法 / pytest / launch **唯一解释器 = `Env/Python312/python.exe`**（Windows）。
  绝不用系统 PATH 的 `python` 或 `C:\Program Files\Python\...` —— 依赖（如 `rarfile`、科学库）不一致会触发「环境幽灵问题」。
- 前端需 Node 22（见 `Code/frontend/package.json` engines）。
- 手动/脚本统一：`Env\Python312\python.exe launch.py <cmd>`；`start.bat`/`stop.bat` 已强制该解释器。
- `Env/Python312` 是本地联调运行时，**不是** Docker 生产镜像。

## 2. 本地联调命令（launch.py）

| 命令 | 作用 |
|------|------|
| `Env\Python312\python.exe launch.py start` | 全栈：Docker + FastAPI + 7 Worker + Beat + Vite 前端 |
| `… launch.py start <component>` | 单组件：`docker`/`fastapi`/`beat`/`worker`/`worker:<name>`/`frontend`/`gateway` |
| `… launch.py status` / `logs [c] [-n N]` | 看状态 / 看日志 |
| `… launch.py flush` | 清 Redis DB + 天气文件缓存（**高风险，仅排障**） |
| `… launch.py sync [job]` | 数据面 Open-Meteo 同步（默认 `open-meteo-sync`） |

> Windows Docker 相关服务需 **Docker Desktop 与终端都以管理员身份**运行，否则 `start`/`sync` 可能失败（见 `.ai/docs/reference/本地联调环境说明.md`）。

服务地址：FastAPI `:8000`（docs `/docs`）、前端 `:5175`、Open-Meteo `:8080`、Redis `:6379`、MinIO `:9100`（Console `:9101`）。

## 3. 改 X 则跑 Y（速查，权威在 `.ai/rules/project-conventions.md`）

仓库根执行后端/算法测试（`Test/backend`、`Test/algorithms`），**不要**再用过期的 `Code/backend/tests/` 路径。

- 天气瓦片：`Env/Python312/python.exe -m pytest Test/backend/test_weather_tile_service.py -q`
- 工作流运行：`… -m pytest Test/backend/test_workflow_routes.py Test/backend/test_interaction_hub.py Test/backend/test_business_regression.py -q`
- **工作流定时器**：`… -m pytest Test/backend/test_workflow_timer_service.py Test/backend/test_celery_tasks.py -q`（真实 cron/interval 还需 `launch.py start beat` + 消费 `standard` 的 worker）
- 配置/鉴权：`… -m pytest Test/backend/test_config_security.py Test/backend/test_api_keys_basemap.py -q`
- GEE：`… -m pytest Test/backend/test_gee_bridge_service.py -q`
- 统一底图瓦片：`… -m pytest Test/backend/test_unified_tile_service.py -q`
- Open-Meteo 双源：`… -m pytest Test/backend/test_open_meteo_dual_providers.py Test/backend/test_open_meteo_performance.py -q`
- Python 算法包：`… -m pytest Test/algorithms/... -q` 或 `pre-commit` 覆盖 `algorithms/`
- 前端：`cd Code/frontend && npm run test && npm run lint && npm run build`
- 前端定时器：`cd Code/frontend && npm run test -- workflow-timer`
- 契约：`cd Code/frontend && npm run check:openapi`
- 任意提交前：`pre-commit run --all-files`

后端测试需 `REDIS_URL` + `ENVIRONMENT=test`。WorkBuddy shim 下需禁用：
`CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX=`。
CI 门禁：pre-commit → pytest → vitest → check:openapi。

## 4. 高风险区（改动前确认鉴权/加密/隔离）

见 `.ai/rules/project-conventions.md` 第 3 节：`/config/*` 写操作 + `POST /import/raster`（需 `X-API-Key`）、GEE 凭据加密（`BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY`）、`flush`（清队列/缓存）、Open-Meteo named volume（勿 bind mount）。

## 5. 避坑

- 不在个人目录（Desktop/Downloads/Documents）递归删/ `rm -rf`；清理走受限的 `launch.py flush`。
- 不在 `.gitignore` 排除路径（`.data`、`imports_output`、`tmp`、`.pytest_run*`）落源码。
- `.ai/` 为本地专用，不进 GitHub；工具规则指针文件可保留。
- 工作流设计 / 种子 / 定时器规范见 `.ai/skills/workflow-design.md`。
