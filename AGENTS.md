# AGENTS.md

面向 AI coding agent 的仓库导航。仅凭本文档即可定位模块与验证命令。

## 项目定位

CGDA（综合地理数据分析系统）：基于 Web 的地理信息平台，统一承载 2D 平面地图（MapLibre 主路径）/ 3D 地球（Cesium，依赖已引入但非默认主链）、多源数据接入（本地 / GEE / Open-Meteo / 商业天气源）、动态时空结果展示与回传、多课题组算法模块化接入。已进入工程落地阶段：`workflow-runs` 主链、天气瓦片渲染、Celery/Redis/MinIO 基础设施均可运行。

## 目录路由

| 路径 | 职责 | 关键子目录 |
|------|------|-----------|
| `Code/backend/` | FastAPI + Celery：workflow 编排、weatherengine、统一瓦片、GEE | `app/api/routers/`（按域路由）、`app/services/workflow/`、`app/weatherengine/`、`app/tasks/`、`app/gee/`、`tests/` |
| `Code/frontend/` | Vue 3 + TypeScript + Vite + Pinia：MapLibre 2D、天气叠加、工作流交互 | `src/views/`、`src/components/`、`src/stores/`、`src/services/`、`src/composables/` |
| `Code/algorithms/` | Python 算法包：contracts / data_access / runner / publish | `providers/Python/`（lint/mypy 覆盖范围） |
| `Code/shared/` | 前后端共享协议与公共契约 | `contracts/` |
| `Code/infra/data-sync/` | 数据面 compose（Open-Meteo 同步，与运行栈隔离） | `docker-compose.yml`、`sync.sh` / `sync.ps1` |
| `Doc/` | 方案、技术栈、规范与协作文档 | — |
| `Tools/` | 数据下载、校验与辅助脚本 | — |
| `Env/` | 本地开发环境与启停辅助 | — |
| `launch.py` | 跨平台一键启动器（Docker + FastAPI + Celery + 前端） | — |

后端路由入口：`app/api/routers/__init__.py` 注册各域 router（health / layer / workflow / runtime / weather / algorithm / provider / artifact / import）；瓦片另走 `app/api/tile_routes.py`（底图 `/unified-tiles`）与 `app/api/weather_tile_routes.py`（天气 `/weather/tiles`）；配置写操作走 `app/api/config_routes.py`。

## 命令指针（launch.py）

所有日常联调经根目录 `launch.py`（Windows: `start.bat` / `stop.bat`；Linux: `./start.sh` / `./stop.sh` 均转发到 `launch.py`）：

| 命令 | 作用 |
|------|------|
| `python launch.py start` | 启动全部（Docker 运行栈 + FastAPI + 7 个 Celery Worker + Beat + 前端），进入监控循环 |
| `python launch.py start <component>` | 单组件：`docker` / `fastapi` / `beat` / `worker` / `worker:<name>` / `frontend` |
| `python launch.py stop` | 停止全部服务（含 Docker 容器） |
| `python launch.py status` | 查看服务状态（Docker / FastAPI :8000 / 前端 :5175 / Worker PID / volume） |
| `python launch.py logs [component] [-n N]` | 查看日志（`fastapi` / `beat` / `frontend` / `worker:<name>`；默认合并全部） |
| `python launch.py flush` | 清空 Redis DB + 应用天气文件缓存（**见高风险区**） |
| `python launch.py sync [job]` | 数据面一次性同步（默认 `open-meteo-sync`，走 `Code/infra/data-sync`） |

服务地址：FastAPI `http://127.0.0.1:8000`（docs `/docs`）、前端 `http://localhost:5175`、Open-Meteo API `http://127.0.0.1:8080`、Redis `:6379`、MinIO `:9100`（Console `:9101`）。

## 高风险区

改动以下区域前必须确认鉴权、加密或数据面隔离约束，避免破坏运行态或泄露凭据：

1. **`/config/*` 写操作**：`app/api/config_routes.py` + `app/services/config_service.py` / `api_config.py` / `effective_config.py`。所有 `/config/*` 写操作与 `POST /import/raster` 需 `X-API-Key`（development 且未启用 keys 时可旁路）。鉴权密钥 = `backend_auth` DB 覆盖 env。覆盖图层 URI、天气 provider、remote-storage 等运行真源，改错会污染运行配置。

2. **GEE 凭据**：`app/gee/` + `app/services/gee_parallel_config.py`。存储的 GEE 账号凭据用 `BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY`（32-byte hex，`.env` 生成）加密落 DB。非 development 环境**必须**配置该密钥，否则凭据无法加解密。涉及 `/config/gee/accounts*` 与 `/gee/config`。

