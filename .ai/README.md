# .ai/ —— CGDA AI 工作区（随仓库提交）

本目录集中存放所有 AI 编程上下文：**规则 / 技能 / 计划 / 进度 / 记忆 / 文档**。
仓库根表面只保留 `AGENTS.md`、`CLAUDE.md`、`README.md` 三份文档；本目录随仓库提交（2026-09-06 起），供各 AI 工具与团队成员共享——例外：`.ai/mcp.json`（本地 MCP 密钥）、`.ai/tmp/`（临时区）与 `.ai/progress/archive/tmp-*`/`trae-tmp-*`（含明文凭据的临时探针归档，如 NAS profile、门户口令）仍在 `.gitignore`。**政策：明文凭据只存本地（gitignored 文件，如 `Tools/_nas_credentials.json`、上述探针归档）；任何入库文档/脚本中出现口令值时必须脱敏为 `********`。**

> **约定单一真源在本目录**：2026-09-10 起，Cursor / Trae / Copilot / Kiro / WorkBuddy 等工具的指针文件与目录（`.cursor/`、`.kiro/`、`.trae/`、`.cursorignore`、`.github/copilot-instructions.md`）已从版本库移除，**不再保留指针副本**。读约定直接看本目录 `rules/`，改约定只改本目录；上述路径仍在 `.gitignore`，工具若自行生成也不会误入库。

## 目录导航

| 子目录 | 内容 |
|--------|------|
| `rules/` | **约定单一真源**：`project-conventions.md`（运行时/launch/改X则跑Y/高风险区/命名/提交）、`qingtian-decision-policy.md`（QingTian 决策策略）、`git-commit-message.md`（Conventional Commits） |
| `skills/` | 可复用 AI 技能文档：`omega-sf-inversion`、`multi-source-data-ingestion`、`runtime-and-verify`、`contract-openapi-drift` |
| `plans/` | 计划（历史计划已从 `.trae/documents/` 迁入，归档在 `memory/archive/`） |
| `progress/` | 进度 / 验证追踪：FY-SMAP 系列、`ui-verification-steps.md`、`2026-08-04-pending-tasks-audit.md`（待完善排期 SSOT）、`2026-08-04-test-reorganization.md`、`2026-08-04-backend-32-fixes.md`（后端 pytest 全绿） |
| `memory/` | AI 记忆 / 历史上下文：`MEMORY.md`（长期记忆：仓库约定、环境硬约定、已知坑、事故记录）、`YYYY-MM-DD[-主题].md`（日志，如 `2026-09-10-git-restore-and-sync.md`）、`archive/`（原 `.trae/documents/*` ~72 份历史计划与对话） |
| `docs/` | 项目文档（原 `Doc/` 整体迁入）：`design/`（架构/设计）、`specs/`（规范/spec）、`reference/`（任务记录/验证报告） |

## 怎么用

- **改代码前**：先读 `rules/project-conventions.md` + 根 `AGENTS.md`（「改 X 则跑 Y」映射）。
- **做反演 / 数据接入**：读 `skills/` 对应技能。
- **看进度 / 历史决策**：`progress/` 与 `memory/archive/`。
- **查设计 / 规范**：`docs/` 下各子目录。
- **找临时的MCP** : 直接读取mcp.json。

## 维护约定

- 新增/修改项目硬约定 → 只改 `rules/project-conventions.md`，工具指针文件保持不动。
- 沉淀可复用流程 → 新增 `skills/*.md`。
- 不要把明文凭据、私有服务器地址写进本目录（凭据走安全存储，仅描述通道）。

## IDE / AI 工具可读性

``.ai/`` 已随仓库提交，但 `.ai/mcp.json` 与 `.ai/tmp/` 仍 gitignore；各工具本地读取：

| 工具 | 做法 |
|------|------|
| Cursor | `.ai/` 已随仓库提交，无需 `.cursorignore` 反排除（该文件已于 2026-09-10 移除） |
| VS Code / Cursor 资源管理器 | `.vscode/settings.json` 的 `files.exclude` / `search.exclude` **不得**排除 `.ai` |
| Trae / Copilot / Claude / WorkBuddy | 入口仍读根 `AGENTS.md` / `CLAUDE.md` 指针；本目录为约定与进度真源 |
| 验证 | Agent 应能 Glob/Read `.ai/progress/*`、`.ai/rules/*` |

若 Cursor 仍搜不到 `.ai`：Settings → Indexing → Refresh；确认 Hierarchical Cursor Ignore 未在上级目录再次忽略。
