# 审查修复执行记录（B1 + B2 核心，2026-08-08）

基于 [code-review-fullstack-2026-08.md](./code-review-fullstack-2026-08.md)。

## 已落地

| ID | 改动摘要 |
|----|----------|
| P0-1 | `require_write_access`：dev 旁路仅 loopback，或 `BACKEND_DEV_AUTH_BYPASS`；补矩阵测 |
| P0-2 | `assert_encryption_policy` / `validate_encryption_key_format`：64 hex fail-fast |
| P0-3 | 文档标明共享 key blast radius（README / AGENTS / conventions） |
| P0-4 | `service_restart`：始终 `restart backend`，响应 components 诚实为全量组 |
| P0-5 | `refuse_empty_iv_outside_development` 接入各 secrets repository |
| P1-1 | workflow events IP → `rate_limit.client_ip`（尊重 trust_proxy） |
| P1-2 | 写限流前缀含 `/workflow-runs` |
| P1-3 | 天气瓦片 GET 宽松 per-IP 限流（默认 240/min） |
| P1-5 | download orchestrator 不再静默填 `demo://snapshots/...`（missing + 空 URI） |
| P1-6 | GEE API account management：production 默认 false |
| P1-9 | `npm run check:openapi/catalog` 经 `scripts/run-repo-python.mjs` 用 Env/Python312 |
| P2-1 | layers / weather-tile / workflow-runner `debugLog` 门控（`?debug=1` / `cgda.debug` / perf） |
| build | 补 `LayerContextActionId` 含 `runWorkflowNoCache`（修 vue-tsc） |

## 验证

- `pytest`：`test_config_security` / `test_secrets_encryption` / `test_data_source_paths` / `test_rate_limit_coverage` / `test_data_root_policy` → **29 passed**
- FE：`vitest` weather-tile + workspace-persist + perf-probe → **48 passed**；`npm run build` → **OK**
- Lint：既有 warnings，无新增 error

## 未纳入本轮（仍见审查报告 B2/B3）

- P1-4 敏感 config GET 收紧
- P1-7/8 OpenAPI schema 深度 drift / settings 迁 gen:types
- P1-10 localStorage 写 Key 存储策略
- P2-2 god-store 续拆、P2-3 Demo 契约清理等

## 文档同步

- `README.md`「发布边界」
- `AGENTS.md` / `.ai/rules/project-conventions.md` 高风险区
- 本文件 + 审查报告执行状态
