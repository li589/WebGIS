# 数据集与图层重命名 — 调研分析与执行方案

> 调研阶段交付物（**仅分析与方案，未执行任何代码修改**）。
> 输入需求文件：`Docs/导师修改意见-命名.docx`（四层命名法）、`Docs/《星地数据融合…》结题验收材料-早期初稿.docx`（当前实际图层）。
> 调研日期：2026-08-10。调研方式：Deep Research 流程适配为代码库内部调查（提取 docx → 定位真源定义 → 全仓枚举引用 → 映射与爆炸半径评估）。

---

## 0. 一句话结论

当前 6 个土壤水分相关图层 ID 混用了「数据来源 / 变量 / 算法 / 角色」四个维度，与导师意见一致。推荐按**四层命名法** `{role}-{source}-{variable}-{period}-{method}` 统一改名。**改名不是只改一个字符串**——同一个物理量在仓库里有 **3 个必须一致的标识符**（后端 `layer_descriptors.json` 的 `layer_id`、前端 `catalog.ts` 的 `catalogId`、`overlay_registry.py` 的 `OverlaySpec.layer_id`）外加 **source_uri_map 的 key** 和 **workflow 的 `linked_layer_id`**。此外还存在一组**未被导师意见覆盖、但同样需要决策的 `omega-*` 运行时图层**和一组**仅在报告里出现、代码里尚未实现**的文档 ID。以下给出完整映射提案、爆炸半径、执行顺序与待确认决策点。

---

## 1. 命名规范（四层命名法）要点

来自 `导师修改意见-命名.docx` §2–§5，作为本次改名的唯一规范真源：

- **格式**：`{role}-{source}-{variable}-{period}-{method}`，英文小写、连字符连接，**禁用希腊字母 / 中文 / 空格**；`role` 可省略但正式管理建议保留。
- **字段允许值**：
  - `role`：`prod`(正式产品) / `ref`(参考产品) / `obs`(观测) / `demo`(演示样例) / `method`(方法展示)
  - `source`：`fy` / `smap` / `fy-smap` / `station`
  - `variable`：`sm` / `vod` / `omega` / `et` / `di` / `drought-class`
  - `period`：`202512` / `201504-202512` / `doy` / `latest`
  - `method`：`dynamic-omega` / `ddca` / `l3` / `fusion`
- **显示名称格式**（中文）：`【来源】+【变量中文名】+【时间范围】+【角色/方案说明】`。
- **角色分类表**（导师建议，作为 `prod/ref/obs/demo/method` 取值依据）：

| 建议图层ID | 建议显示名称 | 角色 | 核心验收 |
|---|---|---|---|
| prod-fy-sm-202512-dynamic-omega | FY土壤水分产品（2025年12月，dynamic ω方案） | 正式/样例 | 是 |
| prod-smap-sm-202512-dynamic-omega | SMAP土壤水分产品（2025年12月，dynamic ω方案） | 正式/方法 | 可选 |
| ref-smap-sm-202512-l3 | SMAP官方土壤水分参考产品（2025年12月） | 参考 | 否 |
| ref-ddca-sm-2015-2025 | DDCA双通道土壤水分参考产品 | 参考/算法对照 | 否 |
| method-fy-omega-doy-dynamic | FY dynamic ω多年平均产品 | 方法展示 | 否/辅助 |
| method-smap-omega-static | SMAP静态ω参考参数 | 方法对照 | 否/辅助 |
| obs-station-sm-daily | 站点土壤水分观测 | 验证数据 | 否 |
| demo-sm-latest | 土壤水分演示图层 | 演示样例 | 否 |

---

## 2. 当前命名混乱盘点（实地核对结果）

代码里实际存在的土壤水分相关图层（真源：`layer_descriptors.json` + `overlay_registry.py` + `catalog.ts`）：

