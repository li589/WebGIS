# CGDA 项目 AI 编程硬约定（单一真源）

> 本文件是 CGDA（综合地理数据分析系统）所有 AI 编程工具共用的**约定单一真源**。
> 完整架构与目录路由见根目录 `AGENTS.md` / `README.md`。
> 各工具（Cursor / Trae / Copilot / Qoder / WorkBuddy）的规则文件仅保留指向本文件的**指针**，改动约定请直接改本文件。

---

## 0. 运行时（最高优先级）

- **后端 / 算法 / pytest / launch 唯一解释器 = `Env/Python312/python.exe`**（Windows）。
  绝不要用系统 PATH 里的 `python` 或 `C:\Program Files\Python\...`，否则依赖（如 `rarfile`、科学库）不一致会触发“环境幽灵问题”。
- 手动或脚本调用统一走 `Env\Python312\python.exe launch.py <cmd>`；`start.bat` / `stop.bat` 已强制该解释器。
- 前端需 Node 22（见 `Code/frontend/package.json` engines）。
- `Env/Python312` 是**本地联调运行时**，不是 Docker 生产镜像；交付部署另走容器/服务器环境。

## 1. 本地联调命令（launch.py）

所有日常联调经根目录 `launch.py`（由 `start.bat` 等以 `Env/Python312` 调用）：

| 命令 | 作用 |
|------|------|
| `Env\Python312\python.exe launch.py start` | 启动全部（Docker + FastAPI + 7 Worker + Beat + **Nginx Gateway**） |
| `… launch.py start --vite` | 同上，Gateway 同域 + 背后 Vite HMR（入口仍 `:5175`，Vite `:5174`） |
| `… launch.py reload gateway` | Nginx 配置热重载（不重建容器） |
| `… launch.py start <component>` | 单组件：`docker` / `fastapi` / `beat` / `worker` / `worker:<name>` / `frontend` / `gateway` / `backend` |
| `… launch.py start gateway` | 仅 Nginx 同域入口 `:5175`（`--rebuild-frontend` 可强制 rebuild dist） |
| `… launch.py restart` | 全量重启（**默认含 Gateway**）；改前端后建议加 `--rebuild-frontend` |
| `… launch.py restart backend` | 仅重启 FastAPI + Worker + Beat（改 `BACKEND_DATA_ROOT` 后必用；不动 Docker/Gateway） |
| `… launch.py stop [gateway]` | 停止全部 / 仅停 Gateway |
| `… launch.py status` | 查看服务状态（Docker / FastAPI :8000 / 前端 :5175 / Gateway / Worker PID / volume） |
| `… launch.py logs [component] [-n N]` | 查看日志 |
| `… launch.py flush` | 清空 Redis DB + 应用天气文件缓存（**见高风险区**；**永不**由 start/restart 自动执行） |
| `… launch.py clean-cache` | 手动清理 `__pycache__` / `.pyc` 与 Vite `.vite`（**不**碰 Redis） |
| `… launch.py start\|restart` | **默认**按组件矩阵自动 clean（pycache / Vite）；`--no-clean-cache` 跳过；`--clean-cache` 强制两者全清 |
| `… launch.py sync [job]` | 数据面一次性同步（默认 `open-meteo-sync`） |

服务地址：FastAPI `http://127.0.0.1:8000`（docs `/docs`）、前端入口 `http://localhost:5175`（默认 Nginx Gateway 静态；`--vite` 时同域 HMR）、Open-Meteo API `http://127.0.0.1:8080`、Redis `:6379`、MinIO `:9100`（Console `:9101`）。

联调缓存分层、症状对照与排障顺序见 **`Docs/07-工程保障/联调缓存与生效边界.md`**（实现：`launch/cache_hygiene.py`）。

> Windows 启动 Docker 相关服务（`start` / `start docker` / `sync`）时，Docker Desktop 与运行终端都要**以管理员身份**运行，否则镜像无法拉取/volume 读失败/部分容器起不全（见 `.ai/docs/reference/本地联调环境说明.md`）。

## 2. 验证命令（改 X 则跑 Y）

