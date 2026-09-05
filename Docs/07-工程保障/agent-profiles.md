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

## 能力（切片 A–D + P0–P3）

- 短会话记忆（每用户/session 最近约 12 轮）；**多会话**：`GET/DELETE /agent/sessions*` + 前端历史下拉切换 / 删除；Markdown 导出当前对话
- 每次 chat 注入活动图层 + 地图选点 `map_point` + **timeline / viewport / basemap_id** + 可访问目录摘要 + 工具清单
- 客户端 UI intents：
  - 显隐 / 透明度 / 缩放到图层 / 活动图层列表
  - 视口：`fit_china` / `locate_coordinate` / `switch_basemap`（及 FE 别名）
  - 时间轴：`set_timeline` / `set_timeline_playing`
  - 图层栈 / 样式：`remove_layer` / `reorder_layer` / `set_layer_symbology`
- 只读工具（ACL 过滤，立即执行）：
  - `search_layers` / `list_workflows` / `get_layer_meta` / `get_workflow_meta`
  - `sample_layer_point`（`lng`/`lat` 或 `client_context.map_point`）
  - `web_search`（DuckDuckGo Instant Answer + Wikipedia；`BACKEND_AGENT_WEB_SEARCH_ENABLED`，默认开）
  - `list_workflow_runs` / `get_workflow_run` / `get_layer_coverage`
  - `list_workflow_timers`（**仅 admin**）
- `run_workflow` 创建确认票据（可选 `time_range`、`workflow_variant=online`）；对话内确认卡批准后才提交 `workflow-runs`
- 有界多跳工具循环（`BACKEND_AGENT_MAX_TOOL_HOPS`，默认 4）
- **SSE 流式**：`POST /agent/chat/stream`；前端可 **停止生成**（AbortController）；失败自动回退 `/agent/chat`
- 响应 `steps` / `usage`；可选 `confirmations`；`search_layers` / 活动图层结果可渲染 **可点图层卡**（打开 / 定位）
- 前端伴侣面板展示当前地图选点，并随 `client_context.map_point` 发送

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/agent/config` | profiles（含 `scope`）+ presets + `can_manage_*` |
| POST | `/agent/config/profiles` | `{ preset_id, scope }` |
| PUT/DELETE | `/agent/config/profiles/{id}` | 需对应 scope 写权限 |
| POST | `/agent/config/active` | `{ profile_id, scope }` |
| POST | `/agent/config/use-global` | 清除个人启用，回退全局 |
| POST | `/agent/models/refresh` | 拉模型列表 |
| GET | `/agent/sessions` | 当前用户会话摘要列表 |
| GET | `/agent/sessions/{id}` | 会话消息（属主隔离） |
| DELETE | `/agent/sessions/{id}` | 删除会话文件 |
| POST | `/agent/chat` | LLM/演示 + `ui_intents` + `steps` + `usage` + 可选 `confirmations` |
| POST | `/agent/chat/stream` | SSE 流式（同请求体）；事件 `token`/`step`/`intent`/`done`/`error` |
| POST | `/agent/confirm` | 批准/拒绝危险操作票据（`run_workflow`）；写权限 required |

生产环境对 chat 按 IP 限流（`BACKEND_AGENT_CHAT_RATE_LIMIT_PER_MINUTE`，默认 30）。
`POST /agent/models/refresh` 另有独立限流（`BACKEND_AGENT_MODELS_REFRESH_RATE_LIMIT_PER_MINUTE`，默认 20）；**仅 admin** 可刷新 `scope=global` 的配置档。

会话文件带 TTL（`BACKEND_AGENT_SESSION_TTL_HOURS`，默认 24）与每用户数量上限（`BACKEND_AGENT_MAX_SESSIONS_PER_USER`，默认 40）。

确认票据 TTL：`BACKEND_AGENT_CONFIRM_TTL_SECONDS`（默认 600）。`run_workflow` 仅创建票据，**批准后**才提交 `workflow-runs`；`demo` 角色无法确认写操作。

多跳上限：`BACKEND_AGENT_MAX_TOOL_HOPS`（默认 4，钳制 1～8）；每跳记入 `steps`（`thought` / `tool` / `tool_result`）。

Gateway：`/agent/chat/stream` 单独 `location ^~`（`proxy_buffering off`，读超时 600s，`X-Accel-Buffering: no`）。

## 后续升级

P0–P3（地图意图同步、时间轴/图层栈、跑态与覆盖工具、停流/卡片/多会话）已落地。明确未做：向量 RAG、Agent 写定时器、取消/重试 run 确认卡、微信端。

历史方案见 AI 工作区：

[`.ai/plans/2026-08-29-agent-capability-upgrade.md`](../../.ai/plans/2026-08-29-agent-capability-upgrade.md)

（该文件位于本地 `.ai/`，默认不随公开仓同步；审查对照见 [代码审查 — Agent 子系统](../06-代码审查/code-review-2026-08-29-agent-subsystem.md)。）
