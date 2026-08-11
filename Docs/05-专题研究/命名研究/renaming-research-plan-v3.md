# 数据集与图层重命名方案 v3（TBD 全清 + 下划线多条目规则，可执行版）

> v2→v3 变更：① 用户确认全部 TBD（fy ID 可用 / 融合产物确认 / omega 按源拆分 / 站点进融合层）；② 新增**下划线多条目规则**（多源、多变量字段内用 `_` 隔离）；③ TBD 清零，方案进入可执行状态。仍未改任何代码，等待确认后按 Phase 1 落地。

---

## 0. v3 变更清单

| 项 | v2 | v3 |
|---|---|---|
| 命名规则 | 四层法仅连字符 | 四层法字段间 `-` + **字段内多条目 `_`** |
| 融合层 `sm-dec2025` | `prod-fy-smap-sm-202512-fusion` | `prod-fy_smap_station-sm_vod_omega-202512-fusion` |
| `fy-mwri` | `ref-fy-tb-202512-mwri`（TBD-1） | 确认可用，去标记 |
| omega-* | 不拆分（2 个 ID） | **按源拆分 4 线** + GLDAS 归 SMAP 线 |
| 站点 | 显示名体现 | **进 ID**（`fy_smap_station`） |
| 待确认 | TBD-1~4 | 全部关闭 |

---

## 1. 命名规范 v3（四层法 + 下划线多条目规则）

**基础**：`{role}-{source}-{variable}-{period}-{method}`（字段间连字符 `-`，与导师意见一致）。

**新增规则（用户 2026-08-10 拍板）**：
- **字段内多条目用下划线 `_` 隔离**：多个数据集 / 源 / 传感器出现在同一字段时，如 `source=fy_smap_station`（SMAP+FY+站点三源）。
- **多输出变量同理**：一个图层含多个变量时 `variable=sm_vod_omega`（SM+VOD+OMEGA）。
- 单条目字段不受影响（维持连字符字段分隔）。
- 保留惯例：`period` 日期范围 `201504-202512` 保持连字符（是范围语义，非多条目）。

| 字段 | 允许值示例（v3） | 说明 |
|---|---|---|
| role | prod / ref / obs / demo / method | 不变 |
| source | fy / smap / fy_smap / fy_smap_station / station / fy_smap_station | **多源用 `_`** |
| variable | sm / vod / omega / sm_vod_omega / tb | **多变量用 `_`**；`tb` 为亮温输入类（FY 层） |
| period | 202512 / 201504-202512 / doy / daily | 不变 |
| method | avg / dynamic / dynamic-omega / ddca / l3 / fusion | 新增 avg/dynamic（区分平均/动态线） |

---

## 2. 产品族矩阵（v3 更新）

| 源 | 算法版本 | 产出变量 | 图层 ID（v3） | 现状 |
|---|---|---|---|---|
| SMAP | avg（ω 固定平均） | SM/ω/VOD | `method-smap-omega-doy-avg` | 工作流已实现 |
| SMAP | dynamic（SF 逐日倒推） | SM/ω/VOD | `method-smap-omega-doy-dynamic` | 工作流已实现 |
| FY | avg | SM/ω/VOD | `method-fy-omega-doy-avg` | 工作流已实现 |
| FY | dynamic | SM/ω/VOD | `method-fy-omega-doy-dynamic` | 工作流已实现 |
| SMAP+FY+站点 | **fusion（正式产品）** | **SM+VOD+ω** | `prod-fy_smap_station-sm_vod_omega-202512-fusion` | 展示层已注册（`sm-dec2025`，当前仅 SM 变量展示） |
| — | block（8 天块前置） | ω | `omega-block`（内部保留） | 中间层，不改名 |

> 融合层说明（TBD-2 确认）：mat 为融合产物，单文件含 OMEGA/SM/VOD 多变量（原 MATLAB 方法构建）。**当前展示层仅读 SM 变量**（`overlay_registry` 的 `source_variable="SM"`）；VOD/ω 的独立图层展示 = 后续补实现任务（用户 D4 已定）。数据路径可能变化或改从在线平台获取（工程配置层处理，`overlay_registry` 走 `_data_join`，不涉及本方案）。

---

## 3. 重命名映射总表（v3）

### 3.1 静态 catalog 图层（6 → 5 个）

