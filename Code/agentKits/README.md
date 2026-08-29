# Agent Kits

CGDA AI 助手的**共享契约层**（工具 schema、提示词、Provider 预设）。不含运行时编排。

| 目录 | 职责 |
|------|------|
| `presets/` | Provider 目录 JSON（`provider_catalog.json`，后端 mtime 热加载） |
| `tools/` | 工具 / UI intent JSON Schema |
| `prompts/` | 系统提示词 |

## 两类能力

1. **服务端 tools**（`server_tools.json`）：由后端执行。当前允许 **`search_layers`**（只读、经 ACL 过滤）；`run_workflow` 仍拒绝（见升级方案 Phase B）。
2. **UI intents**（`ui_intents.json`）：后端建议、**前端执行**（显隐、透明度、缩放到图层）。地图状态只存在于客户端；前端应对 `catalog_id` 做可添加性校验。

运行时：`Code/backend/app/services/agent/` + `POST /agent/chat` + `/agent/config*`（全局 admin / 个人档）；
主前端设置 → **Agent 配置**；挂件 UI 在 `Code/frontend/src/components/agent/`。
说明见 `Docs/07-工程保障/agent-profiles.md`；升级路线见 `.ai/plans/2026-08-29-agent-capability-upgrade.md`。

## 原则

- 字段 `snake_case`
- 危险写操作（跑工作流）须确认卡（Phase B）
- 密钥不进本目录
- prompts / tools JSON 由运行时按 mtime 缓存，改文件即热更新
