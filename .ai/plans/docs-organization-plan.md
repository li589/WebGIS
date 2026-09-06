# CGDA 项目文档归类整理计划

## 一、目标与原则

### 目标
根目录表面仅保留 `.ai/` 和 `Docs/` 两个文档类目录，其它文档全部合理归类；零散非代码文件清理干净。

### 原则
- **`.ai/`** 作为 AI 工作区（本地专用，不上传 GitHub），保留其 `plans/`、`progress/`、`memory/`、`rules/`、`skills/` 结构
- **`Docs/`** 作为表面可见的正式文档目录，按主题分类，面向人类开发者
- 已在 `.gitignore` 中的缓存目录（`.mypy_cache/`、`.pytest_cache/` 等）保持不动
- 不触碰代码目录（`Code/`、`Test/`、`Tools/`、`Env/`、`launch.py`、`launch/` 等）
- `frontend-design-audit/` 和 `project-overview/` 作为可更新 HTML 报告，整体迁入 `Docs/`

---

## 二、Docs/ 新目录结构

采用"数字前缀 + 语义目录名"的组织方式，编号确保阅读顺序稳定。

```
Docs/
├── README.md                              ← 文档总索引与导航
├── 01-协作规范/                            ← 团队协作与开发指南
│   ├── Git协作说明.md
│   ├── 前端开发者协作说明.md
│   ├── 后端开发者协作说明.md
│   ├── 文档治理说明.md
│   ├── 工程收口仪表盘.md
│   └── 项目任务清单.md
├── 02-架构设计/                            ← 架构层（设计与决策）
│   ├── 后端架构设计.md
│   ├── 架构设计.png
│   ├── class-diagram.mermaid
│   ├── sequence-diagram.mermaid
│   ├── SpatiaLite空间表设计.md
│   ├── SpatiaLite代码审查与跨平台改进.md
│   ├── 设计_omega_sf重构.md
│   ├── 设计_异常捕获收窄.md
│   ├── workflow-editor-ui.md
│   ├── 工程决策纪要-配置瓦片与契约.md
│   ├── 开放门户工具流组件说明.md
│   └── Draw/                              ← 技术栈图生成脚本与产物
├── 03-规范协议/                            ← 协议层 + 规范 + PRD
│   ├── 规范文档.md
│   ├── 技术介绍.md / .pdf
│   ├── 技术栈.md / .pdf
│   ├── layer-naming.md
│   ├── workflow_seed_conventions.md
│   ├── workflow_stub_nodes.md
│   ├── stub_node_enablement.md
│   ├── workflow_node_system_settings_map.md
│   ├── PRD_增量_异常捕获收窄.md
│   ├── 数据源与工作流对照说明-2026-07-21.md
│   ├── 课题组数据需求与产出说明.md
│   ├── 当前数据源与产出一览.md
│   ├── 远程存储接入说明.md
│   ├── 双通道接口设计总结.md
│   └── design-system-spec.md
├── 04-执行部署/                            ← 执行层 + 环境 + 交付清单
│   ├── 本地联调环境说明.md
│   └── delivery-checklist.md
├── 05-专题研究/                            ← 专题层（按技术方向组织）
│   ├── 数据集目录/
│   │   ├── CGDA数据集与图层综合对照表-2026-08-11.md
│   │   ├── CGDA数据集与图层综合对照表-2026-08-11.docx
│   │   └── 20260811-dataset-layer-catalog/
│   ├── omega_sf反演/
│   │   ├── omega_sf_smap_dec2025_vs_matlab_parity.md
│   │   ├── omega_sf_export_tif_vs_matlab_detail.md
│   │   ├── omega_sf_export_tif_vs_matlab_detail.json
│   │   ├── fy-smap-fix-summary.md
│   │   └── fy-smap-full-verification-guide.md
│   ├── 天气渲染/
│   │   ├── 天气渲染进度同步-2026-07-21.md
│   │   ├── weather-rendering-fix-2026-08-06.md
│   │   └── 本地Open-Meteo完善计划-2026-07-21.md
│   ├── 命名研究/
│   │   ├── renaming-research-plan.md
│   │   ├── renaming-research-plan-v2.md
│   │   └── renaming-research-plan-v3.md
│   └── 其它专题/
│       ├── hardcode-extension-audit.md
│       ├── 性能基线-风场核显.md
│       ├── 真实数据e2e门槛.md
│       ├── 课题组数据全链路-2026-07-21.md
│       ├── basemap-cache-review-20260811.md
│       └── workflow_scheduling_audit_report.md
├── 06-代码审查/                            ← 代码审查报告集合
│   ├── 代码审查纪要-2026-07-21.md
│   ├── code-review-2026-08-05.md
│   ├── code-review-2026-08-09.md
│   ├── code-review-2026-08-09-arch-flow.md
│   ├── code-review-2026-08-10.md
│   ├── code-review-2026-08-10-correctness-concurrency.md
│   ├── code-review-2026-08-11-workflow-scheduling.md
│   ├── code-review-problem-report-20260811.md
│   ├── code-review-fullstack-2026-08-09.md
│   ├── code-review-fullstack-2026-08.md
│   ├── 2026-08-11-global-code-review.md
│   ├── 2026-08-12-global-code-review.md
│   ├── fix-review-b1-b2-2026-08-09.md
│   ├── fix-review-b1-b2-2026-08.md
│   ├── fix-review-b2b3-round2-2026-08.md
│   └── fix-review-settings-gentypes-2026-08.md
├── 07-工程保障/                            ← 工程质量、CI、交付计划
│   ├── ci-green-cgda-dev-2026-08-09.md
│   ├── phase2-cgda-closeout-2026-08-08.md
│   ├── rereview-cgda-fixes-2026-08-08.md
│   ├── code-review-cgda-uncommitted-2026-08-08.md
│   ├── pre-launch-check-cgda-2026-08-04.md
│   ├── functional-check-2026-08-11.md
│   ├── s1-s2-s3-implementation-2026-08-09.md
│   ├── frontend-fix-plan.md
│   └── UI优化与底图模块修复-2026-08-12.md
├── 08-HTML报告/                            ← 可更新 HTML 报告
│   ├── frontend-design-audit/
│   │   ├── frontend-design-audit.html
│   │   ├── _shared/
│   │   └── assets/
│   └── project-overview/
│       └── project-overview.html
├── 09-结题材料/                            ← 项目结题验收
│   ├── 《星地数据融合土壤水分监测与干旱智能预警系统》结题验收材料-早期初稿.docx
│   ├── 《星地数据融合土壤水分监测与干旱智能预警系统》结题验收材料-早期初稿-命名更新版.docx
│   ├── _backup_结题验收材料-命名更新版-原始备份.docx
│   ├── 导师修改意见-命名.docx
│   └── 星地融合项目结题报告.md
├── 10-参考示例/                            ← 外部产品参考（原 Example/）
│   └── Windy参考/
│       ├── Windy.app/
│       └── Windy.com/
└── 99-历史归档/                            ← 过时但需保留的历史记录
    ├── 代码事实同步/
    │   ├── 代码事实同步文档-2026-07-06.md
    │   ├── 代码事实同步文档-2026-07-15.md
    │   └── 代码事实同步文档-2026-07-16.md
    └── 任务记录/
        ├── 一份任务说明-7.25.txt
        └── 一份任务记录-8.01.txt
```