| 当前 layer_id | 新 layer_id | 新 display_name | role |
|---|---|---|---|
| `smap-sm-ts` | `ref-smap-sm-202512-l3` | SMAP官方土壤水分参考产品（2025年12月） | ref |
| `sm-dec2025` | `prod-fy_smap_station-sm_vod_omega-202512-fusion` | SMAP/FY/站点融合土壤水分产品（2025年12月，SM/VOD/ω） | prod |
| `fy-mwri` | `ref-fy-tb-202512-mwri` | FY-3 MWRI 原始亮温（2025年12月） | ref |
| `soil-ddca` | `ref-ddca-sm-201504-202512` | DDCA双通道土壤水分参考产品（2015年4月—2025年12月） | ref |
| `station-soil` | `obs-station-sm-daily` | 站点土壤水分观测 | obs |
| `lab-output` | **删除** | — | — |

### 3.2 omega-* 运行时层（按源拆分 4 线）

| 当前 ID | 新 ID（SMAP 线） | 新 ID（FY 线） | 涉及的 workflow seed |
|---|---|---|---|
| `omega-avg-daily` | `method-smap-omega-doy-avg` | `method-fy-omega-doy-avg` | smap_single / smap_online / smap_dual / **gldas_online** → SMAP 线；fy_single → FY 线 |
| `omega-sf-fenkuai` | `method-smap-omega-doy-dynamic` | `method-fy-omega-doy-dynamic` | smap_single → SMAP；fy_single → FY |
| `omega-block` | `omega-block`（保留，内部中间层） | — | omega_block_smap_single（linked_layer_id 归 SMAP avg 线） |

显示名：`SMAP dynamic ω 多年平均产品（doy）` / `FY dynamic ω 多年平均产品（doy）` / `SMAP dynamic ω 动态反演产品（doy）` / `FY dynamic ω 动态反演产品（doy）`。

> **GLDAS 归属判定**：`omega_avg_daily_gldas_online` 是「SMAP TB 反演 + GLDAS 温度（DUAL 双温度方案）输入」变体，产物仍是 avg ω 线 → 归 `method-smap-omega-doy-avg`（不建独立 GLDAS 线；GLDAS 是温度输入非产品源）。

### 3.3 dataset_key（D5：独立，本轮不改）

同 v2：`dataset_key` 为数据集标识符，与 `layer_id` 解耦，本轮不动（`smap_sm_ts_dec2025`、`sm_multisource_dec2025`、`fy_mwri`、`ismn_casmos`、`lab_model_runs`、`soil_moisture_ddca` 现状保留；`lab_model_runs` 随 lab-output 图层删除而移除）。

### 3.4 source_uri_map.example.json

| key | 处理 |
|---|---|
| `fy-mwri` | → `ref-fy-tb-202512-mwri` |
| `station-soil` | → `obs-station-sm-daily` |
| `lab-output` | 删除 |
| `smap-soil` | 删除（死别名，D6） |
| `omega-block` | 保留（内部名） |
| `inversion-daily` / `block-inversion` 等 | 不在本次范围，不动 |

> 部署待办：`source_uri_map` 生产以 `BACKEND_DOWNLOAD_SOURCE_URI_MAP` 指向实际文件（本仓库仅 example），机构实际文件需同步改。

---

## 4. lab-output 删除专项（同 v2，§3）

判定结论不变：数据存在（`I:\...\smap_sm_overlay.png`/`doy_*.mat`）但为早期 14 天均值样例、与 ω 家族重叠、名称不合规 → **删除图层，磁盘数据保留**。删除清单（6 处代码/测试/工具 + 文档）同 v2 §3.2，含 `layer_descriptors.json`、`catalog.ts`（条目+SOURCE_LAB）、`overlay_registry.py`（L625-641 注册块）、`source_uri_map.example.json`、相关测试/工具、结题材料 §3.2 表行。

---

## 5. 逐文件影响面清单（v3）

