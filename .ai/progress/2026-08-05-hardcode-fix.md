# 写死点改造进度（批 1–3）

**日期**：2026-08-05  
**计划**：`hardcode_research_and_fix`（不改 plan 文件本身）  
**审计矩阵**：[hardcode-extension-audit.md](../docs/reference/hardcode-extension-audit.md)  
**交付清单**：[delivery-checklist.md](../docs/reference/delivery-checklist.md)

## 批 1 — 路径真源（完成）

- production / 非 test 空 `BACKEND_DATA_ROOT` → `assert_data_root_policy` 拒启
- 算法 `dataset_config` 取消 `I:\` 静默回退
- `workflow_router` / `overlay_registry` 相对 data_root
- workflow seeds `{DATA_ROOT}` / `{DATA_ROOT_WIN}` 展开
- FE 下载/SSH 表单去 I: 占位；SSH 默认空；`.env.example` / MinIO / launch 双轨说明
- 验证：`test_data_root_policy` + 相关 pytest 绿

## 批 2 — 目录 / 地理 / 种子（完成）

- `Tools/check_catalog_drift.py` + `npm run check:catalog` + CI job
- 补齐 6 个 FE 有、BE 缺的 climate descriptors
- `LayerSidebar` 二级 pills 动态去重；placeholder 非 development 过滤
- SF restore 读 descriptor `workflow_id`，禁止写死 seed id
- `BACKEND_MAP_DEFAULT_*` + FE `map-defaults` 水合；Bbox 追加机构 AOI
- `source_uri_map.example.json` 机构模板说明

## 批 3 — 白标与设置（完成）

- `VITE_BRAND_*` / `VITE_ORG_LABEL`
- `VITE_SETTINGS_TABS` 控制设置 Tab
- 交付清单文档化 demo/stub 生产禁令

## 未纳入（按计划）

- Redis `requirepass`、多租户/SSO、合并 launch `.data` 与 runtime 为单物理目录
