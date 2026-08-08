# CLAUDE.md

> CGDA（综合地理数据分析系统）给 Claude Code / 通用 AI 工具的入口说明。
> 完整架构、目录路由与「改 X 则跑 Y」映射见 **`AGENTS.md`**；项目说明与本地环境见 **`README.md`**。
> 所有 AI 提示 / 技能 / 计划 / 进度 / 记忆 / 文档集中在仓库根 **`.ai/`**（本地专用，不上传 GitHub）。

## 硬约定速览（详情见 `.ai/rules/project-conventions.md`）

- **运行时**：后端 / 算法 / pytest / launch **唯一解释器 = `Env/Python312/python.exe`**（Windows）。绝不用系统 PATH 的 `python`。
- **前端**：Node 22（`Code/frontend/package.json` engines）。
- **Windows Docker**：`launch.py start` / `sync` 需 Docker Desktop 与终端都以**管理员身份**运行。

## 常用命令

- 全栈启动：`Env\Python312\python.exe launch.py start`
- 单组件：`… launch.py start <docker|fastapi|beat|worker|worker:<name>|frontend|gateway|backend>`
- 仅重启后端进程组（改数据根后）：`… launch.py restart backend`
- 状态/日志：`… launch.py status` / `logs [component] [-n N]`
- 数据同步：`… launch.py sync [job]`
- 清缓存（仅排障）：`… launch.py flush`（高风险，清 Redis + 天气缓存）
- 后端单测：`cd Code/backend && pytest tests/<对应用例> -q`（需 `REDIS_URL` + `ENVIRONMENT=test`）
- 前端：`cd Code/frontend && npm run test && npm run lint && npm run build`
- 契约：`cd Code/frontend && npm run check:openapi`
- 提交前：`pre-commit run --all-files`

## 高风险区（改动前确认鉴权 / 加密 / 隔离）

1. `/config/*` 写操作与敏感读需会话 Cookie、用户 API Token 或 `backend_auth` 服务密钥（`X-API-Key`）；RBAC：`viewer` 只读。dev 旁路仅 loopback，或 `BACKEND_DEV_AUTH_BYPASS`。
2. `/auth/*` 用户登录、RBAC 账户与个人 API Token；角色/密码变更吊销会话。
3. 共享加密主密钥 `BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY`（64 hex / 32-byte，启动校验）加密 GEE/API keys/天气/远程/门户；非 development 必配。
4. `launch.py flush` 清空 Redis + 天气缓存，仅排障用。
5. Open-Meteo 走 Docker named volume，勿用 Windows bind mount。
6. `BACKEND_DATA_ROOT` 必配（production 空根拒启）；前端设置 → 数据源可改，须重启 FastAPI+Worker+Beat 生效。
7. **错误响应**：4xx/422/500 JSON 含 `request_id`；与前端 LogPanel 导出、`launch.py logs` 串联排障。

## 协议 / 命名

- HTTP JSON 字段 `snake_case`；时间 ISO 8601；空间 `bbox + crs`；枚举小写英文。
- **Celery 元数据仅 US-ASCII**：`WorkflowResultReference.title` / `create_artifact_result_ref(title=...)` 必须纯英文。
- 共享协议：`Code/shared/contracts`（Pydantic 单一事实来源）与前端 `src/types/api-contracts.ts`（OpenAPI 自动生成，**勿手改**）。
- 后端主链 `workflow-runs`；旧 `/tasks` 仅桥接。

## AI 知识库（`.ai/`）

- `.ai/rules/` —— 约定单一真源（project-conventions / qingtian-decision-policy / git-commit-message）
- `.ai/skills/` —— 可复用技能（workflow-design / omega-sf-inversion / multi-source-data-ingestion / runtime-and-verify / contract-openapi-drift）
- `.ai/plans/` —— 计划
- `.ai/progress/` —— 进度/验证追踪（FY-SMAP 系列、UI 验证步骤）
- `.ai/memory/` —— AI 记忆 / 历史上下文（archive/）
- `.ai/docs/` —— 项目文档（design / specs / reference；含 `specs/workflow_seed_conventions.md`）

> 本仓库根仅保留 `AGENTS.md`、`CLAUDE.md`、`README.md` 三份文档；其余 AI 上下文均在 `.ai/`。