### 改名必改（真源三处 + 交叉引用）
| 文件 | 改动 |
|---|---|
| `Code/backend/app/catalog_seeds/layer_descriptors.json` | 5 条改名（含融合层多源多变量 ID）+ 删 lab-output |
| `Code/frontend/src/stores/layers/catalog.ts` | 5 条 `catalogId`+`name`+`SOURCE_*[id]` 改名 + 删 lab-output（`SOURCE_SM_DEC2025` 的描述需更新为融合/多变量说明） |
| `Code/backend/app/services/overlay_registry.py` | `smap-sm-ts`/`sm-dec2025`/`soil-ddca` 3 条硬编码 `layer_id` 改名 + 删 lab-output 注册块；`sm-dec2025` 的注释（Phase 2 产品族）同步 |
| `Code/backend/source_uri_map.example.json` | 2 key 改名 + 删 2 key |
| `workflow_seeds/system/smap_soil_moisture_local.json`、`open_data_nsidc_smap_sample.json` | `linked_layer_id: "smap-sm-ts"` → `ref-smap-sm-202512-l3` |
| omega-* 9 个 seed | 见 §5.1 |

### 5.1 omega-* seed 拆分明细

| seed | 改动 |
|---|---|
| `omega_avg_daily_smap_single.json` / `smap_online` / `smap_dual` / `gldas_online` | `linked_layer_id` → `method-smap-omega-doy-avg` |
| `omega_avg_daily_fy_single.json` | `linked_layer_id` → `method-fy-omega-doy-avg` |
| `omega_sf_fenkuai_smap_single.json` | `linked_layer_id` + **output/map_layer 节点 `layer_id`** → `method-smap-omega-doy-dynamic` |
| `omega_sf_fenkuai_fy_single.json` | 同上 → `method-fy-omega-doy-dynamic` |
| `omega_block_smap_single.json` | `linked_layer_id` → `method-smap-omega-doy-avg`（D1 前置，服务 SMAP avg 线）；产出内部 `omega-block` 不变 |

### 测试 / 工具 / 文档 / 生成物
- 测试：`Test/backend/`（test_workflow_request_resolver / test_provider_frontend_compat / test_layer_remote_uris / test_interaction_hub / test_dual_pool_capacity）、`Test/tools/test_data_production_e2e.py`、`Test/frontend/`（overlay-symbology.test.ts、workspace-persist.test.ts、restore-workflow-bridge.test.ts、workflow-overlay-render-hint.test.ts）
- 工具：`Tools/verify_*`（6 个）+ `smoke_system_workflows.py` + `run_omega_sf_strip_timing.py`
- 文档：`Code/docs/`（真实数据e2e门槛、代码事实同步文档×2）、`deliverables/gstack/pre-launch-check-cgda-2026-08-04.md`、结题材料 docx
- 生成物：`dist/assets/layers-*.js`（`npm run build` 重建）、`Test/reports/*`（gitignored 勿手改）

---

## 6. 执行顺序（Phase 1–5，TBD 已全清）

> 仓库根执行；解释器 `Env/Python312/python.exe`。

**Phase 1 — 后端真源**：`layer_descriptors.json` → `overlay_registry.py` → 11 个 workflow seed → `source_uri_map.example.json`
→ 校验：`Env/Python312/python.exe -m pytest Test/backend/test_layer_remote_uris.py Test/backend/test_provider_frontend_compat.py Test/backend/test_workflow_request_resolver.py Test/backend/test_interaction_hub.py Test/backend/test_dual_pool_capacity.py -q`

**Phase 2 — 前端真源**：`catalog.ts` → `overlay-symbology.ts:140` 注释（omega-* 新 ID 示例）
→ 校验：`cd Code/frontend && npm run test -- layers catalog overlay-symbology` → `npm run build`

**Phase 3 — 测试/工具/文档**：`Test/`+`Tools/` 字面量 → 文档 → 全量回归：`pytest Test/backend` + `pytest Test/algorithms` + `npm run test`

**Phase 4 — 运行时验收**：`launch.py restart backend` → 抽查 `/layers`、`/overlays`、`/overlay-preview/{new_id}`、`/overlay-value/{new_id}`、`/unified-tiles/{new_id}/{z}/{x}/{y}`、工作流关联图层

**Phase 5 — 提交**：前置清 env（`env -u ACC_PRODUCT_CONFIG_V3 CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX=`）→ `git commit`（`refactor:`，conventional-commits 钩子）

---

## 7. 风险与注意（v3 补充）

