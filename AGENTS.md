# AGENTS.md

面向 AI coding agent 的仓库导航。仅凭本文档即可定位模块与验证命令。

## 项目定位

CGDA（综合地理数据分析系统）：基于 Web 的地理信息平台，统一承载 2D 平面地图（MapLibre 主路径）/ 3D 地球（Cesium，依赖已引入但非默认主链）、多源数据接入（本地 / GEE / Open-Meteo / 商业天气源）、动态时空结果展示与回传、多课题组算法模块化接入。已进入工程落地阶段：`workflow-runs` 主链、天气瓦片渲染、Celery/Redis/MinIO 基础设施均可运行。

## 目录路由

| 路径 | 职责 | 关键子目录 |
|------|------|-----------|
| `Code/backend/` | FastAPI + Celery：workflow 编排、weatherengine、统一瓦片、GEE | `app/api/routers/`（按域路由）、`app/services/workflow/`、`app/weatherengine/`、`app/tasks/`、`app/gee/`（测试已迁出至仓库根 `Test/backend/`） |
| `Code/frontend/` | Vue 3 + TypeScript + Vite + Pinia：MapLibre 2D、天气叠加、工作流交互 | `src/views/`、`src/components/`、`src/stores/`、`src/services/`、`src/composables/` |
| `Code/algorithms/` | Python 算法包：contracts / data_access / runner / publish | `providers/Python/`（lint/mypy 覆盖范围） |
| `Code/shared/` | 前后端共享协议与公共契约 | `contracts/` |
| `Code/infra/data-sync/` | 数据面 compose（Open-Meteo 同步，与运行栈隔离） | `docker-compose.yml`、`sync.sh` / `sync.ps1` |
| `Code/infra/gateway/` | 可选 Nginx 同域入口（静态 dist + 反代 FastAPI `:8000`） | `docker-compose.yml`、`nginx.conf`、`README.md` |
| `.ai/` | **AI 工作区（本地专用，不上传 GitHub）**：技能 / 规则 / 计划 / 进度 / 记忆 / 文档 | `rules/`、`skills/`、`plans/`、`progress/`、`memory/`、`docs/` |
| `Doc/` | **（已并入 `.ai/docs/`）** 原方案、技术栈、规范与协作文档 | 见 `.ai/docs/{design,specs,reference}/` |
| `Tools/` | 主线外辅助（下载/校验/一次性脚本）；**禁止**放主体功能与运行时模块，见 `Tools/README.md` | — |
| `Test/` | **测试集中地**（仓库根，不在任何 `Code/` 子树下）：后端 `Test/backend/`、前端 `Test/frontend/`（保留 `src/` 目录结构，相对导入已改写为 `@/`）、算法 `Test/algorithms/`、独立/调试/报告 `Test/{standalone,debug,reports,tools}/` | 运行：`Env/Python312/python.exe -m pytest Test/backend`（后端/算法）；`cd Code/frontend && npm run test`（前端） |
| `Env/Python312/` | **本地联调唯一 Python 运行时**（Windows: `python.exe`） | 依赖与后端/Worker 必须与此一致 |
| `launch.py` | 跨平台一键启动器（自动切换到 Env/Python312） | — |

后端路由入口：`app/api/routers/__init__.py` 注册各域 router（health / layer / workflow / runtime / weather / algorithm / provider / artifact / import）；瓦片另走 `app/api/tile_routes.py`（底图 `/unified-tiles`）与 `app/api/weather_tile_routes.py`（天气 `/weather/tiles`）；配置写操作走 `app/api/config_routes.py`。

## Python 环境（硬约定）

- **唯一解释器**：`Env/Python312`（勿用系统 PATH / `Program Files\Python`）。
- **推荐入口**：Windows `start.bat` / `stop.bat`；Linux `./start.sh` / `./stop.sh`。
- **手动调用**：`Env\Python312\python.exe launch.py <cmd>`。
- Agent 在本仓库执行后端/pytest/launch 时，也应优先该解释器。

## Windows：Docker 管理员身份（硬约定）

在 **Windows** 上启动本仓库 Docker 相关服务（`launch.py start` / `start docker` / `sync`）时：