| 当前 layer_id | 当前 display_name | 当前 dataset_key | 语义 | 现状问题 |
|---|---|---|---|---|
| `smap-sm-ts` | SMAP土壤湿度时序（2025-12） | `smap_sm_ts_dec2025` | SMAP L3 参考产品（时序样例） | 结题材料称 2025-12，但 `overlay_registry` 注释写 2023-01 采样；period 不一致 |
| `sm-dec2025` | SMAP土壤湿度融合（2025-12） | `sm_multisource_dec2025` | 融合 SMAP/FY-3D/站点（本项目核心产出 / dynamic-ω） | 结题描述它是「SMAP/FY/站点融合」，导师表把它归为「SMAP L 波段 dynamic-ω 方案」——融合 vs 单源语义冲突 |
| `fy-mwri` | FY-3 MWRI 亮温 | `fy_mwri` | **FY 原始亮温（输入，非产品）** | 导师表里没有「亮温/输入」层；若要对齐需把它改成 FY 土壤水分**产品**层，但当前它是原始输入 |
| `soil-ddca` | 土壤生态DDCA（双通道反演） | `soil_moisture_ddca` | DDCA 双通道参考（2015–2025） | 较清晰，可对应 `ref-ddca-sm-2015-2025` |
| `station-soil` | 站点土壤湿度 | `ismn_casmos` | ISMN/CASMOS 观测 | 较清晰，可对应 `obs-station-sm-daily` |
| `lab-output` | 科研模型模拟结果 | `lab_model_runs` | SMAP/ω 交叉分析模型输出（2023-01） | 导师表无直接对应项；需决策归为 demo 或 method |

**额外发现的命名碎片（导师意见未覆盖，但需要决策）**：

1. **`omega-*` 运行时图层**（代码里真实存在，但不在静态 catalog/seed 中）：
   - `omega-avg-daily`、`omega-sf-fenkuai`、`omega-block` —— 由工作流运行期动态注册（算法产出叠加层），被 `workflow_seeds/*.json` 的 `linked_layer_id`、前端 `overlay-symbology.ts`、`Tools/*.py` 引用。
   - 结题材料 §2.1 把它们称作 `omega-output` / `omega-fy-output`（SMAP/FY 植被参数多年均值，doy 组织），二者**名字对不上**。
2. **仅在报告里、代码未实现的文档 ID**：`vod-dec2025`（SMAP 植被光学厚度 2025-12）、`omega-dec2025`（SMAP 植被单次散射反照率 2025-12）。当前代码只注册了 SM 变量（`sm-dec2025`，`source_variable="SM"`），VOD/ω 未作为独立图层接入。
3. **`source_uri_map.example.json` 里的遗留别名 `smap-soil`**：key 为 `smap-soil`，但当前任何图层 ID 都不是它（已分裂为 `smap-sm-ts`/`sm-dec2025`），属于死别名，需清理或对齐。

---

## 3. 重命名映射提案（current → recommended）

### 3.1 主集：6 个已实现的土壤水分图层（建议采纳）

| 当前 layer_id | 建议 layer_id | 建议 display_name | 角色 | 对应导师表 | 备注 / 决策点 |
|---|---|---|---|---|---|
| `smap-sm-ts` | `ref-smap-sm-202512-l3` | SMAP官方土壤水分参考产品（2025年12月） | ref | ref-smap-sm-202512-l3 | period 用 `202512`；实际采样期若是 2023-01 需同步校正数据或改 period |
| `sm-dec2025` | `prod-smap-sm-202512-dynamic-omega` | SMAP土壤水分产品（2025年12月，dynamic ω方案） | prod | prod-smap-sm-202512-dynamic-omega | 结题描述其为「SMAP/FY/站点融合」，导师表归为 SMAP L 波段 dynamic-ω。**是否要在 ID/名称里体现「融合」？** 见决策点 D2 |
| `fy-mwri` | `prod-fy-sm-202512-dynamic-omega`（若改为 FY 产品层）或保留 `fy-mwri`（若仅作输入） | FY土壤水分产品（2025年12月，dynamic ω方案） | prod | prod-fy-sm-202512-dynamic-omega | **关键决策 D1**：当前 `fy-mwri` 是原始亮温输入，导师表期望的是 FY 土壤水分产品。二选一：① 把 `fy-mwri` 改名并对齐为 FY 产品层（需同时改其数据与展示语义）；② 保留 `fy-mwri` 作输入层，另**新增** `prod-fy-sm-202512-dynamic-omega` 产品层 |
| `soil-ddca` | `ref-ddca-sm-201504-202512` | DDCA双通道土壤水分参考产品 | ref | ref-ddca-sm-2015-2025 | period 用 `201504-202512`（连字符格式，对齐导师表示例） |
| `station-soil` | `obs-station-sm-daily` | 站点土壤水分观测 | obs | obs-station-sm-daily | 清晰 |
| `lab-output` | `demo-sm-latest`（演示样例）或 `method-smap-omega-202301`（方法展示） | 土壤水分演示图层 / SMAP-ω交叉分析方法产品 | demo/method | demo-sm-latest | **决策 D3**：导师表无对应项；lab-output 是模型输出样品，归 demo 还是 method 需定 |

