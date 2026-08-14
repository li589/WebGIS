# Settings → gen:types 迁移（2026-08）

## 范围

- 完成 `/config/*` 与 `GET /runtime/config` 剩余端点的 Pydantic response/request 模型化
- 前端 `settings-api.ts` 全面改用 `api-reexports.ts` / OpenAPI 生成类型
- 修复 `WeatherProviderSettings.vue` 构建 TS 错误
- **未做**：god-store 续拆（`layers/index.ts`、`weather-tile-manager.ts` 等）

## 后端

- `config_contracts.py`：新增 delete/toggle/evict/open-data/portal/remote-layer-uris 等请求/响应模型
- `api_contracts.py`：`RuntimeConfigSnapshotResponse`（`extra=allow`）
- `config_routes.py`：上述端点全部挂 `response_model`；`evict`/`open-data-presets`/`portal`/`remote-layer-uris` 替换 `dict[str, Any]`
- `runtime_router.py`：`GET /runtime/config` → `RuntimeConfigSnapshotResponse`

## 前端

- `export_openapi.py` → `openapi.json`（178 schemas）
- `npm run gen:types` + `check:openapi` 通过
- `api-reexports.ts`：补充全部新 config/runtime schema 导出
- `settings-api.ts`：删除内联 DTO，函数返回类型全部来自 gen:types
- `WeatherProviderSettings.vue`：`formatPercent` / `daily_used` 空值守卫
- `GeneralSettings.vue` / `DataSourceSettings.vue`：适配 `RuntimeConfigSnapshotResponse` / `PortalCredentialUpsertRequest`

## 验证

- `pytest Test/backend/test_config_security.py Test/backend/test_openapi_fingerprint.py` — 10 passed
- `npm run build` — OK

## 全栈重启

执行 `launch.py stop` → `launch.py start`（见当次会话终端输出）。
