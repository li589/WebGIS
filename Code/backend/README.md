# Backend

`Code/backend/` 是本项目的后端服务根目录。它承接前端请求、组织工作流运行、管理状态与事件、回传结果，并作为 Python 算法包、天气引擎与 Web 平台之间的桥梁。

## 当前后端定位

核心不是 CRUD API，而是一条稳定的任务执行链：

- 接收前端或外部系统请求
- 校验并标准化工作流提交参数（engine request registry）
- 创建运行记录、状态流和事件流
- 选择同步执行或 Celery 异步执行
- 经 bridge 调用 weather / Python provider / download / GEE
- 管理 artifact、结果引用、预览图与统一瓦片
- 向前端提供查询、元数据和结果读取接口

工作流编排已从单体 `interaction_hub` 拆分为 `app/services/workflow/` 下的聚焦服务，经 `service_container.py` 对外暴露。

## 当前可用能力（按域）

### 系统 / 控制流

- `GET /health`
- `POST /workflow-runs`
- `GET /workflow-runs/{run_id}`
- `GET /workflow-runs/{run_id}/view`
- `GET /workflow-runs/{run_id}/events`
- `POST /workflow-runs/{run_id}/cancel`
- `POST /workflow-runs/{run_id}/retry`
- `GET /runtime/status`
- `GET /runtime/config` / `PATCH /runtime/config`
- `GET /runtime/metrics`
- `GET /runtime/api-config`（及 provider 变体）

### 目录 / 图层 / 叠加

- `GET /layers`
- `GET /demo/layers/snapshots`、`GET /demo/layers/{layer_id}/snapshot`
- `GET /geo/transform`
- `GET /overlays`、`/overlay-preview/{layer_id}`、`/overlay-bounds/{layer_id}`、`/overlay-value/{layer_id}`

### 天气

- `GET /weather/point`
- `GET /weather/workflows`（及 diagnostics / 按名查询）
- `GET /weather/tiles/{layer_id}/{z}/{x}/{y}`（**天气 GeoJSON 瓦片正式入口**）

### 底图代理与缓存

- `GET /unified-tiles/{layer_id}/{z}/{x}/{y}`（**底图栅格正式入口**；天气 layer 将 404）
- `GET /runtime/tiles/providers`
- `GET /runtime/tiles/cache/stats`、`POST /runtime/tiles/cache/clear`
- 旧前缀 `/tiles/...` 已移除

### 配置 / 设置面（`/config/*`）

前端「系统设置」面板消费这些接口（开发态 Vite 需代理 `/config`）：

- `GET /config/general`、`/config/about`、`/config/data-source`
- `GET|PUT|DELETE /config/api-keys*`（天地图 / 百度等；运行真源 = DB 覆盖 env）
- `GET|POST|DELETE /config/gee/accounts*`、`GET /config/gee/runtime`
- `GET /config/weather`、`GET|PUT /config/weather/providers*`

**安全（2026-07-16）**：所有 `/config/*` 写操作与 `POST /import/raster` 需 `X-API-Key`（development 且未启用 keys 时可旁路）。  
鉴权密钥 = `backend_auth` DB 覆盖 env（`effective_config`）。非 development 必须配置 `BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY`。

### 算法 / Provider / Artifact / 导入 / GEE

- `GET /algorithm/workflows`（及 panel-schema / ui-schema / diagnostics）
- `GET /provider/workflows`（及 diagnostics / 按名查询）
- `GET /artifacts/{artifact_id}`、`GET /artifacts/{artifact_id}/preview.png`
- `POST /import/raster`
- `GET /gee/config`（及 limits / status / environment）
- GEE 业务路由可按配置挂载

执行模式：支持 `sync` / `celery`。旧 `/tasks` 仍经 `task_store` 软下线桥接到 `workflow-runs`，不再作为主叙事。

## 工作流容量双池

`POST /workflow-runs` 提交时按 payload 分类计入不同活跃 run 上限：

| 池 | 判定 | 配置 | 默认 |
|----|------|------|------|
| business | 非瓦片 workflow（分析 / 课题组 / GEE / 非瓦片天气 DAG 等） | `BACKEND_MAX_ACTIVE_RUNS` / runtime `max_active_runs` | 8 |
| weather_tile | `weather_request` DAG 含 `weather_tile_render` | `BACKEND_MAX_ACTIVE_WEATHER_TILE_RUNS` / runtime `max_active_weather_tile_runs` | 16 |

前端视口天气瓦片热路径应走 `GET /weather/tiles/...`（`WeatherTileService`），不占上述任一 workflow 池。显式 tile workflow 仍可用，计入 `weather_tile` 池。

## 当前实现事实

