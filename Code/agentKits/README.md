# Agent Kits

CGDA AI 助手的**共享契约层**（工具 schema、提示词）。不含运行时编排。

| 目录 | 职责 |
|------|------|
| `tools/` | 工具 / UI intent JSON Schema |
| `prompts/` | 系统提示词 |

## 两类能力

1. **服务端 tools**（`server_tools.json`）：由后端执行（检索图层、提交工作流等）。首版仅 schema 占位。
2. **UI intents**（`ui_intents.json`）：后端建议、**前端执行**（显隐、透明度、缩放到图层）。地图状态只存在于客户端。

运行时：`Code/backend/app/services/agent/` + `POST /agent/chat` + `/agent/config*`（全局 admin / 个人档）；
预设目录 JSON：`Code/agentKits/presets/provider_catalog.json`；
主前端设置 → **Agent 配置**；挂件 UI 在 `Code/frontend/src/components/agent/`。
说明见 `Docs/07-工程保障/agent-profiles.md`。

## 原则

- 字段 `snake_case`
- 危险写操作（跑工作流）须确认卡（后续迭代）
- 密钥不进本目录
