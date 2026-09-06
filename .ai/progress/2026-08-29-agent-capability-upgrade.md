# 2026-08-29 Agent 底层功能配置与接入升级

## 状态

**方案已落盘；Phase 0 / B / C / D done。**

## 文档

| 文件 | 说明 |
|------|------|
| [`.ai/plans/2026-08-29-agent-capability-upgrade.md`](../plans/2026-08-29-agent-capability-upgrade.md) | 完整升级方案 + Phase 0～D 任务拆分 |
| [`Docs/07-工程保障/agent-profiles.md`](../../Docs/07-工程保障/agent-profiles.md) | 现状 + 确认 API + 多跳 + SSE |

## 阶段进度

| Phase | 内容 | 状态 |
|-------|------|------|
| M0 方案 | 文档落盘 | **done** |
| P0 | 配置与接入加固 | **done** |
| B | `run_workflow` + 确认卡 | **done** |
| C | 有界多跳 + 只读工具扩展 | **done** |
| D | SSE 流式 | **done** |

## Phase D 交付

- `POST /agent/chat/stream`：`token` / `step` / `intent` / `done` / `error`
- Gateway：`location ^~ /agent/chat/stream`（`proxy_buffering off`，长读超时）
- FE：`streamAgentChat` + `AgentChatPanel` 流式气泡；失败回退 `/agent/chat`
- demo 伪流式分片；OpenAPI 已同步
- 测试：SSE demo + error 事件

## 下一步

升级主链收口；后续按需：真 token 流（上游流式协议）、双向 WS（非目标）。