### 3.2 数据集 dataset_key（用户明确说「数据集和图层名」，建议一并改）

`dataset_key` 仅在 `layer_descriptors.json` + 后端 API 契约字段（`api_contracts.py:68`、`api-contracts.ts:4471`）出现，**无运行时 join 逻辑**（工作流里的 `dataset_key` 是另一套命名空间，不冲突）。因此改名低风险：

| 当前 dataset_key | 建议 | 绑定图层 |
|---|---|---|
| `smap_sm_ts_dec2025` | `ref-smap-sm-202512-l3` | smap-sm-ts |
| `sm_multisource_dec2025` | `prod-smap-sm-202512-dynamic-omega` | sm-dec2025 |
| `fy_mwri` | `prod-fy-sm-202512-dynamic-omega`（同 D1）或保留 | fy-mwri |
| `soil_moisture_ddca` | `ref-ddca-sm-201504-202512` | soil-ddca |
| `ismn_casmos` | `obs-station-sm-daily` | station-soil |
| `lab_model_runs` | `demo-sm-latest` / `method-smap-omega-202301` | lab-output |

> 注：`dataset_key` 当前为 snake_case；若改连字符形式需确认前端/契约消费者未对 snake 做假设（已查无运行时 join，基本安全）。如求稳可不改 dataset_key，只改 layer_id/display_name。

### 3.3 次集：omega-* 运行时层（决策是否纳入本期）