后端 / 算法测试集中在仓库根 `Test/`（`Test/backend/`、`Test/algorithms/`），仓库根用 `Env/Python312/python.exe -m pytest Test/backend` 执行，需 `REDIS_URL` 与 `ENVIRONMENT=test`（见 `.github/workflows/ci.yml`）。前端测试在 `Test/frontend/`，由 `Code/frontend/vite.config.ts` 的 `test.include` 跨出 root 加载。CI 质量门：pre-commit（全量）→ pytest → vitest → check:openapi。

**WorkBuddy 内跑后端测试硬约定**：safe-delete shim（`sitecustomize.py`）拦截一切文件删除转回收站，对 basetemp 路径 fail-closed，致 `test_import_data_io`/`test_resumable_upload`/`test_raster_timeseries_upsert` 等假阳性。shim 仅在 `CODEBUDDY_SESSION_ID`/`CLAUDE_SESSION_ID` 存在时激活，本地须前缀禁用：
`CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend -p no:cacheprovider --basetemp="Test/.pytest-be"`
（CI Ubuntu 无此 shim。）`test_archive_safe.py` 需 `Code/backend/vendor/unrar/win-x64/UnRAR.exe`（gitignore；rarlab `unrarw64.exe -s -d` 解出）；Linux/CI `apt install unrar`。

