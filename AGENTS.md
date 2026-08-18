# AGENTS.md

面向 AI coding agent 的仓库导航。仅凭本文档即可定位模块与验证命令。

## 项目定位

CGDA（综合地理数据分析系统）：**面向课题组与大气研究院研究员**的科研数据分析平台（初代定位），统一承载 2D 平面地图（MapLibre 主路径）/ 3D 地球（Cesium，实验性非默认主链）、多源数据接入（本地 / GEE / Open-Meteo / 商业天气源）、动态时空结果展示与回传、多课题组算法模块化接入。已进入工程落地阶段：`workflow-runs` 主链、天气瓦片渲染、Celery/Redis/MinIO 基础设施均可运行。发布边界（单机构/单 API Key/SQLite、demo:// 与占位节点的环境开关、写限流策略）见 README.md「发布边界（初代）」。

## 目录路由

| 路径 | 职责 | 关键子目录 |
|------|------|-----------|
| `Code/backend/` | FastAPI + Celery：workflow 编排、weatherengine、统一瓦片、GEE | `app/api/routers/`（按域路由）、`app/services/workflow/`、`app/weatherengine/`、`app/tasks/`、`app/gee/`（测试已迁出至仓库根 `Test/backend/`） |
| `Code/frontend/` | Vue 3 + TypeScript + Vite + Pinia：MapLibre 2D、天气叠加、工作流交互 | `src/views/`、`src/components/`、`src/stores/`、`src/services/`、`src/composables/` |
| `Code/algorithms/` | Python 算法包：contracts / data_access / runner / publish | `providers/Python/`（lint/mypy 覆盖范围） |
| `Code/shared/` | 前后端共享协议与公共契约 | `contracts/` |
| `Code/infra/data-sync/` | 数据面 compose（Open-Meteo 同步，与运行栈隔离） | `docker-compose.yml`、`sync.sh` / `sync.ps1` |
| `Code/infra/gateway/` | **默认** Nginx 同域入口（静态 dist + 反代 FastAPI `:8000`） | `docker-compose.yml`、`nginx.conf`、`maintenance/`、`README.md` |
| `Docs/` | **公开文档仓库**：架构设计 / 规范协议 / 专题研究 / 代码审查 / 结题材料 / HTML 报告 | 见 `Docs/README.md` 索引 |
| `.ai/` | **AI 工作区（本地专用，不上传 GitHub）**：技能 / 规则 / 计划 / 进度 / 记忆 | `rules/`、`skills/`、`plans/`、`progress/`、`memory/` |
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
- 默认联调/演示入口为 **Nginx Gateway** `:5175`（静态 `Code/frontend/dist` + 反代 API）；与 Vite HMR 互斥。本地改前端热更新用 `launch.py start --vite` 或 `start frontend`。

## 命令指针（launch.py）

所有日常联调经根目录 `launch.py`（由 `start.bat` 等以 `Env/Python312` 调用）：

| 命令 | 作用 |
|------|------|
| `start.bat` 或 `Env\Python312\python.exe launch.py start` | 启动全部（Docker + FastAPI + 7 Worker + Beat + **Nginx Gateway**） |
| `Env\Python312\python.exe launch.py start --vite` | 同上，但前台改用 Vite HMR（会停 Gateway） |
| `Env\Python312\python.exe launch.py start <component>` | 单组件：`docker` / `fastapi` / `beat` / `worker` / `worker:<name>` / `frontend` / `gateway` / `backend` |
| `Env\Python312\python.exe launch.py start gateway` | 仅 Nginx 同域入口 `:5175`（`--rebuild-frontend` 可强制 rebuild dist） |
| `Env\Python312\python.exe launch.py restart` | 全量重启（**默认含 Gateway**）；改前端后建议加 `--rebuild-frontend` |
| `Env\Python312\python.exe launch.py restart backend` | **仅**重启 FastAPI + 全部 Worker + Beat（不动 Docker / Gateway / Vite）；改 `BACKEND_DATA_ROOT` 后必用 |
| `stop.bat` / `… launch.py stop` | 停止全部服务（含 Docker 与 gateway 容器） |
| `… launch.py stop gateway` | 仅停 Nginx Gateway |
| `… launch.py status` | 查看服务状态（Docker / FastAPI :8000 / 前端 :5175 / Gateway / Worker PID / volume） |
| `… launch.py logs [component] [-n N]` | 查看日志 |
| `… launch.py flush` | 清空 Redis DB + 应用天气文件缓存（**见高风险区**） |
| `… launch.py clean-cache` | 清理 `__pycache__` / `*.pyc` 与 Vite `node_modules/.vite`（**不**碰 Redis；代码更新后推荐） |
| `… launch.py start\|restart --clean-cache` | 启动/重启前先执行 `clean-cache` |
| `… launch.py sync [job]` | 数据面一次性同步（默认 `open-meteo-sync`） |

