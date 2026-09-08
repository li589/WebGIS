# AI 工作产物归集清单（2026-08-19）

> 将 `.ai` 文件夹之外的 AI 生成 / AI 工作文档·报告·计划 / 临时探针脚本，按类型归类移入 `.ai`。
> 全部为 gitignored 文件，迁移对 git 跟踪零影响。

## 一、迁移总览

| 来源（迁移前位置） | 数量 | 归入 `.ai` 目标 | 类型 |
|---|---|---|---|
| `.trae/documents/` | 56 | `.ai/memory/archive/trae-documents-20260819/` | Trae 计划/报告/脚本/图（08-15→08-19） |
| `.trae/tmp/` | 16 | `.ai/progress/archive/trae-tmp-20260819/` | Trae 临时产物（png/geojson/py/txt） |
| 根 `_tmp_*` | 18 | `.ai/progress/archive/tmp-probes-20260817/` | AI 探针脚本/数据 dump（08-17） |
| 根 `tmp/` | 1 | `.ai/progress/archive/tmp-repro-20260819/` | 复现产物（repro-v2r-4f102c87） |
| 根 `temp.txt` | 1 | `.ai/progress/archive/root-stray-20260819/` | 临时文本 |
| 根 `nul`（120B，Windows 保留名） | — | 内容另存 `root-stray-20260819/nul-stray-20260819.bin` | 垃圾文件，原文件保留（见下） |
| `.ai` 根 `tmp-*.txt`（3） | 3 | `.ai/progress/archive/` | auth/fe 差异草稿 |

**合计迁移文件：94 个**（含 3 个 `.ai` 根清理）。

## 二、保留未动（说明理由）

- **`.trae/rules/git-commit-message.md`**：工具规则指针，按 `.ai/README.md` 约定保留原位，不迁移。
- **`Docs/`（212 文件）**：AGENTS.md 定义的**公开文档库**（架构/规范/代码审查/HTML 报告/结题材料），AI 生成的项目交付物，非 AI 私有草稿，维持公开库定位。
- **`.cursor/`、`.qoder/`、`.vscode/`**：各 AI/IDE 工具配置与状态目录，非 AI 工作文档。
- **`Test/debug/`（27 脚本）**：属 `Test/` 测试树的 debug 集中地（AGENTS.md 约定），保留。
- **根 `nul`**：Windows 保留设备名，命令行无法 rename/delete（已验证 os.rename/os.remove/cmd del 均 Access Denied，MSYS 还会吞路径）。内容已另存，原文件无害（gitignored），待用户手动删除。

## 三、Trae 未完成任务进度（核查结论）

- **在飞（08-19）**：ω 变体路由 + 图层组在线反演。代码已落盘，**未提交、未验证**：X2 变体修复零单测、前端 dist 过期、online_temporal 未配、组状态芯片无配色、上轮 ω run 被重启杀需清理。工作区 29 modified + 49 untracked。
- **保留待办**（详见 `.ai/progress/2026-08-18-unclosed-items-audit.md`）：前端重构 V3 收尾、P2 backlog、真实数据 e2e/NAS（阻塞数据环境）、`project-conventions.md` 鉴权模型漂移、U1–U4 用户手动项。

## 四、后续建议

1. 手动删除根 `nul`（资源管理器或重启后处理），或忽略（已 gitignore）。
2. 如希望把 `Docs/` 中「纯 AI 内部」子集（如 `06-代码审查`、`07-工程保障`、`99-历史归档`）也归入 `.ai`，可再单独执行（会改变公开库引用，需同步 AGENTS.md）。
3. 在飞 ω 任务如需继续，建议先 `npm run build` 重建 dist → 跑 `test_workflow_request_resolver.py` 等 3 个新测试 → API 级实跑验证。