- **Docker Desktop 与运行启动命令的终端必须以管理员身份运行。**
- **否则启动可能会失败**（Docker 未就绪、compose 失败、镜像/volume 访问异常等）。
- 否则还可能出现：**镜像无法访问/拉取**、named volume 或引擎配置读失败、部分容器起不全。
- 默认联调**不包含 Nginx**；可选剖面 `launch.py start gateway`（见 `Code/infra/gateway/`），日常入口是 Vite `:5175` + FastAPI `:8000`。

## 命令指针（launch.py）

所有日常联调经根目录 `launch.py`（由 `start.bat` 等以 `Env/Python312` 调用）：

| 命令 | 作用 |
|------|------|
| `start.bat` 或 `Env\Python312\python.exe launch.py start` | 启动全部（Docker + FastAPI + 7 Worker + Beat + Vite 前端） |
| `Env\Python312\python.exe launch.py start <component>` | 单组件：`docker` / `fastapi` / `beat` / `worker` / `worker:<name>` / `frontend` / `gateway` |
| `Env\Python312\python.exe launch.py start gateway` | Nginx 同域入口 `:5175`（静态 dist + 反代 API；与 Vite 互斥） |
| `stop.bat` / `… launch.py stop` | 停止全部服务（含 Docker 与 gateway 容器） |
| `… launch.py stop gateway` | 仅停 Nginx Gateway |
| `… launch.py status` | 查看服务状态（Docker / FastAPI :8000 / 前端 :5175 / Gateway / Worker PID / volume） |
| `… launch.py logs [component] [-n N]` | 查看日志 |
| `… launch.py flush` | 清空 Redis DB + 应用天气文件缓存（**见高风险区**） |
| `… launch.py sync [job]` | 数据面一次性同步（默认 `open-meteo-sync`） |

服务地址：FastAPI `http://127.0.0.1:8000`（docs `/docs`）、前端 `http://localhost:5175`、Open-Meteo API `http://127.0.0.1:8080`、Redis `:6379`、MinIO `:9100`（Console `:9101`）。

## 高风险区

改动以下区域前必须确认鉴权、加密或数据面隔离约束，避免破坏运行态或泄露凭据：

1. **`/config/*` 写操作**：`app/api/config_routes.py` + `app/services/config_service.py` / `api_config.py` / `effective_config.py`。所有 `/config/*` 写操作与 `POST /import/raster` 需 `X-API-Key`（development 且未启用 keys 时可旁路）。鉴权密钥 = `backend_auth` DB 覆盖 env。覆盖图层 URI、天气 provider、remote-storage 等运行真源，改错会污染运行配置。

2. **GEE 凭据**：`app/gee/` + `app/services/gee_parallel_config.py`。存储的 GEE 账号凭据用 `BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY`（32-byte hex，`.env` 生成）加密落 DB。非 development 环境**必须**配置该密钥，否则凭据无法加解密。涉及 `/config/gee/accounts*` 与 `/gee/config`。

3. **flush（清缓存）**：`Env\Python312\python.exe launch.py flush` 执行 Redis `FLUSHDB` + 删除 `Code/backend/.data/cache/weather` 与 `weatherengine` 目录。会清空队列、缓存与限流/断路器状态，影响在线服务；**不**删 Open-Meteo Docker volume。仅在排障或强制刷新天气缓存时使用，勿在正常联调中随意执行。

4. **Open-Meteo volume**：named volume `backend_open-meteo-data`（名可经 `Code/infra/data-sync/.env` 的 `OPEN_METEO_DATA_VOLUME` 覆盖），落在 Docker Desktop VHDX 内（`I:\Docker\DockerDesktop`）。**勿用 Windows 路径 bind mount** 替代。API 在 backend 运行栈（容器 `cgda-open-meteo`）；同步在 `Code/infra/data-sync`（`-p data-sync`）。两栈共享同一 volume 但 compose project 不同，改动 compose 时勿混用 project 名。

## "改 X 则跑 Y" 映射