服务地址：FastAPI `http://127.0.0.1:8000`（docs `/docs`）、前端入口 `http://localhost:5175`（默认 Nginx Gateway；`--vite` 时为 Vite）、Open-Meteo API `http://127.0.0.1:8080`、Redis `:6379`、MinIO `:9100`（Console `:9101`）。

## 高风险区

改动以下区域前必须确认鉴权、加密或数据面隔离约束，避免破坏运行态或泄露凭据：

1. **`/config/*` 写操作与敏感读**：`app/api/config_routes.py` + `app/services/config_service.py` / `api_config.py` / `effective_config.py` / `credential_resolver.py`。写操作与敏感 GET 需有效凭据：会话 Cookie、用户 API Token 或 `backend_auth` 服务密钥（`X-API-Key`）。RBAC：三角色模型——`admin`（全权限）、`standard`（可读写/创建工作流，不可改高危配置）、`demo`（只读 + 受控数据传输）。配置管理端点（API Key / GEE / 天气 / 远程存储等）仅 `admin` 可写。development 且 `api_keys_enabled=false` 时仅 **直连 loopback** 可旁路。`/config/about` 仍公开。`PUT /config/data-source/paths` 写 `.env` 后须重启后端进程组。
1b. **部署配置真源 `deployment.config.json`**：`app/services/deployment_config.py` + `/config/deployment*` 端点 + 前端 `/deployment`（仅 admin）。加载链 `deployment.config.json → .env 覆盖 → Settings()`，文件损坏/版本不识 **fail-closed 拒启**（错误含 `.bak.1/.2/.3` 轮换恢复指引）。PUT 原子应用（备份→.env 镜像→data-sync/.env 双写→临时文件 os.replace，任一步失败整体回滚）；docker 组键变更需 `launch.py restart` 全量重启。凭据类不入 json（DB 面板热载）。治理矩阵见 `Docs/03-规范协议/配置文件治理说明.md`。
2. **用户鉴权**：`app/api/routers/auth_router.py`（`/auth/*` 登录、账户、个人 Token）、`session_service.py`、`user_repository.py`。角色/密码/禁用变更会吊销该用户全部会话与 Token。

3. **GEE / 共享加密主密钥**：`BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY` 须为 **64 hex chars（32-byte）**，启动时校验；同一把 key 加密 GEE SA、API keys、天气 provider、远程存储、门户凭据。非 development 缺 key 拒启；空 IV 明文行在生产拒绝解密。GEE API 账号管理 production 默认关闭。涉及 `/config/gee/accounts*` 与 `/gee/config`。

4. **flush（清缓存）**：`Env\Python312\python.exe launch.py flush` 执行 Redis `FLUSHDB` + 删除 `Code/backend/.data/cache/weather` 与 `weatherengine` 目录。会清空队列、缓存与限流/断路器状态，影响在线服务；**不**删 Open-Meteo Docker volume。仅在排障或强制刷新天气缓存时使用，勿在正常联调中随意执行。代码更新 / 模块导入怪错 / Vite 插件异常请用 **`launch.py clean-cache`**（只清本地 `__pycache__` 与 Vite `.vite`），再 `restart`；两者勿混用。

