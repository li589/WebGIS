# 2026-08-12 P2 快速项收口

## 范围

处理 P2 backlog 中的中低风险快速项：R2 / D-1 / D-2 / N-3 / N-4 / L2。

## 完成清单

### R2 — 断路器 threshold 调参 ✅ 已修复（确认）

- **状态**：代码在之前的 Phase 5/6 审查中已修复，本次确认并更新文档
- **文件**：`Code/backend/app/core/redis_client.py`（threshold 1→3 + 指数退避 30→60→120s）
- **验证**：`test_redis_circuit_breaker.py` 全部通过

### D-1 — Task* 死契约 ✅ 已清除（确认）

- **状态**：旧 Task* 模型（TaskSubmit / TaskStatus 等）已从 `api_contracts.py` 完全清除
- **openapi.json**：无 `/tasks` 路径，无死 Task* schema
- **残留**：`TaskLimit` / `TaskType` / `ExportTaskStatusResponse` 均为 GEE 引擎活跃模型，非死契约
- **遗留命名**：`default_task_type` / `task_type` 字段仍沿用旧名但活跃读写，不影响功能

### D-2 — OpenAPI security schemes ✅ 已完成

- **问题**：OpenAPI 仅声明 `APIKeyHeader`，缺少 Session Cookie 和 Bearer Token
- **改动**：`Code/backend/app/main.py` 添加自定义 `app.openapi()` 函数
- **新增 schemes**：
  - `SessionAuth`：apiKey / cookie / `cgda_session`
  - `BearerAuth`：http / bearer（用户个人 API Token）
- **验证**：`check:openapi` 通过；`openapi.json` 含 3 个 securitySchemes

### N-3 — hPa 字段单位语义 ✅ 已完成

- **问题**：`WeatherPointCurrent` 9 个 hPa 气压层字段无单位说明
- **改动**：`Code/shared/contracts/api_contracts.py` 为每个字段添加 `Field(description=...)`
  - `wind_speed_*hPa` → "风速 (m/s)"
  - `wind_direction_*hPa` → "风向 (°)"
  - `temperature_*hPa` → "温度 (°C)"
- **验证**：`openapi.json` 含字段 description；ruff / mypy 无新增错误

### N-4 — 时间戳类型化 ✅ 已完成

- **问题**：sync status 端点返回 ad-hoc dict，`finished_at` 为 ISO 字符串
- **改动**：
  1. `api_contracts.py`：新增 `OpenMeteoSyncStatusResponse` 模型（`finished_at: datetime | None`）
  2. `weather_router.py`：添加 `response_model=OpenMeteoSyncStatusResponse`
  3. `workflow_router.py`：`str(start_at).replace("-", "")[:8]` → `start_at.strftime("%Y%m%d")`
- **验证**：`openapi.json` 中 `finished_at` 为 `string` + `format: date-time`

### L2 — Ghost uvicorn 修复 ✅ 已完成

- **问题**：`cmd_stop()` 杀父进程后 uvicorn 子进程成为孤儿仍监听 :8000
- **根因**：`terminate_by_cmdline_patterns` pattern 列表 `["start_fastapi.py"]` 无法匹配子进程命令行（含 `spawn_main` / `uvicorn`）
- **改动**：`launch/commands.py` `cmd_stop()` pattern 列表补充 `"spawn_main"` + `"uvicorn"`
- **验证**：ruff 通过

## 验证结果

| 检查项 | 结果 |
|--------|------|
| ruff（修改文件） | ✅ All checks passed |
| mypy（api_contracts.py） | ✅ 0 new errors（2 pre-existing on L417/L654） |
| pytest（weather/circuit/config） | ✅ 89 passed |
| pytest（auth） | ✅ 9 passed |
| vitest（前端全量） | ✅ 632 passed (121 files) |
| check:openapi | ✅ OK |
| check:catalog | ✅ FE=37 BE=41 |
| gen:types | ✅ TypeScript 类型重新生成 |
| OpenAPI schema | ✅ 3 securitySchemes + OpenMeteoSyncStatusResponse + hPa descriptions |
| lint（前端） | ⚠️ 1 pre-existing error (IconButton.vue return-in-computed-property) |
| build（前端） | ⚠️ 1 pre-existing error (basemap-module.ts overlayUrlTemplate) |

## 修改文件清单

| 文件 | 改动类型 |
|------|---------|
| `launch/commands.py` | L2: pattern 列表补充 |
| `Code/shared/contracts/api_contracts.py` | N-3: hPa Field descriptions; N-4: 新增 OpenMeteoSyncStatusResponse |
| `Code/backend/app/main.py` | D-2: 自定义 openapi() + security schemes |
| `Code/backend/app/api/routers/weather_router.py` | N-4: response_model 接线 |
| `Code/backend/app/api/routers/workflow_router.py` | N-4: str() → strftime() |
| `Code/frontend/openapi.json` | 自动重导（D-2 + N-3 + N-4） |
| `Code/frontend/src/types/api-contracts.ts` | 自动重生成 |
| `.ai/docs/reference/工程收口仪表盘.md` | 文档更新 |
| `.ai/progress/2026-08-04-pending-tasks-audit.md` | 文档更新 |

## 预存问题（非本次引起）

1. **IconButton.vue lint error**：`vue/return-in-computed-property`（L40），预存
2. **basemap-module.ts build error**：`TileSourceConfig.overlayUrlTemplate` 属性不存在（L56/L230），`api-config.ts` 接口未定义此属性，预存
3. **api_contracts.py mypy warnings**：L417 `default_factory` ResultKind、L654 `default_factory` WeatherPointCurrent，预存
