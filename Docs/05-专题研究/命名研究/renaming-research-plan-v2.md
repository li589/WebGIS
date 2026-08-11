# 数据集与图层重命名方案 v2（决策回执 + 产品族矩阵 + 执行清单）

> v1 为纯调研盘点（2026-08-10）；v2 在用户对 D1–D6 逐项拍板后更新，新增**产品族结构模型**、**lab-output 删除专项**、**omega-* 运行时层纳入**。本方案仍为分析与执行计划（未改代码，待用户确认 TBD 后落地）。

---

## 0. 决策回执（用户拍板 → 落实为条款）

| # | 用户决定 | 落实 |
|---|---|---|
| D1 | FY=风云卫星；`fy-mwri` 暂按**风云原始亮温**处理，名称待回头确认 | 新 ID 体现「FY 亮温输入」语义：`ref-fy-tb-202512-mwri`，全方案打 **TBD-1** 标记 |
| D2 | SM 是多源多线（SMAP 源 / FY 源 × avg 平均 / dynamic 动态 raw），ID 应体现 SMAP/FY/站点融合 | 新增 §1 产品族矩阵；`sm-dec2025` → `prod-fy-smap-sm-202512-fusion`；omega-* 按算法区分 avg/dynamic |
| D3 | `lab-output` 若无对应数据集或完善方法应**删去**，交付品不得出现令人疑惑的名称 | §3 删除专项：数据存在但为早期样例且与 ω 家族重叠 → **删除图层**，磁盘数据保留 |
| D4 | **一并**纳入 omega-* 运行时层；`vod-dec2025`/`omega-dec2025` 补实现定为后续任务 | §2.2 omega-* 改名映射；§7 TBD-3 拆分与否 |
| D5 | 数据集 ≠ 图层，**dataset_key 与 layer_id 无关** | §2.3 dataset_key 保持独立命名体系，**本轮不改** |
| D6 | `smap-soil` 删除与否看有无算法/数据保证可用 | 全仓核查仅 example 模板出现、无数据/算法支撑 → **删除**（§2.4） |

---

## 1. 产品族结构模型（多源 × 算法版本）——本方案核心新增

结合代码事实（`workflow_seeds`：`omega_avg_daily_*` 为 avg 线、`omega_sf_fenkuai_*` 为 dynamic 线、`omega_block_*` 为前置中间层），SM/ω/VOD 产品族真实结构为：

| 源 | 算法版本 | 产出变量 | 现状 | 备注 |
|---|---|---|---|---|
| SMAP | avg（ω 固定平均，sf=STATIC） | SM / ω / VOD | 工作流已实现 | `omega_avg_daily_smap_single` 等 |
| SMAP | dynamic（SF 逐日倒推，sf=INVERTED_DAILY） | SM / ω / VOD | 工作流已实现 | `omega_sf_fenkuai_smap_single` |
| FY | avg | SM / ω / VOD | 工作流已实现 | `omega_avg_daily_fy_single` |
| FY | dynamic | SM / ω / VOD | 工作流已实现 | `omega_sf_fenkuai_fy_single` |
| SMAP+FY+站点 | **fusion（融合正式产品）** | SM | 展示层已注册 = `sm-dec2025` | 结题材料 §3.2「融合SMAP/FY-3D/站点观测」 |
| — | block（8 天块反演前置） | ω | 内部中间层 | `omega_block_*`，建议保留内部名 |

**关键结论**：算法层已有完整的「源 × 版本」矩阵，但**展示层（静态 catalog）只注册了 1 条 SM 融合线**（`sm-dec2025`）+ 早期样例（`lab-output`）。本次重命名只针对**已存在实体**；矩阵其余行的展示图层补实现 = 后续任务（对齐用户 D4「vod/omega 补实现定为之后任务」）。

---

## 2. 重命名映射总表（v2）

### 2.1 静态 catalog 图层（6 → 5 个）

