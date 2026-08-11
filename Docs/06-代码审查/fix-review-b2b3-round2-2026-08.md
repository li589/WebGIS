# 审查修复执行记录（B2/B3 第二轮，2026-08-08）

承接 [fix-review-b1-b2-2026-08.md](./fix-review-b1-b2-2026-08.md)。

## 已落地

| ID | 改动摘要 |
|----|----------|
| P1-4 | 敏感 `GET /config/*` 挂 `require_config_read_access`；`/general` `/about` 仍公开；FE `settingsFetch` 对 GET 附带 X-Api-Key |
| P1-7 | `check_openapi_drift` 加深：operationId / params / body·response $ref / security 指纹 |
| P1-10 | 写 Key 默认 sessionStorage；UI 勾选才持久化 localStorage；旧 local 键兼容标 persist |
| P2-3 | 删除未使用 `Demo*` Pydantic 模型；重导 openapi + gen:types（159 paths / 136 schemas） |
| P2-4 | `persistence_service.get_effective_config_int` 吞异常改为 warning 日志 |
| P2-6 | FE 单测 `backend-auth-settings-local.test.ts`（6） |

## 验证

- pytest：`test_config_security`（含敏感 GET）+ `test_openapi_fingerprint` + secrets → **19 passed**（本轮子集）
- `npm run check:openapi` → OK（含 fingerprint）
- vitest：`backend-auth-settings-local` → **6 passed**；`npm run build` → **OK**
- `launch.py restart backend` → FastAPI HTTP 就绪

## 仍未纳入（后续）

- P1-8 settings-api 手写 DTO 全面迁 gen:types / api-reexports
- P2-2 god-store 续拆（layers / weather-tile / WorkflowCanvas）
- Settings 组件级集成测（ApiKeySettings 勾选持久化）
