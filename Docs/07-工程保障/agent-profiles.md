# Agent 多配置档与对话

设置 → **Agent 配置**：多套命名 Profile（演示 / Ollama / 国内外站 / 自定义）。

## 预设真源

Provider 默认 URL / 模型目录保存在 [`Code/agentKits/presets/provider_catalog.json`](../../Code/agentKits/presets/provider_catalog.json)，后端按 mtime 热加载；改 JSON 无需改 Python 常量。

## 权限与隔离

| 范围 | 存储 | 谁可写 |
|------|------|--------|
| 全局 | `{DATA_ROOT}/_runtime/agent/global_profiles.json` | 仅 **admin** |
| 个人 | `{DATA_ROOT}/_runtime/agent/users/{user_id}/profiles.json` | 本人且 `standard`/`admin` |

对话解析顺序：若当前用户有个人 `active_profile_id` → 用个人档；否则回退全局启用档。`demo` 角色只读。API Key 加密存储，响应永不回传明文。

## 能力（切片 A + Phase B + Phase C）

- 短会话记忆（每用户/session 最近约 12 轮）
- 每次 chat 注入活动图层 + 可访问目录摘要 + 工具清单
- 只读工具：`search_layers` / `list_workflows` / `get_layer_meta`（ACL 过滤，立即执行）
- `run_workflow` 创建确认票据；对话内确认卡批准后才提交 `workflow-runs`
- 有界多跳工具循环（`BACKEND_AGENT_MAX_TOOL_HOPS`，默认 4）
- 响应 `steps` / `usage`；可选 `confirmations` 供前端确认卡

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/agent/config` | profiles（含 `scope`）+ presets + `can_manage_*` |
| POST | `/agent/config/profiles` | `{ preset_id, scope }` |
| PUT/DELETE | `/agent/config/profiles/{id}` | 需对应 scope 写权限 |
| POST | `/agent/config/active` | `{ profile_id, scope }` |
| POST | `/agent/config/use-global` | 清除个人启用，回退全局 |
| POST | `/agent/models/refresh` | 拉模型列表 |
| POST | `/agent/chat` | LLM/演示 + `ui_intents` + `steps` + `usage` + 可选 `confirmations` |
| POST | `/agent/confirm` | 批准/拒绝危险操作票据（`run_workflow`）；写权限 required |

生产环境对 chat 按 IP 限流（`BACKEND_AGENT_CHAT_RATE_LIMIT_PER_MINUTE`，默认 30）。
`POST /agent/models/refresh` 另有独立限流（`BACKEND_AGENT_MODELS_REFRESH_RATE_LIMIT_PER_MINUTE`，默认 20）；**仅 admin** 可刷新 `scope=global` 的配置档。

会话文件带 TTL（`BACKEND_AGENT_SESSION_TTL_HOURS`，默认 24）与每用户数量上限（`BACKEND_AGENT_MAX_SESSIONS_PER_USER`，默认 40）。

确认票据 TTL：`BACKEND_AGENT_CONFIRM_TTL_SECONDS`（默认 600）。`run_workflow` 仅创建票据，**批准后**才提交 `workflow-runs`；`demo` 角色无法确认写操作。

多跳上限：`BACKEND_AGENT_MAX_TOOL_HOPS`（默认 4，钳制 1～8）；每跳记入 `steps`（`thought` / `tool` / `tool_result`）。

## 后续升级

切片 A / P0 / B / C 之后的 **SSE 流式（Phase D）** 任务拆分见 AI 工作区计划：

[`.ai/plans/2026-08-29-agent-capability-upgrade.md`](../../.ai/plans/2026-08-29-agent-capability-upgrade.md)

（该文件位于本地 `.ai/`，默认不随公开仓同步；审查对照见 [代码审查 — Agent 子系统](../06-代码审查/code-review-2026-08-29-agent-subsystem.md)。）
