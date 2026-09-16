# WorkBuddy 计划归档（2026-09-16 迁入）

## 为什么有这份归档

WorkBuddy 的计划文件原先只落在**工具用户级目录** `~/.workbuddy/plans/`（随机代号命名），
不在版本库内：换机器、换工具、清理工具缓存都会丢，团队成员也看不到。

本目录按 `.ai/memory/archive/trae-documents-20260819/` 的既有先例，把**属于本仓库（CGDA）**
的计划整体迁入 `.ai/`，作为可版本化、可检索的历史计划真源。

- **迁移方式**：`cp -p` 复制（保留原始 mtime），**原文件未删除**——`~/.workbuddy/plans/` 原样保留。
- **文件命名**：保留 WorkBuddy 原始代号（如 `radiant-pulse-einstein.md`），不改名以免丢失追溯线索；
  主题与日期见下表。
- **索引维护**：新增归档条目时同步更新本表。

## 清单（13 份，均属 CGDA）

| 原始文件（代号） | 主题 | 计划日期 |
|---|---|---|
| `cosmic-cascade-curie.md` | 将 AI 上下文集中到 `.ai/` 并清理仓库表面（本目录结构的来源计划） | 2026-08-04 |
| `stellar-thunder-newton.md` | 修复后端 32 个 pytest 失败项 → 全绿 | 2026-08-04 |
| `toasty-aurora-curie.md` | SpatiaLite (`mod_spatialite`) 升级计划 | 2026-08-05 |
| `toasty-vortex-tesla.md` | 地理数据分析系统 — 三任务实现计划 | 2026-08-08 |
| `electric-vortex-newton.md` | ω 反演图层组在线反演 · 续接执行计划 | 2026-08-20 |
| `radiant-vortex-curie.md` | 反馈中心前端页面移动端 / 小屏适配（`Code/infra/gateway/maintenance/html/`） | 2026-08-20 |
| `swift-pulse-darwin.md` | 硬编码清理计划（可配置性 + 跨平台部署） | 2026-08-20 |
| `toasty-aurora-einstein.md` | 基础设施安全审计修复（nginx 页面定向 / API 文档暴露 / 供应链） | 2026-08-20 |
| `electric-nebula-einstein.md` | 两阶段实施计划：六源在线下载验证（#58） | 2026-08-21 |
| `quantum-thunder-newton.md` | 阶段 3/6：访问模式扩展与存量迁移 — 集成计划 | 2026-08-21 |
| `swift-thunder-turing.md` | 缓存优先 + 后台刷新（消除"未配置分析工作流引擎"文案污染） | 2026-08-21 |
| `toasty-aurora-turing.md` | 远程数据源数据集化改造 — 实现方案 | 2026-08-21 |
| `radiant-pulse-einstein.md` | 图层平台子系统 P0 升级实施计划 | 2026-08-24 |

> 相关进度/结论多在 `.ai/progress/` 与 `.ai/memory/`（如 `2026-08-04-backend-32-fixes.md`
> 对应 `stellar-thunder-newton`；`2026-08-05-hardcode-*.md` 对应 `swift-pulse-darwin`）。
> 本目录存**计划（怎么做）**，`progress/` 存**结果（做完没）**，两者互补，不重复。

## 已核查但**未**迁入的内容（含原因）

| 来源 | 内容 | 未迁入原因 |
|---|---|---|
| `~/.workbuddy/plans/quantum-cascade-turing.md` | 「Clawdroid：AI 文档统一化」 | **非本仓库项目**（Go `ClawRuntime` + Kotlin App，另一套 `Docs/` 与 IPC 契约）。经全仓库检索 `Clawdroid` 零命中，确认不属 CGDA。 |
| `~/.workbuddy/memory/*_memory.md` | 用户记忆画像（含 `7886fced-*` CGDA 画像、`8751befb-*` 他项目画像） | **服务端托管缓存**，由云端注入并在下次会话覆盖；本地副本入库会立即过时并造成双真源。项目级长期记忆以 `.ai/memory/MEMORY.md` 为准。 |
| `~/.workbuddy/MEMORY.md`、`SOUL.md`、`IDENTITY.md`、`USER.md` | 智能体身份与跨项目用户记忆 | **跨项目、非本仓库专属**，按分层约定留在用户级（`~/.workbuddy/`）。 |
| `~/.workbuddy/{logs,traces,binaries,plugins,skills,workspace,projects,blobs,cache,file-history,...}` | 运行时数据（合计约 7 GB+） | 工具运行时资产，非 AI 上下文；其中 `logs`/`traces` 含大量噪声与可能的敏感内容，**不入库**。 |

## 后续

- 若确认无需保留，可删除 `~/.workbuddy/plans/` 中的这 13 份原件（本目录已完整留存）。
  **删除前请确认**：该目录由 WorkBuddy 工具写入，删除属工具外部操作。
- 后续 WorkBuddy 会话产出的计划，建议直接在仓库内落到 `.ai/plans/`（当期）或本目录（历史）。