5. **Open-Meteo volume**：named volume `backend_open-meteo-data`（名可经 `Code/infra/data-sync/.env` 的 `OPEN_METEO_DATA_VOLUME` 覆盖），落在 Docker Desktop VHDX 内（`I:\Docker\DockerDesktop`）。**勿用 Windows 路径 bind mount** 替代。API 在 backend 运行栈（容器 `cgda-open-meteo`）；同步在 `Code/infra/data-sync`（`-p data-sync`）。两栈共享同一 volume 但 compose project 不同，改动 compose 时勿混用 project 名。

6. **生产禁止演示开关**：勿开启 `BACKEND_DEMO_SOURCES_ENABLED` / `BACKEND_NODE_STUBS_VISIBLE`；机构交付核对见 `Docs/04-执行部署/delivery-checklist.md`。

7. **地理数据根**：`BACKEND_DATA_ROOT`（及 `BACKEND_OUTPUT_ROOT`）为算法 / overlay / 图层 readiness 真源；**禁止**代码静默回退盘符。production 空根拒启。前端修改入口已收敛至部署配置中心 `/deployment`（仅 admin，`PUT /config/deployment` 三步状态机 preview→apply→`POST /config/service/restart`）；设置页 `PathConfigSection` 为只读展示（含 `pending_restart` 徽章）。

## "改 X 则跑 Y" 映射

