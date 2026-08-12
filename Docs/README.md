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
5. `Docs/02-架构设计/后端架构设计.md`
6. `Docs/03-规范协议/双通道接口设计总结.md`、`规范文档.md`
7. `Code/shared/contracts/README.md` + `Code/algorithms/providers/Python/README.md`
8. 按需：`05-专题研究/`、`04-执行部署/本地联调环境说明.md`

## HTML 报告（可更新）

- **`08-HTML报告/project-overview/`** — 项目全景总览
- **`08-HTML报告/frontend-design-audit/`** — 前端设计审查报告

## 2026-08 代码对齐要点（摘要）

| 主题 | 现行事实 | 详文 |
|------|----------|------|
| 底图 vs 天气瓦片 | `/unified-tiles` 栅格；`/weather/tiles` GeoJSON；勿混用 | `02-架构设计/工程决策纪要-…` |
| 天地图街道 | `tianditu-vec` + `tianditu-cva` overlay；代理 UA=`CGDA-Backend/1.0` | `07-工程保障/UI优化与底图模块修复-2026-08-12.md` |
| 配置门面 | `config_service` 再导出 L3：`config_api_keys` / GEE / weather / remote_storage | `Code/backend/README.md` |
| 图层 store | `stores/layers/` 域拆分：bindings / selectors / workspace\|viewport\|workflow-run-domain | `Code/frontend/README.md` |
| 测试落点 | 后端/算法：`Test/`；前端：`Test/frontend/`（由 Vite vitest 加载） | `AGENTS.md` |