| 改动区域 (X) | 定位模块 | 验证命令 (Y) |
|-------------|---------|-------------|
| 天气瓦片 | `app/weatherengine/tile_service.py`、`app/api/weather_tile_routes.py` | `Env/Python312/python.exe -m pytest Test/backend/test_weather_tile_service.py -q`（仓库根执行）；再起 fastapi 请求 `/weather/tiles/{layer_id}/{z}/{x}/{y}` |
| 天气工作流编译 | `app/services/workflow_graph_compiler.py`、`workflow_seeds/system/weather_*.json` | `Env/Python312/python.exe -m pytest Test/backend/test_workflow_graph_compiler.py -q` |
| 天气点查 / 引擎 | `app/weatherengine/service.py`、`fetch_gateway.py`、`providers/` | `Env/Python312/python.exe -m pytest Test/backend/test_weather_point_service.py Test/backend/test_weatherengine_service.py Test/backend/test_fetch_gateway.py -q` |
| 工作流运行 | `app/services/workflow/`、`app/api/routers/workflow_router.py` | `Env/Python312/python.exe -m pytest Test/backend/test_workflow_routes.py Test/backend/test_interaction_hub.py Test/backend/test_business_regression.py -q` |
| 工作流定时器 | `app/services/workflow_timer_service.py`、`app/api/routers/workflow_timer_router.py`、`app/tasks/workflow_timer_tasks.py`；FE `WorkflowTimerPanel.vue` | `Env/Python312/python.exe -m pytest Test/backend/test_workflow_timer_service.py Test/backend/test_celery_tasks.py -q`；真实 cron 需 `launch.py start beat` + standard worker；FE：`cd Code/frontend && npm run test -- workflow-timer` |
| 配置 / 鉴权 | `app/api/config_routes.py`、`app/services/config_service.py` | `Env/Python312/python.exe -m pytest Test/backend/test_config_security.py Test/backend/test_api_keys_basemap.py -q` |
| runtime 调优键 / worker 配置同步 | `services/workflow/runtime_status_service.py`（白名单+校验器）、`services/effective_config.py`（投影+getter）、`core/celery_app.py`（`_bootstrap_worker_runtime` 钩子） | `Env/Python312/python.exe -m pytest Test/backend/test_runtime_config_effect.py Test/backend/test_concurrency_config.py -q`；改动语义：runtime PATCH FastAPI 进程即时、worker 需新世代（`launch.py restart backend`）；`task_memory_budget_mb`/`task_cpu_budget_cores` 为预留声明值（无调度准入消费，UI 已标注） |
| 数据根 / 图层就绪 | `BACKEND_DATA_ROOT`、`env_file_upsert.py`、`service_restart.py`、`catalog_seeds/layer_descriptors.json`；FE `DeploymentConfigView.vue`（`/deployment` 修改入口，`PathConfigSection` 只读） | `Env/Python312/python.exe -m pytest Test/backend/test_data_source_paths.py Test/backend/test_data_root_policy.py -q`；改路径后 `launch.py restart backend`，再 `GET /layers` 看 `run_readiness` |
| GEE | `app/gee/`、`app/services/gee_bridge_service.py` | `Env/Python312/python.exe -m pytest Test/backend/test_gee_bridge_service.py -q` |
| 统一瓦片（底图） | `app/api/tile_routes.py`、`tile_provider_registry.py`、`tile_proxy_service.py`（天地图须用服务端 UA `CGDA-Backend/1.0`；街道=`tianditu-vec`+`tianditu-cva` overlay） | `Env/Python312/python.exe -m pytest Test/backend/test_unified_tile_service.py Test/backend/test_api_keys_basemap.py -q`；联调抽样 `GET /unified-tiles/tianditu-vec/{z}/{x}/{y}` 与 `…/tianditu-cva/…` 应 200 |
| 栅格导入 / CRS | `app/api/routers/import_router.py` | `Env/Python312/python.exe -m pytest Test/backend/test_import_raster_crs.py Test/backend/test_crs_detector.py -q` |
| Open-Meteo 双源 | `app/weatherengine/providers/`、`.env.open-meteo.example` | `Env/Python312/python.exe -m pytest Test/backend/test_open_meteo_dual_providers.py Test/backend/test_open_meteo_performance.py -q`；本地 `python launch.py sync` |
| overlay 本地图 | `overlay_registry.py`、`Tools/audit_overlay_assets.py` | `python Tools/audit_overlay_assets.py` |
| D2 / A1A2 NDVI | `modules/omega_avg_daily.py`、`ingest/ndvi_hdf_preprocess.py` | `Env/Python312/python.exe -m pytest Test/backend/test_omega_avg_algorithm.py Test/backend/test_omega_avg_daily_module.py -q`；`Env/Python312/python.exe -m pytest Test/algorithms/test_ndvi_hdf_preprocess.py -q` |
| 前端任意改动 | `Code/frontend/src/`（测试在 `Test/frontend/`） | `cd Code/frontend && npm run test && npm run lint && npm run build` |
| 天气瓦片 FE 调度 / 图例 | `weather-tile-manager.ts`、`weather-tile-banner.ts`、`effective-layer-symbology.ts` | `cd Code/frontend && npm run test -- weather-tile weather-tile-banner effective-layer-symbology` |
| 前后端契约 / OpenAPI | `Code/frontend/openapi.json`、`Code/shared/contracts/` | `cd Code/frontend && npm run check:openapi` |
| Python 算法包 | `Code/algorithms/providers/Python/` | `pre-commit run --all-files`（ruff + mypy 覆盖 `algorithms/`） |
| 任意提交前 | 全仓库 | `pre-commit run --all-files`（ruff / mypy / eslint / prettier / 契约检查） |

## 3. 高风险区（改动前必须确认鉴权 / 加密 / 数据面隔离）