| 改动区域 (X) | 定位模块 | 验证命令 (Y) |
|-------------|---------|-------------|
| 天气瓦片 | `app/weatherengine/tile_service.py`、`app/api/weather_tile_routes.py` | `Env/Python312/python.exe -m pytest Test/backend/test_weather_tile_service.py -q`（仓库根执行）；再 `python launch.py start fastapi` 后请求 `/weather/tiles/{layer_id}/{z}/{x}/{y}` |
| 天气工作流编译 | `app/services/workflow_graph_compiler.py`、`workflow_seeds/system/weather_*.json` | `Env/Python312/python.exe -m pytest Test/backend/test_workflow_graph_compiler.py -q` |
| 天气点查 / 引擎 | `app/weatherengine/service.py`、`fetch_gateway.py`、`providers/` | `Env/Python312/python.exe -m pytest Test/backend/test_weather_point_service.py Test/backend/test_weatherengine_service.py Test/backend/test_fetch_gateway.py -q` |
| 工作流运行 | `app/services/workflow/`、`app/api/routers/workflow_router.py` | `Env/Python312/python.exe -m pytest Test/backend/test_workflow_routes.py Test/backend/test_interaction_hub.py Test/backend/test_business_regression.py -q` |
| 工作流定时器 | `app/services/workflow_timer_service.py`、`workflow_timer_router.py`、`workflow_timer_tasks.py`；FE `WorkflowTimerPanel.vue` | `Env/Python312/python.exe -m pytest Test/backend/test_workflow_timer_service.py Test/backend/test_celery_tasks.py -q`（真实 cron 需 Beat + standard worker）；FE：`cd Code/frontend && npm run test -- workflow-timer` |
| 配置 / 鉴权 | `app/api/config_routes.py`、`app/services/config_service.py`、`credential_resolver.py` | `Env/Python312/python.exe -m pytest Test/backend/test_config_security.py Test/backend/test_api_keys_basemap.py Test/backend/test_auth.py -q` |
| runtime 调优键 / worker 配置同步 | `services/workflow/runtime_status_service.py`（PATCH 白名单+校验器）、`services/effective_config.py`（快照投影+getter）、`core/celery_app.py`（`_bootstrap_worker_runtime` worker 钩子）；治理见 `Docs/03-规范协议/配置文件治理说明.md` | `Env/Python312/python.exe -m pytest Test/backend/test_runtime_config_effect.py Test/backend/test_concurrency_config.py -q`；语义：PATCH 后 FastAPI 进程即时生效，worker 需新世代（`launch.py restart backend`） |
| 部署配置中心 | `app/services/deployment_config.py`、`app/api/config_routes.py`（`/config/deployment*`）、`app/core/config.py`（json→.env 加载链）；FE `DeploymentConfigView.vue`、`router.ts`；治理见 `Docs/03-规范协议/配置文件治理说明.md` | `Env/Python312/python.exe -m pytest Test/backend/test_deployment_config.py Test/backend/test_config_security.py -q`；FE：`cd Code/frontend && npm run test -- deployment-config auth-router` |
| 错误处理 / 可观测性 | `app/main.py`（全局异常）、`runtime_status_service.py`；FE `_http.ts`、`LogPanel`、`SystemStatusSettings` | `Env/Python312/python.exe -m pytest Test/backend/test_error_handlers.py Test/backend/test_interaction_hub.py -q`；`cd Code/frontend && npm run test -- _http auth-router` |
| 数据根 / 图层就绪 | `BACKEND_DATA_ROOT`、`env_file_upsert.py`、`service_restart.py`、`catalog_seeds/layer_descriptors.json`；FE `DeploymentConfigView.vue`（`/deployment` 修改入口，`PathConfigSection` 只读） | `Env/Python312/python.exe -m pytest Test/backend/test_data_source_paths.py Test/backend/test_data_root_policy.py -q`；改路径后 `launch.py restart backend`，再 `GET /layers` 看 `run_readiness` |
| GEE | `app/gee/`、`app/services/gee_bridge_service.py` | `Env/Python312/python.exe -m pytest Test/backend/test_gee_bridge_service.py -q` |
| 统一瓦片（底图） | `app/api/tile_routes.py`、`tile_provider_registry.py`、`tile_proxy_service.py`（天地图须用服务端 UA `CGDA-Backend/1.0`；街道=`tianditu-vec`+`tianditu-cva` overlay） | `Env/Python312/python.exe -m pytest Test/backend/test_unified_tile_service.py Test/backend/test_api_keys_basemap.py -q`；联调抽样 `GET /unified-tiles/tianditu-vec/{z}/{x}/{y}` 与 `…/tianditu-cva/…` 应 200 |
| 栅格导入 / CRS | `app/api/routers/import_router.py` | `Env/Python312/python.exe -m pytest Test/backend/test_import_raster_crs.py Test/backend/test_crs_detector.py -q` |
| Open-Meteo 双源 | `app/weatherengine/providers/`、`Code/infra/data-sync/.env.example` | `Env/Python312/python.exe -m pytest Test/backend/test_open_meteo_dual_providers.py Test/backend/test_open_meteo_performance.py -q`；本地：`python launch.py sync`（`visibility` 需 `gfs_global`） |
| overlay 本地图 | `overlay_registry.py`、`Tools/audit_overlay_assets.py` | `python Tools/audit_overlay_assets.py` |
| D2 / A1A2 NDVI | `modules/omega_avg_daily.py`、`ingest/ndvi_hdf_preprocess.py` | `Env/Python312/python.exe -m pytest Test/backend/test_omega_avg_algorithm.py Test/backend/test_omega_avg_daily_module.py -q`；`Env/Python312/python.exe -m pytest Test/algorithms/test_ndvi_hdf_preprocess.py -q` |
| 前端任意改动 | `Code/frontend/src/`（测试在 `Test/frontend/`） | `cd Code/frontend && npm run test && npm run lint && npm run build` |
| 图层工作区持久化 | `stores/layers/workspace-persist.ts`、`stores/layers/index.ts`；说明见 `Docs/02-架构设计/图层持久化说明.md`；命名见 `Docs/03-规范协议/layer-naming.md` | `cd Code/frontend && npm run test -- workspace-persist` |
| 图层命名 / 重命名 | `stores/layers/layer-naming.ts`、`layer-display-names.ts`、`active-layers.ts`（`setLayerDisplayName`） | `cd Code/frontend && npm run test -- layer-naming layer-display-names setLayerDisplayName`；`npm run check:catalog` |
| 天气瓦片 FE 调度 / 图例 | `weather-tile-manager.ts`、`weather-tile-banner.ts`、`effective-layer-symbology.ts` | `cd Code/frontend && npm run test -- weather-tile weather-tile-banner effective-layer-symbology` |
| 前后端契约 / OpenAPI | `Code/frontend/openapi.json`、`Code/shared/contracts/` | `cd Code/frontend && npm run check:openapi` |
| 图层目录漂移 | FE `catalog.ts` LAYER_LIBRARY ↔ BE `catalog_seeds/*_descriptors.json` | `cd Code/frontend && npm run check:catalog` |
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
- **提交操作硬约定（本机 Windows）**：commit 前必须先 `git add -A` 全量暂存（工作区无未暂存改动）再提交；禁止部分暂存提交与 pathspec 提交（`git commit -- <paths>`）。原因：pre-commit 的 stash/restore 机制在本机 Windows 文件锁下会吞掉未暂存改动（2026-08-16 事故，改动被回滚/文件被删）。丢失改动可从 `~/.cache/pre-commit/patch<时间戳>` 用 `git apply` 找回；详见 `.ai/rules/git-commit-message.md`。

