# 计划：将 AI 上下文集中到 `.ai/` 并清理仓库表面

## 目标

1. 在仓库根目录新建隐藏文件夹 **`.ai/`**，作为所有 AI 提示 / 技能 / 计划 / 进度 / 记忆 / 文档的**单一归属地**。
2. 仓库根「表面」只保留三份人类与通用 AI 都会阅读的文档：**`AGENTS.md`、`CLAUDE.md`、`README.md`**。
3. 全面检查代码与文档，把现有文档内容重新组织进 `.ai/`。
4. 基于最近工作（FY/SMAP `omega_sf` 反演、多源数据接入等）在 `.ai/skills/` 中设计实用的 AI 技能文档。
5. `.ai/` 加入 `.gitignore`，**不推送到 GitHub**。

## 已确认的设计决策（来自用户）

- 文件夹名 / 可见性：**`.ai/`**（隐藏目录）。
- 工具规则文件（` .cursor/rules/`、`.trae/rules/`、`.github/copilot-instructions.md`）路径锁定、必须留在原位才能被工具自动读取 → 改为**简短指针**，完整约定文本作为单一真源存入 **`.ai/rules/`**。
- 文档搬迁范围：**全部迁入** —— `Doc/`、根目录 `FY_SMAP_*.md`、`UI_VERIFICATION_STEPS.md`、`.trae/documents/*` 全部移入 `.ai/`。

## 目标目录结构

```text
.ai/                                  # 全部 AI 上下文（gitignore，本地专用）
├── README.md                         # 索引：本文件夹导航 + 各子目录说明
├── rules/                            # 单一真源：完整约定文本
│   ├── project-conventions.md        # 项目硬约定（运行时/launch/改X则跑Y/高风险区/提交规范）
│   ├── qingtian-decision-policy.md   # MCP 决策策略
│   └── git-commit-message.md         # Conventional Commits 规范
├── skills/                           # 可复用 AI 技能文档（本次重点产出）
│   ├── omega-sf-inversion.md         # FY/SMAP 土壤水分反演 + Matlab 一致性校验
│   ├── multi-source-data-ingestion.md# 校园SSH/NAS/NSIDC SMAP/Earthdata 多源接入
│   ├── runtime-and-verify.md         # 运行时与验证命令映射（防环境幽灵问题）
│   └── contract-openapi-drift.md     # 前后端契约与 OpenAPI 漂移防护
├── prompts/                          # 可复用提示模板（先建空目录 + 1 个种子示例）
├── plans/                            # 计划（迁入 .trae/documents/plan_*.md 等）
├── progress/                         # 进度/验证追踪（迁入根 FY_SMAP_*.md + UI_VERIFICATION_STEPS.md）
│   ├── fy-smap-progress-tracker.md
│   ├── fy-smap-fix-execution-plan.md
│   ├── fy-smap-fix-summary.md
│   ├── fy-smap-full-verification-guide.md
│   ├── fy-smap-remediation-plan.md
│   └── ui-verification-steps.md
├── memory/                           # AI 记忆/历史上下文（迁入 .trae/documents/*）
│   └── archive/                      # 旧对话/历史计划（~70 份）
└── docs/                             # 重新组织的项目文档（迁入 Doc/）
    ├── design/                       # 架构/设计（后端架构设计、工程决策纪要、技术栈…）
    ├── specs/                        # 规范/spec（规范文档、远程存储接入说明、数据源对照…）
    ├── reference/                    # 任务记录/验证报告（omega_sf_*_vs_matlab、任务说明、结题报告…）
    └── README.md                     # docs 子索引
```

## 执行步骤

### 1. 创建 `.ai/` 骨架目录
建立 `rules/ skills/ prompts/ plans/ progress/ memory/archive/ docs/{design,specs,reference}/`。

### 2. 搬迁文档
- `Doc/**` → `.ai/docs/{design,specs,reference}/`（按上表分类；图片/PDF 随原文档一并移入对应子目录）。
- 根目录 `FY_SMAP_*.md`（5 份）+ `UI_VERIFICATION_STEPS.md` → `.ai/progress/`。
- `.trae/documents/*` → `.ai/memory/archive/`（其中 `plan_*.md` 等归入 `.ai/plans/`）。

### 3. 生成技能文档 `.ai/skills/`（基于最近工作，执行时先读真实代码核对）
- **omega-sf-inversion.md**：关键文件 `Code/algorithms/providers/Python/algorithms/omega_sf.py`、Matlab 参考 `Code/algorithms/providers/Matlab/omega_sf_fenkuai.m`；校验法：`Env\Python312\python.exe launch.py start worker:omega_sf` 后对 run-* 产物算 MAE，对照 `.ai/docs/reference/omega_sf_*_vs_matlab_*.md`（FY MAE≈0.046–0.058，SMAP MAE≈0.006–0.053）；已知坑：preload 全 NaN、`event_factory` 即时落库 + `INSERT OR IGNORE`、bbox 列表参数展开、8 天块/空间显示不匹配、日期鲁棒性、文件名三级匹配。
- **multi-source-data-ingestion.md**：校园 SSH（172.16.98.184，likr6008）/ NAS Filebrowser / NSIDC SMAP SPL3SMP_E v6 / Earthdata；后端 `app/api/config_routes.py` + `shared/remote_sources`（sftp/smb/ftp/gs）；**凭据属私有，禁止提交**。
- **runtime-and-verify.md**：`Env/Python312` 唯一运行时、`launch.py` 命令指针、「改 X 则跑 Y」映射、pre-commit、`pytest`、`npm run check:openapi`、Windows Docker 管理员。
- **contract-openapi-drift.md**：`Code/shared/contracts/` + `Code/frontend/src/types/api-contracts.ts`（自动生成勿手改）、`npm run check:openapi` 为 CI 质量门。

