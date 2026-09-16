# 图层平台子系统 P0 升级实施计划

## 范围（已确认）

- **平台底座 P0**：workflow_kind 显式化、layer-assets 查询、lifecycle 聚合、前端 lifecycle 域、时间轴状态接入。
- **完全兼容存量**：不改 imported-* overlay id、不破坏既有 /workflow-runs 与 /overlay-asset-workflows 接口；新能力只以新增列/新增接口叠加。
- **凭证管理不纳入**：GEE 账号池与门户凭证维持现有配置服务，仅预留接口。

## 步骤 1：workflow_runs schema v5（后端底座）

**文件**：
- `Code/backend/app/services/workflow_repository.py`
- `Code/backend/app/services/overlay_asset_workflow_service.py`

改动：
1. SCHEMA_VERSION 4→5；SCHEMA_CHANGES 追加变更记录。
2. `_migrate_schema` additive ALTER 加三列（全部允许 NULL，兼容旧行）：
   - `workflow_kind TEXT`
   - `layer_id TEXT`
   - `progress INTEGER`
   - 索引：`idx_workflow_runs_kind_layer(workflow_kind, layer_id)`
3. `save_run` / `save_run_under_capacity` / `save_run_cas` 共 4 处 SQL 支持新列；**自动提取优先**：可选参数缺省时从 `run_status.layer_id`、`executor_metadata.workflow_kind`、`run_status.progress` 提取，调用面零改动即获得列填充。
4. 新增 `list_runs_by_layer(layer_id, limit)` 走索引查询，替代 asset 服务里 `list_runs()` 全表内存过滤。
5. `overlay_asset_workflow_service.py` 的 6 处 `save_run` 显式传新列。

验证：
- `Test/backend/test_workflow_repository.py` 增加 v4→v5 迁移测试（旧库缺列→实例化→断言列/索引/版本号）、roundtrip、按层查询。
- `REDIS_URL=redis://localhost:6379/0 ENVIRONMENT=test pytest Test/backend/test_workflow_repository.py`

风险：
- 4 处 SQL 遗漏任一处该路径列恒 NULL——用自动提取兜底。
- SQLite ALTER 禁止加无默认值 NOT NULL 列——全允许 NULL 规避。

## 步骤 2：layer-assets 与 lifecycle 接口

**文件**：
- `Code/backend/app/services/overlay_asset_workflow_service.py`（暴露公有 `get_asset_state()`）
- `Code/backend/app/api/routers/layer_router.py`
- `Code/shared/contracts/api_contracts.py`

改动：
1. 新增契约 `LayerAssetStateResponse` / `LayerLifecycleResponse`。
2. `GET /layer-assets/{layer_id}`：`check_resource_access` → 未知层 404 → 返回 asset_state / bake_version / current_bake_version / time_list。
3. `GET /layers/{layer_id}/lifecycle`：聚合 asset_state + `list_runs_by_layer` 最近 run（status/progress/updated_at）+ timeline 元数据。
4. 契约链：`export_openapi.py` 重导 openapi.json → `npm run gen:types` → `check:openapi` 门禁。

验证：
- Test/backend 新增接口回归（ACL / 404 / 聚合结构）。

风险：
- 契约链漏一步 CI 红——按顺序执行并本地跑 check:openapi。
- lifecycle 404 与 ACL fail-closed 语义对齐 `_filter_accessible_layer_ids` 现有行为。

## 步骤 3：前端 lifecycle 域（第四域）

**文件**：
- 新增 `Code/frontend/src/stores/layers/lifecycle-domain.ts`
- 修改 `bindings.ts`、`index.ts`、`selectors.ts`、`types.ts`
- 修改 `Code/frontend/src/services/runtime-api.ts`（lifecycle 查询函数）
- 修改 `Code/frontend/src/components/TimelineScrubber.vue`

改动：
1. `createLifecycleDomain(bindings, workspace, workflowRun)`：聚合 jobLayers + overlayTimeStates（经 bindings 注入）+ dataState，派生 `fresh/stale/updating/missing`。
2. `refreshLayerLifecycle(instanceId)` 调 `/layers/{id}/lifecycle`。
3. bindings 增 stub；index.ts 在 workflow-run 域之后组装回填；selectors 增 `useLayerLifecycle()`（toRef 模式，禁 storeToRefs）。
4. TimelineScrubber 时间块渲染 lifecycle 状态（复用 fetchable 段 CSS 模式）；**双写过渡**：overlayTimeStates 保持 fallback，不动 dataState 三值。

验证：
- `Test/frontend/stores/layers/lifecycle-domain.test.ts`
- `cd Code/frontend && npm run test`（全量绿）

风险：
- 域组装顺序错误致 no-op stub 静默失败——在 index.ts 组装处加断言/日志。
- TimelineScrubber 保留旧渲染路径，lifecycle 状态仅叠加不替换。

## 步骤 4：全量回归

- 后端全量 pytest（带 REDIS_URL + ENVIRONMENT=test + BACKEND_OUTPUT_ROOT）
- 前端 vitest 全量 + type-check + build
- `check:openapi`
- 确认 imported-* id 不变、get_run/list_runs 反序列化不受新列影响

## 提交切分（3 commits）

1. `feat(backend): workflow_runs schema v5 加 workflow_kind/layer_id/progress 列`
2. `feat(backend): 图层资产状态与 lifecycle 聚合查询接口`（含契约 + openapi 重导）
3. `feat(frontend): layers store 新增 lifecycle 域并接入时间轴状态`

## 环境约定

- 提交前缀：`CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= env -u ACC_PRODUCT_CONFIG_V3 git ...`
- 沙箱禁 git stash / 切分支 / merge。
- 后端重启：`Env/Python312/python.exe launch.py restart backend`。
- MATLAB 目录 `Code/algorithms/providers/Matlab/Original-Time_series_soil_moisture_estimation-DuXin/` 保持不动。