1. **三真源一致性** + 提交前全仓 grep 无旧 ID 残留（排除 dist/reports）——同 v2。
2. **融合层 ID 与展示层变量差**：ID 声明 `sm_vod_omega` 三变量，但展示层当前只读 SM。若验收按 ID 逐字核对，需在 layer_descriptors `description` 注明「当前展示 SM，VOD/ω 图层补实现中」，避免名实不符质疑。
3. **omega 拆分后 9 个 seed 的 `linked_layer_id` 逐一对应**，勿批量替换（smap/fy 线不同 ID）；`omega_sf_fenkuai_*.json` 除 `linked_layer_id` 外还有 output 节点 `layer_id` 两处。
4. **`source_uri_map` 生产文件**在机构侧，仓库内只能改 example；部署时同步（部署待办）。
5. 其余同 v2：linked_layer_id 断链、dist 重建、pre-commit env、结题材料 docx 同步。

---

## 8. 证据索引（v3 增量）

- 下划线规则：用户 2026-08-10 拍板（多数据集/源/传感器用 `_` 隔离；多变量同）。
- 融合产物确认：`I:\Geograph_DataSet\Soil_Moisture\SMAP_Soil_VOD_SM\2025120*.mat`（v7.3 HDF5，OMEGA/SM/VOD 三变量）；`overlay_registry.py` Phase 2 注释。
- omega 语义：`omega_avg_daily_*`（avg 线，sf=STATIC）／`omega_sf_fenkuai_*`（dynamic 线，sf=INVERTED_DAILY）／`omega_block_*`（8 天块前置）；`omega_avg_daily_gldas_online` = SMAP 反演 + GLDAS 温度输入（DUAL 双温度）→ 归 SMAP avg 线。
- 其余同 v2 §8。

---

## 9. 执行状态（2026-08-10）

- **Phases 1–4 已执行**：后端三真源 + 11 个 omega workflow seed + `source_uri_map.example.json` + 前端 `catalog.ts` / `overlay-symbology.ts` + 全量回归（`pytest Test/backend` + `Test/algorithms` + `npm run test`）全绿。
- **`lab-output` 已删除**：图层（`layer_descriptors` / `catalog.ts` / `overlay_registry` 注册块）+ 磁盘数据保留；`dataset_key` `lab_model_runs` 随删移除。
- **执行期发现的运行时遗漏（已修，属 Phase 1 真源一致性）**：doc-sync grep 发现 3 处旧 ID 残留会静默失效 → `workflow_router.py`（`omega-sf-fenkuai` 子串匹配→`omega-doy-dynamic`，L317/392）、`config.py` 示例（`smap-soil`→`ref-smap-sm-202512-l3`）、`frontend stores/layers/index.ts`（删 `smap-soil` 死引用 L341/402）。
- **文档同步（Phase 3 文档段）进行中**：
  - `Code/docs/真实数据e2e门槛.md`：`smap-soil`→`ref-smap-sm-202512-l3`、`lab-output`/`lab_output`→`合成样例图层`，已改。
  - `Tools/*.py`：`audit_overlay_assets.py` / `export_overlay_assets.py` 的 `_EXPORT_MAP` 三键改名（smap-sm-ts / soil-ddca / sm-dec2025），`verify_*`（soil-ddca→`ref-ddca-sm-201504-202512`）、`run_omega_sf_strip_timing.py`（`omega-sf-fenkuai`→`method-smap-omega-doy-dynamic`）、`smoke_system_workflows.py` 注释（`omega-avg-daily`→`method-smap-omega-doy-avg`），已改。未实现的 `omega-output` / `vod-dec2025` / `omega-dec2025` / `omega-fy-output` 及 `check_catalog_drift.py` 的 retired-shell `smap-soil` 按约定保留。
  - 结题验收材料 docx §3.2：`lab-output` 表行删除 + 4 个 ID 改名 + 描述更新——**canonical `早期初稿.docx` 仍被进程独占锁阻塞覆盖**（`os.replace` 仍 PermissionError，疑似 IDE 预览/Explorer 缩略图句柄，非 Word 进程）；已把校验通过的编辑件从 `.tmp.docx` 提升为干净交付名 **`早期初稿-命名更新版.docx`**（311 行、lab-output=0、4 个新 ID 齐、旧 ID 全清），可直接使用。用户释放锁后 `os.replace` 覆盖 canonical 并完成 `.corrupted-backup`/`(1).docx` 残留清理；`.corrupted-backup-20260810.docx` 现已不存在。
