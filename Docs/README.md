# CGDA 文档中心

综合地理数据分析系统（CGDA）公开文档仓库，按主题分类存放架构设计、规范协议、专题研究、代码审查、结题材料等。

> **活文档**以模块 README、`AGENTS.md`、本目录下无日期的架构/协议文档为准；**带日期的快照**仅作历史参考，不覆盖现行结构。

## 与 `.ai/` 的分工

| 位置 | 面向 | 是否进 GitHub |
|------|------|----------------|
| `Docs/` | 人类开发者 / 结题与审查材料 | 是 |
| `.ai/` | AI 技能、规则、计划、进度、记忆 | 否（本地专用） |

根目录仅保留 `AGENTS.md`、`CLAUDE.md`、`README.md` 三份 AI/工程入口；细节导航见 `AGENTS.md`。

## 目录结构

| 编号 | 目录 | 说明 |
|------|------|------|
| 01 | `01-协作规范/` | 文档治理、Git/前后端协作、任务清单、工程收口仪表盘 |
| 02 | `02-架构设计/` | 后端架构、空间表、工作流编辑器、工程决策纪要、架构图 |
| 03 | `03-规范协议/` | 技术栈/规范、PRD、命名、工作流节点、数据源与契约说明 |
| 04 | `04-执行部署/` | 本地联调环境、交付清单 |
| 05 | `05-专题研究/` | 天气渲染、omega_sf 反演、数据集目录、命名研究、其它专题 |
| 06 | `06-代码审查/` | 各轮代码审查报告与问题追踪 |
| 07 | `07-工程保障/` | 预启动检查、工程收口、功能验证、UI/底图修复记录 |
| 08 | `08-HTML报告/` | 可交互 HTML（project-overview、frontend-design-audit） |
| 09 | `09-结题材料/` | 结题报告、验收材料、修改意见 |
| 10 | `10-参考示例/` | Windy 等外部参考资料 |
| 99 | `99-历史归档/` | 代码事实同步快照、历史任务记录 |

## 推荐阅读路径（新人）

1. 仓库根 `README.md` → `AGENTS.md`（命令、高风险区、「改 X 则跑 Y」）
2. `Code/README.md` → `Code/backend/README.md` → `Code/frontend/README.md`
3. `Docs/01-协作规范/文档治理说明.md`
4. `Docs/02-架构设计/工程决策纪要-配置瓦片与契约.md`（瓦片双入口 / 配置投影 / 契约 CI）
5. `Docs/02-架构设计/图层分析面板.md`（InfoPanel GIS 五工具 + 产物闭环）
6. `Docs/02-架构设计/后端架构设计.md`
7. `Docs/03-规范协议/双通道接口设计总结.md`、`规范文档.md`
8. `Code/shared/contracts/README.md` + `Code/algorithms/providers/Python/README.md`
9. 按需：`05-专题研究/`、`04-执行部署/本地联调环境说明.md`

## HTML 报告（可更新）

- **`08-HTML报告/project-overview/`** — 项目全景总览
- **`08-HTML报告/frontend-design-audit/`** — 前端设计审查报告
- **`08-HTML报告/security-audit-report/`** — 安全审计报告（13 模块审计发现）
- **`08-HTML报告/security-upgrade-summary/`** — 安全升级总结报告
- **`08-HTML报告/codebase-health-report/`** — 代码库健康审查报告（Brooks-Lint）
- **`08-HTML报告/omega-algorithm-guide/`** — ω 反演算法详解与工作流指南（τ-ω 单/双温度模型 · D1/D2/SF 谱系 · 13 条工作流 2×2×2 矩阵；现行基准，对应提交 37b4fe1）
- **`08-HTML报告/workflow-pipeline-panorama/`** — 工作流与端到端流水线全景（历史快照 2026-08-18，ω 族清单为 2×2×2 重组前状态，文内已注明）
- **`08-HTML报告/omega-sf-migration-mapping/`** — omega_sf_fenkuai Matlab→Python 策略移植对照（历史快照 2026-08-18，工作流部分为重组前状态；Matlab 行号引用仍有效）
- **`08-HTML报告/code-review-findings-2026-08-14/`** — 代码审查报告（历史快照 2026-08-14，问题修复状态以当前代码为准）
- **`08-HTML报告/acceptance-evidence/`** — 结题验收证据（OpenAPI 接口清单 / 健康检查与运行日志 / 产品入库记录 / 数据可用性与数据源说明）

## 2026-08 代码对齐要点（摘要）

| 主题 | 现行事实 | 详文 |
|------|----------|------|
| 底图 vs 天气瓦片 | `/unified-tiles` 栅格；`/weather/tiles` GeoJSON；勿混用 | `02-架构设计/工程决策纪要-…` |
| 天地图街道 | `tianditu-vec` + `tianditu-cva` overlay；代理 UA=`CGDA-Backend/1.0` | `07-工程保障/UI优化与底图模块修复-2026-08-12.md` |
| 配置门面 | `config_service` 再导出 L3：`config_api_keys` / GEE / weather / remote_storage | `Code/backend/README.md` |
| 图层 store | `stores/layers/` 域拆分：bindings / selectors / workspace\|viewport\|workflow-run-domain | `Code/frontend/README.md` |
| 图层目录真源 | 后端 `catalog_seeds/*.json`；前端 `gen:catalog` → `catalog-seeds.generated.json`；`check:catalog` 门禁 | `Tools/generate_catalog_seeds.py`、`AGENTS.md` |
| 在线时序编排 | Timeline 驱动自动取数：`online-temporal-orchestrator.ts` + `useOnlineTemporalIntegration.ts` | `Code/frontend/src/stores/layers/` |
| 默认同域入口 | `launch.py start`/`restart` → Nginx Gateway `:5175`；HMR：`start --vite` | `Code/infra/gateway/README.md` |
| 测试落点 | 后端/算法：`Test/`；前端：`Test/frontend/`（由 Vite vitest 加载） | `AGENTS.md` |