---

## 三、文件移动清单

### 3.1 原 Docs/ 根目录文件

| 原路径 | 目标路径 |
|--------|---------|
| `Docs/Git协作说明.md` | `Docs/01-协作规范/Git协作说明.md` |
| `Docs/前端开发者协作说明.md` | `Docs/01-协作规范/前端开发者协作说明.md` |
| `Docs/后端开发者协作说明.md` | `Docs/01-协作规范/后端开发者协作说明.md` |
| `Docs/文档治理说明.md` | `Docs/01-协作规范/文档治理说明.md` |
| `Docs/class-diagram.mermaid` | `Docs/02-架构设计/class-diagram.mermaid` |
| `Docs/sequence-diagram.mermaid` | `Docs/02-架构设计/sequence-diagram.mermaid` |
| `Docs/双通道接口设计总结.md` | `Docs/03-规范协议/双通道接口设计总结.md` |
| `Docs/真实数据e2e门槛.md` | `Docs/05-专题研究/其它专题/真实数据e2e门槛.md` |
| `Docs/课题组数据全链路-2026-07-21.md` | `Docs/05-专题研究/其它专题/课题组数据全链路-2026-07-21.md` |
| `Docs/代码事实同步文档-2026-07-06.md` | `Docs/99-历史归档/代码事实同步/` |
| `Docs/代码事实同步文档-2026-07-15.md` | `Docs/99-历史归档/代码事实同步/` |
| `Docs/代码事实同步文档-2026-07-16.md` | `Docs/99-历史归档/代码事实同步/` |
| `Docs/20260811-dataset-layer-catalog/` | `Docs/05-专题研究/数据集目录/20260811-dataset-layer-catalog/`（整体迁移） |
| `Docs/_backup_结题验收材料-命名更新版-原始备份.docx` | `Docs/09-结题材料/` |
| `Docs/《星地数据融合...》结题验收材料-早期初稿-命名更新版.docx` | `Docs/09-结题材料/` |
| `Docs/《星地数据融合...》结题验收材料-早期初稿.docx` | `Docs/09-结题材料/` |
| `Docs/导师修改意见-命名.docx` | `Docs/09-结题材料/` |