| 当前 layer_id | 新 layer_id | 新 display_name | role | method 依据 |
|---|---|---|---|---|
| `smap-sm-ts` | `ref-smap-sm-202512-l3` | SMAP官方土壤水分参考产品（2025年12月） | ref | 导师表 ref-smap-sm-202512-l3 |
| `sm-dec2025` | `prod-fy-smap-sm-202512-fusion` | SMAP/FY/站点融合土壤水分产品（2025年12月） | prod | 体现多源融合（D2）；source=fy-smap 双星、method=fusion |
| `fy-mwri` | `ref-fy-tb-202512-mwri` | FY-3 MWRI 原始亮温（2025年12月）**【TBD-1】** | ref | FY=风云卫星；variable 扩展 `tb`（亮温，输入类，导师允许值示例可扩展） |
| `soil-ddca` | `ref-ddca-sm-201504-202512` | DDCA双通道土壤水分参考产品（2015年4月—2025年12月） | ref | 导师表 ref-ddca-sm-2015-2025；period 连字符格式 |
| `station-soil` | `obs-station-sm-daily` | 站点土壤水分观测 | obs | 导师表 obs-station-sm-daily |
| `lab-output` | **删除** | — | — | §3 删除专项 |

> 融合层 source 值说明：导师 source 允许值为 `fy/smap/fy-smap/station`，`fy-smap` 即表达 SMAP+FY 双星；站点参与以显示名与说明体现。若要求站点也进 ID（`fy-smap-station`），列为 **TBD-4**。

### 2.2 omega-* 运行时层（纳入，D4）

