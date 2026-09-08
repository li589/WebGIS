# 2026-09-03 — 散射约束产品改名 + 主题组类隐藏

## 产品改名

- 图层/合集展示：`… ω 反演` → `… 散射约束产品`（合集如 `风云 散射约束产品` / `SMAP 散射约束产品`）。
- 工作流/流水线：`{卫星} {动态|平均} 散射约束产品反演（…）`；变体按钮仍为「在线反演 / 本地反演」。
- **不变**：`layer_id` / `workflow_id` / 产物短标 SM·VOD·ω；算法物理表述（τ-ω）保留。
- 真源：`catalog_seeds/layer_descriptors.json` → `npm run gen:catalog`；`workflow_seeds/system/omega_*.json`（启动 `_sync_system_seeds` 覆盖 runtime system 定义）。

## 主题组 / 二级组类隐藏

- 契约：`LayerCategoryDef.hidden`、`hidden_sub_categories`（create/update/theme-preset 同步）。
- 持久化：主题预设 JSON groups[]；个人工作区 SQLite 列 `hidden` / `hidden_sub_categories`（迁移 ADD COLUMN）。
- API：无 `theme_id` 的 `GET /layers/categories` 过滤 `hidden` 顶层组；`?theme_id=` / theme-preset 全量。
- FE：分组管理「隐藏/显示」+ 编辑态二级勾选；`useSidebarSearch` 过滤顶层与二级；`refreshRuntime` 同页刷新。

## 验证

- `Test/backend/test_layer_groups.py`（含 `test_theme_group_hidden_filtered_for_consumers`）
- FE：`inversion-catalog` / `workflow-run-display-name` / `permission-resources` / `check:catalog` / `check:openapi`

## 联调注意

- 改名后需重启 backend（或至少加载 workflow 定义）使流水线列表名更新。
- 隐藏写入主题预设，按主题分别配置；不影响种子 JSON。