- `retry_pending` 中间态与自动重试语义
- `FailureCategory` 失败分类
- `BridgeExecutionError` 作为 bridge 层统一失败协议
- `source_fetcher` 驱动的真实下载抓取链
- `weatherengine` fallback 与 weather workflow DAG 双路径
- 天气网格缓存、请求去重、断路器与统一瓦片 provider registry
- artifact preview 路由，供前端以 PNG 方式读取 COG 结果
- OpenAPI 可供前端 `openapi-typescript` 生成类型

## 目录结构

```text
backend/
├─ app/
│  ├─ api/                 # REST 路由（按域拆分）
│  │  ├─ routers/          # health / workflow / runtime / layer / weather / …
│  │  ├─ tile_routes.py
│  │  ├─ weather_tile_routes.py
│  │  └─ gee_config_routes.py
│  ├─ core/                # 配置、Celery、日志、Redis
│  ├─ services/            # 业务服务、桥接、目录、瓦片、存储
│  │  └─ workflow/         # submission / lifecycle / runtime / persistence …
│  ├─ tasks/               # Celery 任务
│  ├─ weatherengine/       # 点查、网格、瓦片、天气 DAG 节点
│  ├─ workflow_engine/     # 通用 DAG 执行器
│  ├─ gee/                 # Earth Engine 嵌入模块
│  └─ main.py
├─ docker-compose.yml      # Redis + MinIO
├─ requirements.txt
└─ tests/
```

## 当前核心模块

### `app/api/`

只做参数接收、调用服务层和返回响应。按域拆分为多个 router，不再使用单体 `routes.py`。

### `app/core/`

配置、Celery app、日志、Redis 客户端等基础设施。

### `app/services/workflow/`

替代原 `interaction_hub` 的工作流域服务：

| 模块 | 职责 |
|------|------|
| `submission_service.py` | 提交、派发、容量校验 |
| `lifecycle_service.py` | 取消、重试、超时与失败收口 |
| `transition_builder.py` | 状态转换构建 |
| `persistence_service.py` | 持久化与事件记录 |
| `runtime_status_service.py` | runtime 配置 / 状态 / 前端命令 |
| `follow_up_dispatch_service.py` | follow-up 派发与陈旧 run 清理 |
| `service_container.py` | 模块级服务实例组装 |

相关辅助：`engine_request_registry.py`、`workflow_request_resolver.py`、`failure_classifier.py`、`bridge_protocol.py`。

### 其他重要服务

- `python_provider_bridge_service.py` / `weather_bridge_service.py` / `gee_bridge_service.py`
- `source_fetcher.py`、`download_service.py`、`cache_service.py`
- `tile_provider_registry.py`、`tile_proxy_service.py`
- `result_storage.py`、`result_view_service.py`、`object_store.py`
- `layer_catalog.py`、`overlay_registry.py`

### `app/weatherengine/`

- `service.py`：`/weather/point` 与 fallback map_layer 产物
- `tile_service.py`：z/x/y GeoJSON 瓦片
- `workflow_service.py` + `nodes/*`：天气 DAG（风场、温湿降水气压能见度、tile_render 等）
- `client.py`：网格预报拉取（Open-Meteo 风格）

### `app/tasks/`

通用 workflow task、download follow-up、weather 刷新等 Celery 入口。

## 后端运行模型

控制流 + 数据流双通道：

1. 前端提交 workflow request
2. 后端创建 run 记录与事件流
3. 同步执行器或 Celery worker 执行
4. bridge / provider / weatherengine 产出结果引用
5. 控制流：`workflow-runs/{run_id}` / `events` 回传状态
6. 数据流：`view`、artifact、preview、`unified-tiles` 按需读取

补充：

- 控制流状态含 `retry_pending`
- `ResultKind.map_layer` 是天气图层、GeoJSON 与栅格预览链的重要数据面入口
- 推荐新前端消费 `/unified-tiles/...`，不要新增对 deprecated 天气/底图瓦片路径的依赖

## 运行与部署

- 本地一键：仓库根 `launch.py` / `start.bat`（编排 compose + API + 多队列 worker + 前端）
- 基础设施：`docker-compose.yml` 提供 Redis `:6379`、MinIO `:9100/:9101`
- 环境变量参考 `.env.example`
- 亦可使用 `Env/backend/` 脚本做单项启动

## 推荐阅读顺序

1. `Code/backend/README.md`
2. `Code/shared/contracts/README.md`
3. `Code/docs/双通道接口设计总结.md`
4. `Code/algorithms/providers/Python/README.md`
5. `Code/algorithms/providers/docs/backend_integration_contract.md`

## 说明

- `workflow-runs` 是主线；旧 `/tasks` 仅为兼容桥接
- 文档与代码需持续对齐路由名称、任务模型与结果模型
- 带日期的阶段快照不覆盖本 README 的现行结构描述
