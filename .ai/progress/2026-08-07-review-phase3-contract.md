# CGDA 契约一致性审查清单（Phase 3）

- 审查人：QA 严过关（software-qa-engineer）
- 日期：2026-08-07
- 范围：G5 契约（shared contracts ↔ OpenAPI ↔ 前端 TS；命名约定；关键接口抽样）
- 方式：只读审查，未修改任何代码

## 1. drift 检查结果（命令输出/降级说明）

- 命令：`cd Code/frontend && npm run check:openapi`（= `python ../backend/scripts/check_openapi_drift.py`）
- 系统 python(3.13) 缺 fastapi，首次运行失败；改用仓库解释器后通过：
  `"Env/Python312/python.exe" ../backend/scripts/check_openapi_drift.py` → **`OK: critical OpenAPI paths match committed frontend/openapi.json`**（12 个关键前缀全覆盖：/weather /unified-tiles /config /workflow-runs /workflow-definitions /import /layers /export /overlay-tiles /runtime /gee /artifacts）
- 注意：该脚本只比对路径+方法存在性，**不比对 schema 字段与 security**（见 §2 两项补充发现，为静态比对补出）。

## 2. shared contracts vs 前端类型 漂移问题

| ID | 位置 | 问题 | 严重度(P0-P3) | 建议 |
|----|------|------|--------------|------|
| ~~D-1~~ | ~~`Code/shared/contracts/api_contracts.py`~~ | ~~legacy `/tasks/` API 已从后端移除，但 Task* 模型仍留在共享契约~~ | ~~P2~~ | **✅ 已清除（2026-08-12）**：旧 Task* 模型已从 `api_contracts.py` 完全清除，`/tasks` 路由已从代码和 openapi.json 中移除。见 `2026-08-12-p2-quick-wins.md` |
| ~~D-2~~ | ~~`Code/frontend/openapi.json`~~ | ~~OpenAPI 未声明 `securitySchemes`/任何 security~~ | ~~P2~~ | **✅ 已完成（2026-08-12）**：`main.py` 补充 `SessionAuth`（cookie）+ `BearerAuth`（HTTP Bearer）声明；`openapi.json` 已重导。见 `2026-08-12-p2-quick-wins.md` |

补充（字段级比对结论）：20 个核心模型（LayerDescriptor / LayerCatalogResponse / BoundingBox / SpatialFilter / TimeRange / WorkflowSubmitRequest / WorkflowAcceptedResponse / WorkflowRunStatusResponse / WorkflowResultReference / WorkflowEvent / WorkflowRunViewResponse / WeatherPointResponse / WeatherPointCurrent / RuntimeConfigUpdateRequest / RuntimeConfigUpdateResponse / ApiKeyUpdateRequest / RemoteStorageUpsertRequest 等）在 shared contracts ↔ openapi.json 之间字段与 required 完全一致，无漂移（Task* 三个模型除外，见 D-1）。

## 3. 命名约定违规

| ID | 位置 | 问题 | 严重度 | 建议 |
|----|------|------|--------|------|
| N-1 | `Code/backend/app/services/gee_bridge_service.py:386` | `WorkflowResultReference(title="GEE 导出状态")` 非 US-ASCII，违反 Celery 元数据纯英文约定 | P2 | title 改英文（如 "GEE Export Status"） |
| N-2 | `Code/algorithms/providers/lab_output.py:39,66` | `title="课题组模型输出"` 非 US-ASCII（流入 provider 结果 ref） | P2 | 改英文（如 "Lab Model Output"） |
| ~~N-3~~ | ~~`Code/shared/contracts/api_contracts.py` WeatherPointCurrent~~ | ~~9 个 hPa 字段含大写，违反严格 snake_case~~ | ~~P2~~ | **✅ 已完成（2026-08-12）**：9 个 hPa 字段添加 `Field(description=...)`（m/s, °, °C），保留命名作为白名单例外。见 `2026-08-12-p2-quick-wins.md` |
| ~~N-4~~ | ~~`Code/shared/contracts/config_contracts.py`~~ | ~~时间戳声明为 `str` 而非 `datetime`~~ | ~~P2~~ | **✅ 已完成（2026-08-12）**：新增 `OpenMeteoSyncStatusResponse` 模型（`finished_at: datetime | None`）+ `response_model` 接线；`workflow_router.py` `str()` → `strftime()`。见 `2026-08-12-p2-quick-wins.md` |

通过项：
- 枚举全部小写英文（ExecutionStatus / ResultKind / MapMode / LayerSourceType / TimeGranularity 等，openapi 全量扫描无非小写值）
- BoundingBox 含 west/south/east/north + crs 符合 bbox+crs 约定
- TimeRange.start_at / end_at 及 workflow run 状态时间均为 `format: date-time`（ISO 8601）

## 4. 接口抽样核对结果

| ID | 接口 | 后端定义 | 前端使用 | 一致? | 备注 |
|----|------|----------|----------|------|------|
| I-1 | GET /layers | `Code/backend/app/api/routers/layer_router.py:40` list_layers → LayerCatalogResponse，run_readiness 由 describe_layer_run_readiness 动态填充 | `Code/frontend/src/stores/layers/index.ts:464` 读 descriptor.run_readiness / run_readiness_summary / run_readiness_notes | ✅ | 契约字段与 TS 一致 |
| I-2 | GET /weather/tiles/{layer_id}/{z}/{x}/{y} | `Code/backend/app/api/weather_tile_routes.py`（prefix=/weather/tiles，GET /{layer_id}/{z}/{x}/{y}） | `Code/frontend/src/services/weather-tile-api.ts:303` fetchWeatherTile 拼同路径 | ✅ | openapi 有对应 path |
| I-3 | /workflow-runs 主链 | `Code/backend/app/api/routers/workflow_router.py`：POST /workflow-runs、GET 列表 / 详情 / view / events、POST cancel / retry | TS operations 齐全（`Code/frontend/src/types/api-contracts.ts`） | ✅ | openapi.json 含全部子路径 |
| I-4 | /config/* 写接口鉴权 | `Code/backend/app/api/deps.py` require_write_access 挂在全部写路由（config_routes.py 等 30+ 处）；GET 读接口免鉴权（掩码返回） | `Code/frontend/src/services/_http.ts` / `settings-api.ts` 经 withWriteAuthHeaders 对非 GET 自动附 X-Api-Key | ⚠️ | 运行时一致；契约未表达鉴权（见 D-2），且 /config/api-keys GET 免鉴权属既定设计 |

## 5. 结论

**契约健康度 ⚠️（整体一致，无 P0/P1 破坏）**

- 关键链路（/layers、/weather/tiles、/workflow-runs、/config 写鉴权）后端定义与前端调用在运行时完全一致，OpenAPI drift 检查通过，20 个核心模型字段级比对无漂移（仅 Task* 孤儿模型缺失属死代码）。
- 主要问题集中在 P2 合规面：3 处 Celery 元数据非 ASCII title、9 个 hPa 字段非严格 snake_case、6 个时间戳字段以 str 声明未强制 ISO 8601、OpenAPI 未文档化 X-API-Key 鉴权语义。
- 建议修复优先级：N-1/N-2（US-ASCII 约定，改动小）→ D-1（清理死契约）→ N-4（datetime 类型化）→ D-2（security 文档化）→ N-3（hPa 命名白名单）。
- 均为非阻断项，可随 Phase 5 一并处理。