| 改动区域 (X) | 定位模块 | 验证命令 (Y) |
|-------------|---------|-------------|
| 天气瓦片 | `app/weatherengine/tile_service.py`、`app/api/weather_tile_routes.py` | `Env/Python312/python.exe -m pytest Test/backend/test_weather_tile_service.py -q`（仓库根执行）；再 `python launch.py start fastapi` 后请求 `/weather/tiles/{layer_id}/{z}/{x}/{y}` |
| 天气工作流编译 | `app/services/workflow_graph_compiler.py`、`workflow_seeds/system/weather_*.json` | `Env/Python312/python.exe -m pytest Test/backend/test_workflow_graph_compiler.py -q` |
| 天气点查 / 引擎 | `app/weatherengine/service.py`、`fetch_gateway.py`、`providers/` | `Env/Python312/python.exe -m pytest Test/backend/test_weather_point_service.py Test/backend/test_weatherengine_service.py Test/backend/test_fetch_gateway.py -q` |
| 工作流运行 | `app/services/workflow/`、`app/api/routers/workflow_router.py` | `Env/Python312/python.exe -m pytest Test/backend/test_workflow_routes.py Test/backend/test_interaction_hub.py Test/backend/test_business_regression.py -q` |
| 配置 / 鉴权 | `app/api/config_routes.py`、`app/services/config_service.py` | `Env/Python312/python.exe -m pytest Test/backend/test_config_security.py Test/backend/test_api_keys_basemap.py -q` |
| GEE | `app/gee/`、`app/services/gee_bridge_service.py` | `Env/Python312/python.exe -m pytest Test/backend/test_gee_bridge_service.py -q` |
| 统一瓦片（底图） | `app/api/tile_routes.py`、`tile_provider_registry.py` | `Env/Python312/python.exe -m pytest Test/backend/test_unified_tile_service.py -q` |
| 栅格导入 / CRS | `app/api/routers/import_router.py` | `Env/Python312/python.exe -m pytest Test/backend/test_import_raster_crs.py Test/backend/test_crs_detector.py -q` |
| Open-Meteo 双源 | `app/weatherengine/providers/`、`.env.open-meteo.example` | `Env/Python312/python.exe -m pytest Test/backend/test_open_meteo_dual_providers.py Test/backend/test_open_meteo_performance.py -q`；本地：`python launch.py sync`（`visibility` 需 `gfs_global`） |
| overlay 本地图 | `overlay_registry.py`、`Tools/audit_overlay_assets.py` | `python Tools/audit_overlay_assets.py` |
| D2 / A1A2 NDVI | `modules/omega_avg_daily.py`、`ingest/ndvi_hdf_preprocess.py` | `Env/Python312/python.exe -m pytest Test/backend/test_omega_avg_algorithm.py Test/backend/test_omega_avg_daily_module.py -q`；`Env/Python312/python.exe -m pytest Test/algorithms/test_ndvi_hdf_preprocess.py -q` |
| 前端任意改动 | `Code/frontend/src/`（测试在 `Test/frontend/`） | `cd Code/frontend && npm run test && npm run lint && npm run build` |
| 图层工作区持久化 | `stores/layers/workspace-persist.ts`、`stores/layers/index.ts`；说明见 `.ai/docs/design/图层持久化说明.md` | `cd Code/frontend && npm run test -- workspace-persist` |
| 天气瓦片 FE 调度 / 图例 | `weather-tile-manager.ts`、`weather-tile-banner.ts`、`effective-layer-symbology.ts` | `cd Code/frontend && npm run test -- weather-tile weather-tile-banner effective-layer-symbology` |
| 前后端契约 / OpenAPI | `Code/frontend/openapi.json`、`Code/shared/contracts/` | `cd Code/frontend && npm run check:openapi` |
| Python 算法包 | `Code/algorithms/providers/Python/` | `pre-commit run --all-files`（ruff + mypy 覆盖 `algorithms/`） |
| 任意提交前 | 全仓库 | `pre-commit run --all-files`（ruff / mypy / eslint / prettier / 契约检查） |

后端/算法测试集中在仓库根 `Test/`（后端 `Test/backend/`、算法 `Test/algorithms/`），在仓库根用 `Env/Python312/python.exe -m pytest Test/backend` 执行，需 `REDIS_URL` 与 `ENVIRONMENT=test`（见 `.github/workflows/ci.yml`）。前端测试在 `Test/frontend/`，由 `Code/frontend/vite.config.ts` 的 `test.include` 跨出 root 加载。CI 质量门：pre-commit（全量）→ pytest → vitest → check:openapi。