| 当前 ID（运行时） | 报告里的名字 | 建议（如需统一） | 引用位置 |
|---|---|---|---|
| `omega-avg-daily` | `omega-output`（SMAP 多年均值） | `method-smap-omega-doy-dynamic`？ | workflow_seeds（7 个）、overlay-symbology.ts、Tools/* |
| `omega-sf-fenkuai` | `omega-fy-output`（FY 块反演） | `method-fy-omega-...`？ | workflow_seeds（2 个）、overlay-symbology.ts、Tools/* |
| `omega-block` | （中间层） | 建议保持内部名 | workflow_seeds、Tools/* |

---

## 4. 影响面 / 爆炸半径（逐标识符枚举）

### A. 真源 / 配置（改名必改，且必须保持三者一致）
| 文件 | 涉及字段 | 命中 ID |
|---|---|---|
| `Code/backend/app/catalog_seeds/layer_descriptors.json` | `layer_id` + `display_name`（+可选 `dataset_key`） | 6 条全中 |
| `Code/frontend/src/stores/layers/catalog.ts` | `catalogId` + `name` + `SOURCE_*\[id\]` | 6 条全中 |
| `Code/backend/app/services/overlay_registry.py` | `OverlaySpec(layer_id=...)`（**仅 4 条硬编码**：`lab-output`、`smap-sm-ts`、`soil-ddca`、`sm-dec2025`） | `fy-mwri`/`station-soil` 不在本文件（数据驱动，见下） |
| `Code/backend/source_uri_map.example.json` | **JSON key**（`fy-mwri`、`station-soil`、`lab-output`；遗留别名 `smap-soil`） | 3 + 1 |
| `Code/backend/workflow_seeds/system/smap_soil_moisture_local.json` | `linked_layer_id: "smap-sm-ts"` | smap-sm-ts |
| `Code/backend/workflow_seeds/system/open_data_nsidc_smap_sample.json` | `linked_layer_id: "smap-sm-ts"` | smap-sm-ts |

> **核对结论**：`fy-mwri` / `station-soil` 在后端 Python 中**无硬编码注册**（全仓仅出现于 seed + source_uri_map）。它们由数据导入/seed→overlay 同步动态注册，故改名只需动 seed + catalog + source_uri_map，无需找隐藏注册点。

### B. omega-* 运行时层（若纳入）
- `Code/backend/workflow_seeds/system/`：`omega_sf_fenkuai_*.json`(2)、`omega_block_*.json`(1)、`omega_avg_daily_*.json`(6) 的 `linked_layer_id`
- `Code/frontend/src/stores/overlay-symbology.ts` + `Test/frontend/stores/overlay-symbology.test.ts`
- `Tools/`：`verify_point_query.py`、`verify_overlays_api.py`、`verify_layers_api.py`、`verify_bounds.py`、`export_overlay_assets.py`、`audit_overlay_assets.py`、`smoke_system_workflows.py`、`run_omega_sf_strip_timing.py`

### C. 测试（字面量引用，须同步改，否则失败）
- `Test/backend/test_workflow_request_resolver.py`
- `Test/backend/test_provider_frontend_compat.py`
- `Test/backend/test_layer_remote_uris.py`
- `Test/backend/test_interaction_hub.py`
- `Test/backend/test_dual_pool_capacity.py`
- `Test/tools/test_data_production_e2e.py`

### D. 工具脚本（辅助验证，建议同步改以保持可用）
- `Tools/verify_point_query.py`、`verify_overlays_api.py`、`verify_layers_api.py`、`verify_bounds.py`、`export_overlay_assets.py`、`audit_overlay_assets.py`

### E. 文档（一致性，非运行时；改不改不影响功能）
- `Code/docs/真实数据e2e门槛.md`
- `Code/docs/代码事实同步文档-2026-07-16.md`、`代码事实同步文档-2026-07-06.md`
- `deliverables/gstack/pre-launch-check-cgda-2026-08-04.md`

### F. 生成物（**勿手改**）
- `Code/frontend/dist/assets/layers-*.js`：构建产物，改名后用 `cd Code/frontend && npm run build` 重建
- `Test/reports/*.json|*.log|*.md`：gitignored 的历史证据快照，勿手改（重跑测试会刷新）

---

## 5. 执行方法论（顺序 + 命令 + 校验）

> 遵循仓库「改 X 则跑 Y」约定（见 AGENTS.md）。所有命令从**仓库根**用 `Env/Python312/python.exe` 执行。

**Phase 0 — 冻结决策**：先与用户确认第 6 节的 D1–D4 决策点（尤其是 `fy-mwri` 语义、是否纳入 `omega-*`）。

**Phase 1 — 后端真源**：
1. 改 `catalog_secriptors.json`：`layer_id` + `display_name`（+ 可选 `dataset_key`）。
2. 改 `overlay_registry.py`：4 条硬编码 `layer_id`。
3. 改 `workflow_seeds/system/*.json`：2 处 `linked_layer_id: smap-sm-ts`。
4. 改 `source_uri_map.example.json`：key + 清理 `smap-soil` 别名。
5. 校验：`Env/Python312/python.exe -m pytest Test/backend/test_layer_remote_uris.py Test/backend/test_provider_frontend_compat.py Test/backend/test_workflow_request_resolver.py Test/backend/test_interaction_hub.py Test/backend/test_dual_pool_capacity.py -q`

**Phase 2 — 前端真源**：
6. 改 `catalog.ts`：`catalogId` + `name` + `SOURCE_*\[id\]`（注意文件顶部注释要求「category id 必须与后端 `layer_catalog.py` 的 `category=` 一致」）。
7. 若改 `omega-*`，同步 `overlay-symbology.ts`。
8. 校验：`cd Code/frontend && npm run test -- layers catalog`（及 `overlay-symbology`）。
9. 重建产物：`cd Code/frontend && npm run build`（刷新 `dist/assets/layers-*.js`）。

**Phase 3 — 工具/测试/文档**：
10. 同步改 `Test/tools/test_data_production_e2e.py` 与 `Tools/*.py` 字面量。
11. 全量回归：
    - 后端：`Env/Python312/python.exe -m pytest Test/backend -q`
    - 算法：`Env/Python312/python.exe -m pytest Test/algorithms -q`
    - 前端：`cd Code/frontend && npm run test`
12. 文档一致性更新（E 类）。

**Phase 4 — 运行时验收**：
13. `Env/Python312/python.exe launch.py restart backend`（data root 类改动须重启进程组）。
14. 抽查：`/layers`、`/overlays` 返回的 ID 已更新；`/overlay-preview/{new_id}`、`/overlay-value/{new_id}`、`/unified-tiles/{new_id}/{z}/{x}/{y}` 正常；前端图层栏显示新名称。

---

## 6. 待确认决策点（执行前必须定）

- **D1（最关键）`fy-mwri` 语义**：它是「FY 原始亮温输入」还是改为「FY 土壤水分产品」？决定是原地改名还是新增产品层。
- **D2** `sm-dec2025` 的「融合」语义：ID/名称是否要体现 SMAP/FY/站点融合（与导师表「SMAP L 波段 dynamic-ω 方案」措辞统一）。
- **D3** `lab-output` 归类：demo（演示样例）还是 method（方法展示）？对应 `demo-sm-latest` 或 `method-*`。
- **D4** 范围：本期只改 6 个已实现图层，还是**一并**纳入 `omega-*` 运行时层 + 决定是否补实现文档里的 `vod-dec2025`/`omega-dec2025`？
- **D5** `dataset_key` 是否随 layer_id 一起改（连字符化），还是保持 snake_case 不动？
- **D6** `source_uri_map.example.json` 的遗留别名 `smap-soil`：删除还是对齐到新 ID？

---

## 7. 风险与注意

1. **三者必须同步**：`layer_descriptors.json` ↔ `catalog.ts` ↔ `overlay_registry.py` 任一不一致，前端会拿到旧 ID 或 `/overlays` 404。提交前用 grep 全仓确认无残留旧 ID。
2. **`source_uri_map` 是运行时下载匹配键**：`download_orchestrator.py` 按 key 解析下载 URI；key 不改会导致该图层下载功能失效（不只是显示问题）。
3. **`linked_layer_id` 断链**：workflow 与图层的关联靠它；不改会导致工作流编辑器里「关联图层」丢失。
4. **测试/工具字面量**：C、D 类文件里旧 ID 是硬编码字符串，不改会测试失败或验证脚本误报。
5. **构建产物**：`dist/assets/layers-*.js` 是旧 bundle，必须 `npm run build` 重建，否则线上仍显示旧 ID。
6. **pre-commit 钩子**：提交涉及大文件/多文件时注意（见 MEMORY.md）：清 `ACC_PRODUCT_CONFIG_V3` 等 3 个 env 再提交；frontend prettier 钩子校验全量前端文件。
7. **period 数据真实性**：`smap-sm-ts` 的 period 在结题材料(2025-12)与 registry 注释(2023-01) 不一致，改名时应一并校正数据源或 period 值，避免「名实不符」。

---

## 8. 附：调研证据索引

- 需求真源：`Docs/导师修改意见-命名.docx`（四层命名法 + 角色分类表）、`Docs/《星地数据融合…》结题验收材料-早期初稿.docx`（§3.2 土壤水分产品测试表、§2.1 操作手册、§4 文件命名）。
- 改名真源（3 处必须一致）：`Code/backend/app/catalog_seeds/layer_descriptors.json`、`Code/frontend/src/stores/layers/catalog.ts`、`Code/backend/app/services/overlay_registry.py`。
- 交叉引用：`Code/backend/source_uri_map.example.json`（key）、`Code/backend/workflow_seeds/system/*.json`（`linked_layer_id`）、`Code/backend/app/services/download_orchestrator.py`（uri_map 消费）。
- 全仓引用枚举见第 4 节 A–F。