| 当前 ID | 新 ID | 新 display_name | 引用面（改后同步） |
|---|---|---|---|
| `omega-avg-daily` | `method-omega-avg-doy` | dynamic ω 多年平均产品（doy，SMAP/FY） | 9 个工作流 seed 的 `linked_layer_id`、overlay-symbology.ts:140 注释、Tools/*、前端测试 |
| `omega-sf-fenkuai` | `method-omega-dynamic-doy` | dynamic ω 动态反演产品（doy，SMAP/FY） | 2 个工作流 seed 的 `linked_layer_id` + **output/map_layer 节点 `layer_id`**（`omega_sf_fenkuai_smap_single.json` node 7 等）、其余同上 |
| `omega-block` | `omega-block`（**保留内部名**） | 8天块反演中间层（内部） | 不改名；source_uri_map key 保留 |

> 说明：本期不按源拆分（SMAP/FY 共用一个运行时 ID），源信息体现在显示名与工作流变体；如需拆分（`method-smap-omega-doy-avg` / `method-fy-omega-doy-avg` 等 4 个），列 **TBD-3**。

### 2.3 dataset_key（D5：保持独立，本轮不改）

- `dataset_key` 是**数据集标识符**（对应物理数据），`layer_id` 是**图层标识符**（对应展示/查询入口），二者解耦，符合 D5。
- 现状（`layer_descriptors.json`，仅此处 + API 契约字段，无运行时 join）：`smap_sm_ts_dec2025`、`sm_multisource_dec2025`、`fy_mwri`、`ismn_casmos`、`lab_model_runs`、`soil_moisture_ddca`。
- **本轮不动**；若后续要规范化数据集命名（如 `fy_mwri` → `fy3_mwri_l1c`），单独立项（不依赖图层改名）。
- 注意区分：工作流 seed 节点里的 `dataset_key`（`SMAP_L3`、`smap_folder` 等）是**工作流参数命名空间**，与图层 dataset_key 无关，也不动。

### 2.4 source_uri_map.example.json（key 对齐 + 清理）

| key | 处理 | 理由 |
|---|---|---|
| `fy-mwri` | → `ref-fy-tb-202512-mwri` | 对齐新图层 ID（运行时下载匹配键） |
| `station-soil` | → `obs-station-sm-daily` | 同上 |
| `lab-output` | **删除** | 随图层删除 |
| `smap-soil` | **删除** | **D6 确认**：全仓仅 example 模板出现，无算法/数据支撑（死别名） |
| `omega-block` | 保留 | 内部名保留 |

> 注意：`.env` 已配置 `BACKEND_DATA_ROOT=I:\Geograph_DataSet`，生产 `source_uri_map` 以 `BACKEND_DOWNLOAD_SOURCE_URI_MAP` 指向实际文件（示例见 `DATA_SETUP_GUIDE.txt`）。改 example 后，**机构实际部署文件需同步**（无法在仓库内核对，标注为部署待办）。

---

## 3. lab-output 删除专项（D3）

### 3.1 判定依据（按用户条件「无对应数据集或完善方法则删」）

| 核查项 | 结果 |
|---|---|
| 数据集是否真实存在？ | **存在**：`I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion\smap_sm_overlay.png`(65KB) + `smap_sm_overlay_bounds.json` + `smap_sm_14day_mean.tif` + `Inversion_Results\smap_avg\doy_*.mat`(3.4MB×N) |
| 方法是否完善？ | **否**：内容为「SMAP/ω 交叉分析 14 天均值」早期探索样例（stage 流水线产物），与 ω 平均家族（omega-avg-daily）功能重叠，非验收核心 |
| 名称是否合规？ | **否**：`lab-output`（实验室输出）语义含糊，不符合「交付品不得出现令人疑惑的名称」 |

**结论：删除图层**（磁盘数据文件保留不删，仅取消注册与目录展示）。

### 3.2 删除清单（逐处）

| 文件 | 操作 |
|---|---|
| `Code/backend/app/catalog_seeds/layer_descriptors.json`（约 L649 条目） | 删 `lab-output` 条目（`layer_id`/`dataset_key=lab_model_runs`/`display_name`/`description`） |
| `Code/frontend/src/stores/layers/catalog.ts` | 删 `catalogId:'lab-output'` 条目 + `SOURCE_LAB` 常量 |
| `Code/backend/app/services/overlay_registry.py`（L625-641） | 删 `register_overlay(OverlaySpec(layer_id="lab-output", ...))` |
| `Code/backend/source_uri_map.example.json`（L23） | 删 `"lab-output"` key |
| `Test/backend/test_provider_frontend_compat.py`、`test_layer_remote_uris.py` 等 | 删/改引用 lab-output 的用例（执行时 grep 定位） |
| `Tools/verify_*.py`（若引用） | 删/改 |
| 结题材料 §3.2 表格「lab-output」行、操作手册 §2.1「SMAP/ω 交叉分析」句 | 文档层同步（docx，交付时更新） |
| 磁盘 `smap_sm_overlay.png` 等 | **保留**（不删数据） |

---

## 4. 逐文件影响面清单（v2 合并）

### 改名必改（真源三处 + 交叉引用）
| 文件 | 改动 |
|---|---|
| `Code/backend/app/catalog_seeds/layer_descriptors.json` | 5 条 `layer_id`+`display_name` 改名；删 lab-output |
| `Code/frontend/src/stores/layers/catalog.ts` | 5 条 `catalogId`+`name`+`SOURCE_*[id]` 改名；删 lab-output |
| `Code/backend/app/services/overlay_registry.py` | 硬编码 `layer_id`：`smap-sm-ts`/`sm-dec2025`/`soil-ddca` 改、`lab-output` 删（`fy-mwri`/`station-soil` 本文件无注册，无需动） |
| `Code/backend/source_uri_map.example.json` | key 对齐 + 删 `lab-output`/`smap-soil` |
| `Code/backend/workflow_seeds/system/smap_soil_moisture_local.json` + `open_data_nsidc_smap_sample.json` | `linked_layer_id: "smap-sm-ts"` → `ref-smap-sm-202512-l3` |
| omega-* 相关 9 个 workflow seed | `linked_layer_id`：`omega-avg-daily`→`method-omega-avg-doy`；`omega-sf-fenkuai`→`method-omega-dynamic-doy`；`omega_sf_fenkuai_*.json` 的 **output/map_layer 节点 `layer_id`** 同步 |

### 测试（字面量引用）
- `Test/backend/`：`test_workflow_request_resolver.py`、`test_provider_frontend_compat.py`、`test_layer_remote_uris.py`、`test_interaction_hub.py`、`test_dual_pool_capacity.py`
- `Test/tools/test_data_production_e2e.py`
- `Test/frontend/`：`overlay-symbology.test.ts`、`stores/layers/workspace-persist.test.ts`、`stores/layers/restore-workflow-bridge.test.ts`、`components/map/workflow-overlay-render-hint.test.ts`（omega-* 相关）

### 工具脚本
- `Tools/verify_point_query.py`、`verify_overlays_api.py`、`verify_layers_api.py`、`verify_bounds.py`、`export_overlay_assets.py`、`audit_overlay_assets.py`（+ `smoke_system_workflows.py`、`run_omega_sf_strip_timing.py` 涉及 omega-*）

### 文档（一致性，非运行时）
- `Code/docs/真实数据e2e门槛.md`、`代码事实同步文档-2026-07-16.md`、`-2026-07-06.md`
- `deliverables/gstack/pre-launch-check-cgda-2026-08-04.md`
- 结题材料 docx（§3.2 表 / 操作手册 §2.1）

### 生成物（勿手改）
- `Code/frontend/dist/assets/layers-*.js` → `npm run build` 重建
- `Test/reports/*` → gitignored 历史证据，勿手改

---

## 5. 执行顺序（Phase 0–5）+ 验证命令

> 仓库根执行，解释器 `Env/Python312/python.exe`。遵循 AGENTS.md「改 X 则跑 Y」。

**Phase 0 — TBD 确认**：D1（fy ID）、TBD-3（omega 拆分否）、TBD-4（站点进 ID 否）。

**Phase 1 — 后端真源**：
1. `layer_descriptors.json`（5 改名 + 删 lab-output）→ 2. `overlay_registry.py` → 3. `workflow_seeds`（2 处 smap-sm-ts + 9 处 omega）→ 4. `source_uri_map.example.json`
5. 校验：`Env/Python312/python.exe -m pytest Test/backend/test_layer_remote_uris.py Test/backend/test_provider_frontend_compat.py Test/backend/test_workflow_request_resolver.py Test/backend/test_interaction_hub.py Test/backend/test_dual_pool_capacity.py -q`

**Phase 2 — 前端真源**：
6. `catalog.ts`（5 改名 + 删 lab-output + 注意 category 与后端一致注释）→ 7. `overlay-symbology.ts` 注释（如拆 omega 则同步逻辑）
8. 校验：`cd Code/frontend && npm run test -- layers catalog overlay-symbology`
9. 重建：`cd Code/frontend && npm run build`

**Phase 3 — 测试/工具/文档**：
10. `Test/` + `Tools/` 字面量同步 → 11. 文档（E 类）→ 12. 全量回归：`pytest Test/backend` + `pytest Test/algorithms` + `npm run test`

**Phase 4 — 运行时验收**：
13. `Env/Python312/python.exe launch.py restart backend`（改数据根相关配置后必重启）
14. 抽查：`/layers`、`/overlays` 新 ID；`/overlay-preview/{new_id}`、`/overlay-value/{new_id}`、`/unified-tiles/{new_id}/{z}/{x}/{y}` 正常；前端图层栏新名称；工作流编辑器关联图层不丢

**Phase 5 — 提交**：
15. 前置清 env（`env -u ACC_PRODUCT_CONFIG_V3 CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX=`）后 `git commit`，类型用 `refactor:`（conventional-commits 钩子白名单）

---

## 6. 风险与注意

1. **三真源一致性**：`layer_descriptors` ↔ `catalog.ts` ↔ `overlay_registry` 必须同步，否则 `/overlays` 404 或前端旧 ID。提交前 `grep` 全仓确认无旧 ID 残留（排除 dist/reports）。
2. **source_uri_map 是运行时下载匹配键**：`download_orchestrator.py` 按 key 解析；key 漏改 → 该图层下载失效。
3. **`linked_layer_id` 断链**：工作流与图层关联靠它；漏改 → 工作流编辑器「关联图层」丢失、运行时图层归属错乱。
4. **omega-sf-fenkuai 的 output/map_layer 节点**：`layer_id` 硬编码在工作流 JSON 里（node 7），除 `linked_layer_id` 外需单独改这处。
5. **lab-output 删除**：磁盘数据保留、仅取消注册；若用户后续想要回来，数据仍在。
6. **构建产物**：`dist/assets/layers-*.js` 必须 `npm run build`，否则线上旧 ID。
7. **pre-commit 钩子**：frontend prettier 校验全量前端 glob；大提交注意 stash/restore 未暂存改动（见 MEMORY.md）。
8. **结题材料 docx 同步**：§3.2 产品测试表、操作手册 §2.1 出现旧 ID/名称，交付前须更新（文档层待办）。

---

## 7. 待确认标记（TBD）

- **TBD-1**：`fy-mwri` 新 ID `ref-fy-tb-202512-mwri` —— ①确认「FY=风云卫星」缩写即用 `fy`；②variable 扩展 `tb`（亮温）是否接受；③role 用 `ref`（参考输入）是否合适。确认后可去掉全方案的「待确认」标记。
- **TBD-2**：`sm-dec2025` 数据源当前为 `Soil_Moisture/SMAP_Soil_VOD_SM/{YYYYMMDD}.mat`（v7.3，OMEGA/SM/VOD 三变量）；结题材料称其为「融合 SMAP/FY-3D/站点」。改名时核对数据源是否确为融合产物目录，若否需同步校正数据源指向。
- **TBD-3**：omega-* 本期**不按源拆分**（SMAP/FY 共用一个运行时 ID）。如需拆分（`method-smap-omega-doy-avg` / `method-fy-omega-doy-avg` / `method-smap-omega-doy-dynamic` / `method-fy-omega-doy-dynamic` 四线），工作量约 +9 个 seed、+4 个前端测试，可单独确认。
- **TBD-4**：融合层 ID 是否要求站点也进 ID（`prod-fy-smap-station-sm-202512-fusion`，source 扩展 `fy-smap-station`），还是按推荐 `prod-fy-smap-sm-202512-fusion` + 显示名体现站点。

---

## 8. 证据索引

- 需求真源：`Docs/导师修改意见-命名.docx`、`Docs/《星地数据融合…》结题验收材料-早期初稿.docx`
- 改名真源：`Code/backend/app/catalog_seeds/layer_descriptors.json`、`Code/frontend/src/stores/layers/catalog.ts`、`Code/backend/app/services/overlay_registry.py`
- 交叉引用：`Code/backend/source_uri_map.example.json`（仅 example，无实际部署文件）、`Code/backend/workflow_seeds/system/*.json`（`linked_layer_id` + `output/map_layer.layer_id`）、`Code/backend/app/services/download_orchestrator.py`（uri_map 消费）
- omega 语义：`omega_avg_daily_*`（avg 线，ω 固定 OMEGA_AVG/sf=STATIC）、`omega_sf_fenkuai_*`（dynamic 线，sf=INVERTED_DAILY）、`omega_block_*`（8 天块前置）
- 数据核查：`BACKEND_DATA_ROOT=I:\Geograph_DataSet`（`.env`）；`lab-output` 数据存在（`smap_sm_overlay.png`/`doy_017.mat`）；frontend 对 omega-* 仅 1 行注释（`overlay-symbology.ts:140`）