### 4. 建立 `.ai/rules/` 单一真源
把现有 `.cursor/rules/project-conventions.mdc`、`.cursor/rules/qingtian-decision-policy.mdc`、`.trae/rules/git-commit-message.md` 的完整内容整理进 `.ai/rules/` 对应文件。

### 5. 将原工具规则改为指针
- `.cursor/rules/project-conventions.mdc`、`.cursor/rules/qingtian-decision-policy.mdc` → 仅保留一句：完整约定见 `.ai/rules/<file>.md`，改动前先读。
- `.trae/rules/project-conventions.md`、`.trae/rules/git-commit-message.md` → 同上精简为指针。
- `.github/copilot-instructions.md` → 精简为指针，指向 `.ai/rules/project-conventions.md`。

### 6. 新建根目录 `CLAUDE.md`（Claude Code 入口）
- 精简版：关键硬约定（唯一运行时、Windows Docker 管理员、高风险区 4 项、launch 命令）+ 指向 `AGENTS.md`（完整导航）与 `.ai/`（技能/计划/进度/记忆/文档）。避免与 AGENTS.md 全文重复。

### 7. 更新 `AGENTS.md` 与 `README.md`（仅这三份留表面）
- `AGENTS.md`：目录路由表中 `Doc/` 改为 `.ai/docs/`；新增「AI 知识库」小节指向 `.ai/`（skills/rules/progress/memory）。
- `README.md`：文档导航中 `Doc/...` 链接改为 `.ai/docs/...`；新增指向 `.ai/` 的说明。

### 8. 更新 `.gitignore`
- 追加 `.ai/`（整目录不推送）。
- **保持** `.github/workflows/ci.yml` 不被忽略（CI 必须可推送）；`.cursor/`、`.trae/rules/` 指针文件可保留在 GitHub（体积小、对协作者有用）。

### 9.（可选）根目录零散验证脚本归置
`check_omega_results.py`、`diagnose_omega_issue.py`、`test_fy_smap_regression.py`、`test_compare_matlab.py`、`test_config.py`、`inspect_matlab_ref.py` 等一次性诊断/校验脚本，视情况移入 `Tools/` 或 `.ai/docs/reference/`（不阻塞主流程，执行时与用户确认）。

### 10. 验证
- `git status`：根目录仅 `AGENTS.md / CLAUDE.md / README.md` 为文档；`.ai/` 已忽略、不出现于待提交列表。
- 确认 `.cursor/`、`.trae/rules/`、`.github/copilot-instructions.md` 指针指向存在且正确的 `.ai/rules/` 文件。

## 关键文件清单（将创建/修改）

- 新建：`.ai/README.md`、`.ai/rules/*.md`（3）、`.ai/skills/*.md`（4）、`.ai/prompts/`（种子）、`.ai/progress/*.md`（6）、`.ai/memory/archive/*`、`.ai/docs/**`、根 `CLAUDE.md`
- 修改（精简为指针）：`.cursor/rules/project-conventions.mdc`、`.cursor/rules/qingtian-decision-policy.mdc`、`.trae/rules/project-conventions.md`、`.trae/rules/git-commit-message.md`、`.github/copilot-instructions.md`
- 修改（更新链接）：`AGENTS.md`、`README.md`、`.gitignore`
- 删除原位置：原 `Doc/`、`FY_SMAP_*.md`、`UI_VERIFICATION_STEPS.md`、`.trae/documents/*`（搬迁后移除）

## 风险与注意

- **工具规则文件不可移动**：`.cursor/`、`.trae/rules/`、`.github/copilot-instructions.md` 必须留在原路径，否则对应 AI 工具无法自动加载（仅改为指针）。
- **CI 不被破坏**：`.github/workflows/ci.yml` 保持可推送。
- **`.ai/` 为本地专用**：GitHub 克隆不含 `.ai/`，指针文件在 GitHub 上指向本地目录属预期（协作者本地会有）。
- **凭据安全**：数据接入技能文档中涉及私有服务器/隧道/账号，仅描述通道与后端接口，不写入明文凭据（凭据已存于安全处，不进 `.ai/` 也不进 git）。
- 执行技能文档时会先实际读取对应源码（omega_sf.py、config_routes.py、contracts 等）核对事实，确保文档准确，满足「全面检查代码」。
