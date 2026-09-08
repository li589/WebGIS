# 2026-08-29 Agent 预设外置 + 个人/全局隔离 + 能力切片 A

## 完成

- `Code/agentKits/presets/provider_catalog.json` 为 Provider URL 真源（mtime 热加载）
- 全局档 admin 专属；个人档 per-user；chat 优先个人 active
- 会话记忆、`search_layers` 只读执行、catalog/工具注入、`steps` CoT UI
- 验证：`test_agent_chat.py`、前端 `agent-api`、OpenAPI、build

## 不做（后续）

- `run_workflow` / 多跳无限 tool loop / 流式思维链