**WorkBuddy 内跑后端测试的硬约定**：WorkBuddy 注入的 `sitecustomize.py` safe-delete shim 会拦截一切文件删除（`os.remove`/`shutil.rmtree`）并转回收站，对 pytest basetemp 路径会 `fail-closed`（`windows-sandbox-recycle-bin-unavailable`），导致 `test_import_data_io`/`test_resumable_upload`/`test_raster_timeseries_upsert` 等含文件删除的测试假阳性失败。shim 仅在 `CODEBUDDY_SESSION_ID`/`CLAUDE_SESSION_ID` 环境变量存在时激活，故本地须以前缀禁用：
```
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend -p no:cacheprovider --basetemp="Test/.pytest-be"
```
（CI 的 Ubuntu 环境无此 shim，不受影响。）`test_archive_safe.py` 需 `Code/backend/vendor/unrar/win-x64/UnRAR.exe`（gitignore，本地下载：rarlab `unrarw64.exe` `-s -d` 解出 CLI）；Linux/CI 可 `apt install unrar`。

## 快速验证（示例）

以"改天气瓦片"为例，仅凭本文档即可完成定位与验证：

1. 查"目录路由"→ 天气瓦片属 `Code/backend/`，路由入口 `app/api/weather_tile_routes.py`，服务 `app/weatherengine/tile_service.py`。
2. 查"改 X 则跑 Y"→ 先跑 `Env/Python312/python.exe -m pytest Test/backend/test_weather_tile_service.py -q`（仓库根执行）。
3. 查"命令指针"→ `python launch.py start fastapi` 起后端，再请求 `GET /weather/tiles/{layer_id}/{z}/{x}/{y}` 验证渲染。
4. 涉及缓存异常时查"高风险区"→ 必要时 `python launch.py flush` 清天气缓存后重试。

## 约定

- 后端主叙事是 `workflow-runs`；旧 `/tasks` 仅兼容桥接，勿新增依赖。
- 天气视口热路径走 `GET /weather/tiles/...`（`WeatherTileService`），不占 workflow 池；显式 tile workflow 仍可用但计入 `weather_tile` 池。
- 天气模型缺口：`visibility` 非 `gfs_global` 常 data-empty；80 m 风/温无原生场时外推。本地源需 `launch.py sync`。
- 活文档以各 README 为准；带日期的快照文档（`代码事实同步文档-*` 等）仅作历史参考，不覆盖现行结构。
- 提交信息遵循 Conventional Commits（`feat` / `fix` / `refactor` / `perf` / `chore` / `docs` / `test` / `style` / `build` / `ci`）。

## AI 知识库（`.ai/`，本地专用，不上传 GitHub）

所有 AI 提示 / 技能 / 计划 / 进度 / 记忆 / 文档集中在仓库根 **`.ai/`**，根目录表面仅保留 `AGENTS.md`、`CLAUDE.md`、`README.md` 三份文档。

- `.ai/rules/` —— **约定单一真源**：`project-conventions.md`（运行时/launch/改X则跑Y/高风险区/命名/提交）、`qingtian-decision-policy.md`（QingTian 决策策略）、`git-commit-message.md`（Conventional Commits）。各 AI 工具（Cursor/Trae/Copilot）的规则文件仅作指针，指向此处。
- `.ai/skills/` —— 可复用技能：`omega-sf-inversion`（FY/SMAP 反演+Matlab 一致性校验）、`multi-source-data-ingestion`（校园SSH/NAS/NSIDC/Earthdata）、`runtime-and-verify`（运行时与验证命令）、`contract-openapi-drift`（契约/OpenAPI 漂移防护）。
- `.ai/plans/` —— 计划。
- `.ai/progress/` —— 进度 / 验证追踪（FY-SMAP 系列、`ui-verification-steps.md`）。
- `.ai/memory/` —— AI 记忆 / 历史上下文（`archive/` 含 ~72 份历史计划与对话）。
- `.ai/docs/` —— 项目文档（原 `Doc/` 整体迁入：`design/` 架构设计、`specs/` 规范 spec、`reference/` 任务记录与验证报告）。

> 改代码前读 `.ai/rules/project-conventions.md`；做反演 / 数据接入读 `.ai/skills/` 对应技能。
