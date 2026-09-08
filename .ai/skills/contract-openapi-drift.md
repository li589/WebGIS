# 技能：前后端契约与 OpenAPI 漂移防护

> 场景：改动 API 请求/响应结构、Pydantic 模型、或前端类型，需保证前后端契约一致、CI 的 OpenAPI 检查不挂。
> 适用工具：后端（FastAPI） / 前端（Vue/TS） / 共享协议。

## 1. 契约事实来源（单一真源层级）

| 层级 | 路径 | 说明 |
|------|------|------|
| 共享契约（Python） | `Code/shared/contracts/api_contracts.py`、`config_contracts.py` | Pydantic 模型为协议单一事实来源（见 `Code/shared/contracts/README.md`） |
| OpenAPI 产物 | `Code/frontend/openapi.json` | 后端导出的 OpenAPI 文档 |
| 前端类型（自动生成） | `Code/frontend/src/types/api-contracts.ts` | **由 OpenAPI 自动生成，勿手改** |
| 契约检查入口 | `Code/frontend/package.json` → `npm run check:openapi` | CI 质量门之一 |

契约原则（已核对 README）：字段优先 `snake_case`；围绕统一图层/时间范围/空间范围/任务状态对象协作；先用 Pydantic 作事实来源，后续可导出 JSON Schema/TS 类型。

## 2. 正确工作流（改 API 后）

1. 在 `Code/shared/contracts/api_contracts.py`（或对应后端 router 的 Pydantic 模型）改契约。
2. 重新导出 OpenAPI：`cd Code/frontend && npm run <生成 openapi 的脚本>`（确保 `openapi.json` 更新；具体脚本名以 `package.json` 的 `scripts` 为准）。
3. 重新生成前端类型：`api-contracts.ts` 由工具从 `openapi.json` 生成，**切勿手工编辑**。
4. 跑契约检查：`cd Code/frontend && npm run check:openapi`（对比生成类型与 openapi.json，漂移即报错）。
5. CI 中该步骤位于 pre-commit(全量) → pytest → vitest → check:openapi 之后。

## 3. 漂移典型症状与排查

- 前端报「字段不存在 / 类型不匹配」→ 多半 `api-contracts.ts` 未重新生成或 `openapi.json` 过期。
- `check:openapi` 失败 → 后端改了模型但没重导 OpenAPI，或前端手改了生成文件（回退手改即可）。
- 后端新增响应字段前端收不到 → 检查是否漏改 `shared/contracts`，或前端仍用旧硬编码字段（README 强调前端不应硬编码后端字段）。

## 4. 注意

- 不要为了过检查而手改 `api-contracts.ts` —— 治标不治本，且下次生成会覆盖。
- 协议扩展优先在 `Code/shared/contracts/` 补充正式契约，再同步前后端（README 推荐顺序）。
- 相关验证命令见 `runtime-and-verify` 技能的「改 X 则跑 Y」。