3. **flush（清缓存）**：`python launch.py flush` 执行 Redis `FLUSHDB` + 删除 `Code/backend/.data/cache/weather` 与 `weatherengine` 目录。会清空队列、缓存与限流/断路器状态，影响在线服务；**不**删 Open-Meteo Docker volume。仅在排障或强制刷新天气缓存时使用，勿在正常联调中随意执行。

4. **Open-Meteo volume**：named volume `backend_open-meteo-data`（名可经 `Code/infra/data-sync/.env` 的 `OPEN_METEO_DATA_VOLUME` 覆盖），落在 Docker Desktop VHDX 内（`I:\Docker\DockerDesktop`）。**勿用 Windows 路径 bind mount** 替代。API 在 backend 运行栈（容器 `cgda-open-meteo`）；同步在 `Code/infra/data-sync`（`-p data-sync`）。两栈共享同一 volume 但 compose project 不同，改动 compose 时勿混用 project 名。

## "改 X 则跑 Y" 映射

| 改动区域 (X) | 定位模块 | 验证命令 (Y) |
|-------------|---------|-------------|
| 天气瓦片 | `app/weatherengine/tile_service.py`、`app/api/weather_tile_routes.py` | `cd Code/backend && pytest tests/test_weather_tile_service.py -q`；再 `python launch.py start fastapi` 后请求 `/weather/tiles/{layer_id}/{z}/{x}/{y}` |
| 天气点查 / 引擎 | `app/weatherengine/service.py`、`fetch_gateway.py`、`providers/` | `pytest tests/test_weather_point_service.py tests/test_weatherengine_service.py tests/test_fetch_gateway.py -q` |
| 工作流运行 | `app/services/workflow/`、`app/api/routers/workflow_router.py` | `pytest tests/test_workflow_routes.py tests/test_interaction_hub.py tests/test_business_regression.py -q` |
| 配置 / 鉴权 | `app/api/config_routes.py`、`app/services/config_service.py` | `pytest tests/test_config_security.py tests/test_api_keys_basemap.py -q` |
| GEE | `app/gee/`、`app/services/gee_bridge_service.py` | `pytest tests/test_gee_bridge_service.py -q` |
| 统一瓦片（底图） | `app/api/tile_routes.py`、`tile_provider_registry.py` | `pytest tests/test_unified_tile_service.py -q` |
| 栅格导入 / CRS | `app/api/routers/import_router.py` | `pytest tests/test_import_raster_crs.py tests/test_crs_detector.py -q` |
| Open-Meteo 双源 | `app/weatherengine/providers/`、`.env.open-meteo.example` | `pytest tests/test_open_meteo_dual_providers.py tests/test_open_meteo_performance.py -q` |
| 前端任意改动 | `Code/frontend/src/` | `cd Code/frontend && npm run test && npm run lint && npm run build` |
| 前后端契约 / OpenAPI | `Code/frontend/openapi.json`、`Code/shared/contracts/` | `cd Code/frontend && npm run check:openapi` |
| Python 算法包 | `Code/algorithms/providers/Python/` | `pre-commit run --all-files`（ruff + mypy 覆盖 `algorithms/`） |
| 任意提交前 | 全仓库 | `pre-commit run --all-files`（ruff / mypy / eslint / prettier / 契约检查） |

后端测试默认在 `Code/backend/` 下执行，需 `REDIS_URL` 与 `ENVIRONMENT=test`（见 `.github/workflows/ci.yml`）。CI 质量门：pre-commit（全量）→ pytest → vitest → check:openapi。

## 快速验证（示例）

以"改天气瓦片"为例，仅凭本文档即可完成定位与验证：

1. 查"目录路由"→ 天气瓦片属 `Code/backend/`，路由入口 `app/api/weather_tile_routes.py`，服务 `app/weatherengine/tile_service.py`。
2. 查"改 X 则跑 Y"→ 先跑 `cd Code/backend && pytest tests/test_weather_tile_service.py -q`。
3. 查"命令指针"→ `python launch.py start fastapi` 起后端，再请求 `GET /weather/tiles/{layer_id}/{z}/{x}/{y}` 验证渲染。
4. 涉及缓存异常时查"高风险区"→ 必要时 `python launch.py flush` 清天气缓存后重试。

## 约定

- 后端主叙事是 `workflow-runs`；旧 `/tasks` 仅兼容桥接，勿新增依赖。
- 天气视口热路径走 `GET /weather/tiles/...`（`WeatherTileService`），不占 workflow 池；显式 tile workflow 仍可用但计入 `weather_tile` 池。
- 活文档以各 README 为准；带日期的快照文档（`代码事实同步文档-*` 等）仅作历史参考，不覆盖现行结构。
- 提交信息遵循 Conventional Commits（`feat` / `fix` / `refactor` / `perf` / `chore` / `docs` / `test` / `style` / `build` / `ci`）。