### 3.2 deliverables/ 文件

**deliverables/engineering-assurance/ → Docs/07-工程保障/**

| 文件 |
|------|
| `ci-green-cgda-dev-2026-08-09.md` |
| `code-review-cgda-uncommitted-2026-08-08.md` |
| `phase2-cgda-closeout-2026-08-08.md` |
| `rereview-cgda-fixes-2026-08-08.md` |

**deliverables/gstack/ → Docs/07-工程保障/**

| 文件 |
|------|
| `pre-launch-check-cgda-2026-08-04.md` |

**deliverables/ 根目录 → 各目标目录：**

| 文件 | 目标路径 |
|------|---------|
| `CGDA数据集与图层综合对照表-2026-08-11.md` | `Docs/05-专题研究/数据集目录/` |
| `CGDA数据集与图层综合对照表-2026-08-11.docx` | `Docs/05-专题研究/数据集目录/` |
| `basemap-cache-review-20260811.md` | `Docs/05-专题研究/其它专题/` |
| `code-review-2026-08-05.md` | `Docs/06-代码审查/` |
| `code-review-2026-08-09.md` | `Docs/06-代码审查/` |
| `code-review-2026-08-09-arch-flow.md` | `Docs/06-代码审查/` |
| `code-review-2026-08-10.md` | `Docs/06-代码审查/` |
| `code-review-2026-08-10-correctness-concurrency.md` | `Docs/06-代码审查/` |
| `code-review-2026-08-11-workflow-scheduling.md` | `Docs/06-代码审查/` |
| `code-review-problem-report-20260811.md` | `Docs/06-代码审查/` |
| `design-system-spec.md` | `Docs/03-规范协议/` |
| `frontend-fix-plan.md` | `Docs/07-工程保障/` |
| `functional-check-2026-08-11.md` | `Docs/07-工程保障/` |
| `renaming-research-plan.md` | `Docs/05-专题研究/命名研究/` |
| `renaming-research-plan-v2.md` | `Docs/05-专题研究/命名研究/` |
| `renaming-research-plan-v3.md` | `Docs/05-专题研究/命名研究/` |
| `s1-s2-s3-implementation-2026-08-09.md` | `Docs/07-工程保障/` |
| `weather-rendering-fix-2026-08-06.md` | `Docs/05-专题研究/天气渲染/` |

> 整理完成后，**删除** `deliverables/` 目录。

### 3.3 .ai/docs/ 文件

**`.ai/docs/design/` → `Docs/02-架构设计/`**

| 文件 |
|------|
| `后端架构设计.md` |
| `架构设计.png` |
| `SpatiaLite空间表设计.md` |
| `SpatiaLite代码审查与跨平台改进.md` |
| `设计_omega_sf重构.md` |
| `设计_异常捕获收窄.md` |
| `workflow-editor-ui.md` |
| `工程决策纪要-配置瓦片与契约.md` |
| `开放门户工具流组件说明.md` |
| `Draw/`（整体迁移） |

**`.ai/docs/specs/` → `Docs/03-规范协议/`**

| 文件 |
|------|
| `规范文档.md` |
| `技术介绍.md` / `.pdf` |
| `技术栈.md` / `.pdf` |
| `layer-naming.md` |
| `workflow_seed_conventions.md` |
| `workflow_stub_nodes.md` |
| `stub_node_enablement.md` |
| `workflow_node_system_settings_map.md` |
| `PRD_增量_异常捕获收窄.md` |
| `数据源与工作流对照说明-2026-07-21.md` |
| `课题组数据需求与产出说明.md` |
| `当前数据源与产出一览.md` |
| `远程存储接入说明.md` |

**`.ai/docs/reference/` → 各目标目录：**

| 文件 | 目标路径 |
|------|---------|
| `代码审查纪要-2026-07-21.md` | `Docs/06-代码审查/` |
| `天气渲染进度同步-2026-07-21.md` | `Docs/05-专题研究/天气渲染/` |
| `工程收口仪表盘.md` | `Docs/01-协作规范/` |
| `性能基线-风场核显.md` | `Docs/05-专题研究/其它专题/` |
| `星地融合项目结题报告.md` | `Docs/09-结题材料/` |
| `项目任务清单.md` | `Docs/01-协作规范/` |
| `本地Open-Meteo完善计划-2026-07-21.md` | `Docs/05-专题研究/天气渲染/` |
| `本地联调环境说明.md` | `Docs/04-执行部署/` |
| `workflow_scheduling_audit_report.md` | `Docs/05-专题研究/其它专题/` |
| `omega_sf_smap_dec2025_vs_matlab_parity.md` | `Docs/05-专题研究/omega_sf反演/` |
| `omega_sf_export_tif_vs_matlab_detail.md` | `Docs/05-专题研究/omega_sf反演/` |
| `omega_sf_export_tif_vs_matlab_detail.json` | `Docs/05-专题研究/omega_sf反演/` |
| `delivery-checklist.md` | `Docs/04-执行部署/` |
| `hardcode-extension-audit.md` | `Docs/05-专题研究/其它专题/` |
| `一份任务说明-7.25.txt` | `Docs/99-历史归档/任务记录/` |
| `一份任务记录-8.01.txt` | `Docs/99-历史归档/任务记录/` |
| `UI优化与底图模块修复-2026-08-12.md` | `Docs/07-工程保障/` |

> 整理完成后，**删除** `.ai/docs/` 目录（`.ai/` 保留 plans/progress/memory/rules/skills/prompts）。

### 3.4 .ai/progress/ 需公开的文件（复制，非移动）

以下文件从 `.ai/progress/` **复制**到 `Docs/06-代码审查/`，保持 AI 工作区记录完整性：

| 文件 |
|------|
| `code-review-fullstack-2026-08-09.md` |
| `code-review-fullstack-2026-08.md` |
| `fix-review-b1-b2-2026-08-09.md` |
| `fix-review-b1-b2-2026-08.md` |
| `fix-review-b2b3-round2-2026-08.md` |
| `fix-review-settings-gentypes-2026-08.md` |
| `2026-08-11-global-code-review.md` |
| `2026-08-12-global-code-review.md` |
| `fy-smap-fix-summary.md` → `Docs/05-专题研究/omega_sf反演/` |
| `fy-smap-full-verification-guide.md` → `Docs/05-专题研究/omega_sf反演/` |

### 3.5 HTML 报告

| 原路径 | 目标路径 |
|--------|---------|
| `frontend-design-audit/` | `Docs/08-HTML报告/frontend-design-audit/`（整体迁移） |
| `project-overview/` | `Docs/08-HTML报告/project-overview/`（整体迁移） |

### 3.6 Example/ 目录

| 原路径 | 目标路径 |
|--------|---------|
| `Example/Windy.app/` | `Docs/10-参考示例/Windy参考/Windy.app/` |
| `Example/Windy.com/` | `Docs/10-参考示例/Windy参考/Windy.com/` |

> 整理完成后，**删除** `Example/` 目录。

### 3.7 ~/ 目录

**直接删除**整个 `~/` 目录（仅含 pre-commit 缓存意外产物）。

### 3.8 .trae/documents/ 目录

| 文件 | 处理方式 |
|------|---------|
| `ui-optimization-and-basemap-audit-plan.md` | **移动到** `.ai/plans/` |

> `.trae/` 目录本身保留（Trae IDE 配置）。

### 3.9 .trae-html-share-packages/ 目录

**直接删除**整个目录（HTML 报告 zip 包，源文件已在 Docs/08-HTML报告/）。

---

## 四、根目录零散文件处理

### 4.1 删除类

| 文件 | 理由 |
|------|------|
| `pytest_new.log` ~ `pytest_new5.log`（共 5 个） | pytest 运行日志，无保留价值 |
| `_env_probe.log` | 脚本执行日志，无保留价值 |
| `_env_rebuild.log` | 同上 |
| `_env_verify.log` | 同上 |
| `wsl_fix_result.log` | 同上 |
| `_xlsx_dump.json` | 临时 xlsx 导出 dump |
| `nul` | Windows NUL 重定向空文件 |

### 4.2 移动到 Tools/_env_scripts/

新建 `Tools/_env_scripts/` 目录存放环境排查/修复类脚本。

| 文件 |
|------|
| `_env_pip.bat` |
| `_env_probe.bat` |
| `_env_verify.bat` |
| `_probe_numpy.bat` |
| `fix_wsl_vhdx.bat` |
| `rebuild_env_python.bat` |

### 4.3 移动到 .ai/progress/

| 文件 | 理由 |
|------|------|
| `_pipeline_health_static.json` | AI 生成的管道健康检查静态数据 |
| `_stub_inventory.json` | AI 生成的桩节点清单 |

### 4.4 保留不动（缓存类，已 gitignore）

| 目录/文件 |
|-----------|
| `__pycache__/` |
| `.mypy_cache/` |
| `.pytest_cache/` |
| `.ruff_cache/` |
| `.data/` |

---

## 五、.gitignore 调整

| 调整项 | 当前状态 | 调整后 |
|--------|---------|--------|
| `deliverables/` | 第 162 行忽略 | **删除此行**（目录已不存在） |

其余行保持不变。

---

## 六、需同步更新的引用

1. **`AGENTS.md`** — 更新文档路径引用（如 `.ai/docs/design/...` → `Docs/02-架构设计/...`）
2. **html-report 技能约定** — 后续生成报告目标路径改为 `Docs/08-HTML报告/<报告名>/`

---

## 七、执行步骤

1. 新建 Docs/ 子目录骨架（01-协作规范 ~ 99-历史归档，共 11 个目录）
2. 迁移原 Docs/ 内文件到新分类
3. 迁移 .ai/docs/ 内文件到 Docs/ 对应分类
4. 迁移 deliverables/ 内文件到 Docs/ 对应分类
5. 复制 .ai/progress/ 中需公开的审查报告到 Docs/
6. 移动 frontend-design-audit/ 和 project-overview/ 到 Docs/08-HTML报告/
7. 移动 Example/ 到 Docs/10-参考示例/
8. 移动 .trae/documents/ui-optimization-and-basemap-audit-plan.md 到 .ai/plans/
9. 处理根目录零散文件（删除日志/移动脚本/移动 JSON）
10. 删除空目录（deliverables/、~/、Example/、.trae-html-share-packages/、.ai/docs/）
11. 更新 .gitignore（删除 deliverables/ 行）
12. 新增 Docs/README.md（文档总索引）
13. 更新 AGENTS.md 中的文档路径引用