1. **`/config/*` 写操作** 与 `POST /import/raster`：需 `X-API-Key`。development 且未启用 keys 时仅 **loopback** 旁路（`BACKEND_DEV_AUTH_BYPASS=true` 可放开局域网）。鉴权密钥 = `backend_auth` DB 覆盖 env。覆盖图层 URI、天气 provider、remote-storage、**数据根路径**等运行真源，改错会污染配置。`PUT /config/data-source/paths` 写 `.env` 后须 `restart backend`；`POST /config/service/restart` 受 `BACKEND_UI_RESTART_ENABLED` 门禁（默认仅 development），响应 `components` 恒为全量后端组。
2. **共享加密主密钥**：`BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY` 须 64 hex chars；启动校验；加密 GEE SA / API keys / weather / remote / portal。非 development 缺 key 拒启；生产拒绝空 IV 明文行。GEE API 账号管理 production 默认关闭。
3. **`launch.py flush`**：执行 Redis `FLUSHDB` + 删除 `Code/backend/.data/cache/weather` 与 `weatherengine` 目录。会清空队列、缓存与限流/断路器状态，影响在线服务；**不**删 Open-Meteo Docker volume。仅排障或强制刷新天气缓存时用。**start/restart 永不自动 flush**。代码更新 / 导入怪错 / Vite 插件异常依赖 start/restart 默认矩阵 clean，或手动 **`launch.py clean-cache`**；勿与 `flush` 混用。详见 `Docs/07-工程保障/联调缓存与生效边界.md`。
4. **Open-Meteo volume**：named volume `backend_open-meteo-data`（名可经 `Code/infra/data-sync/.env` 的 `OPEN_METEO_DATA_VOLUME` 覆盖），落在 Docker Desktop VHDX 内。**勿用 Windows 路径 bind mount** 替代。API 在 backend 运行栈（容器 `cgda-open-meteo`）；同步在 `Code/infra/data-sync`（`-p data-sync`）。两栈共享同一 volume 但 compose project 不同，改动 compose 时勿混用 project 名。
5. **地理数据根**：`BACKEND_DATA_ROOT` / `BACKEND_OUTPUT_ROOT` 为算法与图层 readiness 真源；禁止代码静默回退盘符；production 空根拒启。前端修改入口已收敛至部署配置中心 `/deployment`（仅 admin，`PUT /config/deployment` 三步状态机 preview→apply→`POST /config/service/restart`）；设置页 `PathConfigSection` 只读展示（含 `pending_restart` 徽章）。
6. **写/瓦片限流**：`/config` `/import` `/workflow-runs` 写方法 + `/weather/tiles` GET（`BACKEND_WRITE_RATE_LIMIT_PER_MINUTE` / `BACKEND_WEATHER_TILE_RATE_LIMIT_PER_MINUTE`）；development/test 旁路。

## 4. 命名与协议约定

- HTTP JSON 字段统一 `snake_case`；标识用 `*_id` / `*_key`；时间用 ISO 8601；空间范围用 `bbox + crs`；枚举用小写英文。
- **Celery 元数据仅支持 US-ASCII**：所有 `WorkflowResultReference.title` 和 `create_artifact_result_ref(title=...)` 必须是纯英文，用中文会 `ValueError`。
- 共享协议事实来源：`Code/shared/contracts` 与前端由 OpenAPI 生成的 `src/types/api-contracts.ts`（**勿手改**）。
- 后端主链是 `workflow-runs`；旧 `/tasks` 仅兼容桥接，**勿新增依赖**。
- 天气视口热路径走 `GET /weather/tiles/...`（`WeatherTileService`），不占 workflow 池；显式 tile workflow 仍可用但计入 `weather_tile` 池。
- 天气模型缺口：`visibility` 非 `gfs_global` 常 data-empty；80 m 风/温无原生场时外推。本地源需 `launch.py sync`。

## 5. 代码风格（与既有工具对齐，勿自创）

- Python：ruff 默认规则集（E4/E7/E9/F）+ ruff-format（88 宽、4 空格）。`mypy.ini` 当前为宽松基线，`disallow_untyped_defs=False`。
- 前端：Prettier（`singleQuote`、`semi:false`、2 空格、100 宽、LF）+ ESLint flat config（`no-console` 仅允许 warn/error，未用变量以 `_` 前缀忽略）。`src/types/api-contracts.ts` 由 OpenAPI 自动生成，**勿手改**。
- 全局基线见根 `.editorconfig`（Python 4 空格 / 88 宽；TS·Vue 2 空格 / 100 宽；LF / UTF-8 / 去尾随空格）。
- 提交信息遵循 Conventional Commits（见 `.ai/rules/git-commit-message.md`）。
- **提交操作硬约定（本机）**：commit 前必须 `git add -A` 全量暂存（工作区无未暂存改动）再提交；禁止部分暂存提交与 pathspec 提交（`git commit -- <paths>`）——pre-commit 的 stash 机制在本机 Windows 文件锁下会吞掉未暂存改动（2026-08-16 事故）。恢复方法与详细规则见 `.ai/rules/git-commit-message.md`。

## 6. 目录职责（快速定位）