## 前端错误与可观测性

- **404**：未知路由 → `NotFoundView`；登录 `?redirect=` 经 `safeRedirect` 防开放重定向。
- **会话过期**：API 401（非 `/auth/*` bootstrap）→ 自动跳转登录（`session-expired.ts`、`_http.ts`）。
- **服务不可用**：`ServiceConnectivityBanner` 轮询 `GET /health`；Gateway API 5xx → `Code/infra/gateway/maintenance/html/50x.html`。
- **客户端日志**：工具栏「日志」支持仅错误筛选与 JSON 导出；badge 显示 `errorCount`。
- **系统状态**：设置 → 系统状态（`GET /runtime/status`）。
- **Gateway 代理**：与 `vite.config.ts` 对齐（含 `/auth`、`/overlay-tiles`、`/health`）。
- 运维排障：`Docs/07-工程保障/error-handling-and-observability.md`。

## AI 知识库（`.ai/`，本地专用，不上传 GitHub）

所有 AI 提示 / 技能 / 计划 / 进度 / 记忆集中在仓库根 **`.ai/`**，根目录表面仅保留 `AGENTS.md`、`CLAUDE.md`、`README.md` 三份文档，公开文档在 `Docs/`。

- `.ai/rules/` —— **约定单一真源**：`project-conventions.md`（运行时/launch/改X则跑Y/高风险区/命名/提交）、`qingtian-decision-policy.md`（QingTian 决策策略）、`git-commit-message.md`（Conventional Commits）。各 AI 工具（Cursor/Trae/Copilot）的规则文件仅作指针，指向此处。
- `.ai/skills/` —— 可复用技能：`workflow-design`（种子命名/分类/标记与定时器）、`omega-sf-inversion`（FY/SMAP 反演+Matlab 一致性校验）、`multi-source-data-ingestion`（校园SSH/NAS/NSIDC/Earthdata）、`runtime-and-verify`（运行时与验证命令）、`contract-openapi-drift`（契约/OpenAPI 漂移防护）。
- `.ai/plans/` —— 计划。
- `.ai/progress/` —— 进度 / 验证追踪（FY-SMAP 系列、`ui-verification-steps.md`）。
- `.ai/memory/` —— AI 记忆 / 历史上下文（`archive/` 含历史计划与对话）。

> 改代码前读 `.ai/rules/project-conventions.md`；做反演 / 数据接入 / **工作流种子与定时器**读 `.ai/skills/` 对应技能。公开文档（架构、规范、审查、结题等）见 `Docs/`。