- `Code/backend/`：FastAPI + Celery。路由入口 `app/api/routers/__init__.py`；瓦片另走 `app/api/tile_routes.py`（底图 `/unified-tiles`）与 `app/api/weather_tile_routes.py`（天气 `/weather/tiles`）；配置写操作走 `app/api/config_routes.py`。
- `Code/frontend/`：Vue 3 + TS + Vite + Pinia，MapLibre 2D 主链、天气叠加、工作流交互。
- `Code/algorithms/providers/Python/`：算法包，`run_job()` 统一入口，`modules + workflow` 主导（pipeline 仅兼容层）。
- `Code/shared/`：前后端共享契约。`Code/infra/`：数据面 compose（与运行栈隔离）。
- `Tools/`：**禁止**放主体功能与运行时模块（仅一次性下载 / 校验脚本）。
- `Doc/` 已并入 `.ai/docs/`（design / specs / reference）；根目录进度/验证文档已并入 `.ai/progress/`。

## 6.5 问题反馈 → AI 修复闭环（入口）

- 用户反馈中心 `/feedback/` 服务端反馈落盘：`BACKEND_DATA_ROOT/_runtime/feedback/CGDA-BUG-*/`（`report.json` + `meta.json` + 可选 `attachments/` + `response.json`）。
- **扫描约定**：会话开始或提到"反馈/问题/报错"时先扫：
  `Env\Python312\python.exe Tools/feedback_triage.py --open`（AI 待办）；单条详情 `--show <id>`。
- 完整处理 SOP（分析→修复→测试→提交→处理台发布进展闭环）：**`.ai/rules/feedback-triage.md`**；
  被指派处理反馈时加载提示词 **`.ai/prompts/feedback-fix.md`**。
- 修复提交用 `fix(<scope>): 修复反馈 CGDA-BUG-xxxx：<根因与修法>`；发布进展经处理台
  `/feedback/console.html` 或 `PUT /feedback/api/reports/{id}/response`（admin）。
- 后端实现：`app/api/routers/feedback_router.py` + `app/services/feedback_store.py`；测试 `Test/backend/test_feedback_api.py`。

## 7. 避坑

- 不要在个人目录（Desktop / Downloads / Documents）做递归删除或 `rm -rf`；本项目数据清理走 `launch.py flush`（受限）。
- 大规模数据接入（FY/SMAP 等）注意双路 NDVI 与静态辅助数据（ancillary）路径，避免错用源。
- 不要在 `.gitignore` 已排除的路径（`.data`、`imports_output`、`tmp`、`.pytest_tmp`、`Test/.pytest-*`）里落源码。
- `.ai/` 为本地专用上下文（AI 提示/技能/计划/进度/记忆/文档），**不进 GitHub**；协作者的工具规则指针文件可保留在 GitHub。

## 8. Git 沙箱安全（2026-08-22 事故沉淀）

沙箱会静默杀死涉及批量删除的 git 操作（stash / checkout 切分支 / merge），已两次造成 `.git/refs` 丢失。
**完整规范（禁用清单 / 提交纪律 / .git 恢复套路 / 安全回退姿势）见 `.ai/rules/git-safety.md`**——动手做任何"回退/还原/stash"类操作前必读。
核心三条：沙箱内禁 `git stash`；文件级还原只用 `git show <sha>:<path> > <path>`；commit 后立即 push（GitHub 是唯一可靠备份）。

## 9. 前端依赖版本兼容（2026-08-22 事故沉淀）

vue / pinia 已在 `package.json` **精确 pin**（3.5.38 / 3.0.4，禁 `^` 范围）；项目内**禁用 `storeToRefs`**
（Pinia 3.0.4 遍历 store 遇 undefined 属性访问 `.effect` 即崩），统一 `toRef(store, key)` 逐字段模式。
dist rebuild 后必须浏览器冒烟。**完整规范（版本升级流程 / 构建纪律 / 崩溃定位速查）见 `.ai/rules/frontend-dependency-compat.md`**。
事故复盘：`Docs/01-协作规范/事故复盘-2026-08-22-git沙箱与前端依赖版本.md`。
