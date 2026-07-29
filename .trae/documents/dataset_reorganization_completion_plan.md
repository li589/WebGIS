# 数据集目录重组 — 收尾计划

## 一、当前状态评估

### 1.1 目录结构（已完成 ✅）

`I:\Geograph_DataSet\` 顶层 12 个大类目录，全部使用英文命名 + 下划线，无空格、无中文：

| 大类目录 | 子目录数 | 真实数据文件数 | 状态 |
|---------|---------|-------------|------|
| Admin_Boundary | 0 | 0 | 空（仅 .gitkeep） |
| Atmospheric | 2 (CO2, Gosat) | 0 | 空 |
| Ecological_Vegetation | 3 (Biomass, LandCover, NDVI) | 2 (zip) | LandCover 有 2 个 zip |
| Geological | 1 (DEM) | 0 | 空 |
| Hazards | 3 (DWAA_result, Drought_Index, Landslide) | 539 | ✅ 有数据 |
| Inversion_Results | 3 (fy_avg, omega_block, smap_avg) | 0 | 空 |
| Meteorological | 4 (NC_2mTemp, NC_Dewpoint_2mTemp, Precipitation, Weather) | 0 | 空 |
| ProjectOutput | 1 (2023-01_Omega_Inversion) | 603 | ✅ 有数据 |
| Socio_Economic | 2 (HumanFootprint, Transport) | 0 | 空 |
| Soil_Moisture | 11 | 0 | 空 |
| Station_Observation | 4 (CASMOS, China_Station_Rainfall, Global_20yr, ISMN) | 0 | 空 |
| workflow_definitions | 2 (system, user) | 12 | ✅ 有数据 |

**数据丢失说明**：上一轮重组过程中，Admin_Boundary / Station_Observation / Inversion_Results / Soil_Moisture / Meteorological / Atmospheric / Ecological_Vegetation(Biomass, NDVI) / Geological / Socio_Economic 等目录的实际数据文件丢失，仅保留 .gitkeep 占位。仅 Hazards、ProjectOutput 和部分 LandCover zip 文件有真实数据。数据需从远程服务器（win11 E盘 / nas Z盘）重新下载。

### 1.2 代码路径修复（部分完成 ⚠️）

#### 已修复 ✅
- `Code/backend/app/services/layer_catalog.py` — 全部路径已更新
- `Code/backend/app/services/overlay_registry.py` — 全部路径已更新
- `Code/backend/source_uri_map.example.json` — 全部路径已更新
- `Code/backend/workflow_seeds/system/smap_soil_moisture_local.json` — 已更新
- `Code/algorithms/providers/Python/dataset_config.py` — DATASET_REGISTRY 已更新
- `Code/algorithms/providers/Python/data_access/universal_reader.py` — docstring 已更新
- `Code/algorithms/providers/Python/data_access/spatial_aligner.py` — docstring 已更新
- `Code/algorithms/providers/Python/data_access/data_preprocessor.py` — 已更新
- `Code/backend/tests/test_workflow_graph_compiler.py` — 已更新
- `Code/algorithms/providers/Python/tests/test_e2e_output_pipeline.py` — 已更新

#### 未修复（残留旧路径）❌

**关键配置文件：**
| 文件 | 行号 | 旧路径 | 新路径 |
|------|------|--------|--------|
| `Code/backend/.env` | 32 | `I:/Geograph_DataSet/SMAP` | `I:/Geograph_DataSet/Soil_Moisture/SMAP` |
| `Code/backend/.env` | 32 | `I:/Geograph_DataSet/Soil_Ecological_Data/NDVI/VIIRS_9km_tif` | `I:/Geograph_DataSet/Ecological_Vegetation/NDVI/VIIRS_9km_tif` |
| `Code/backend/.env` | 32 | `I:/Geograph_DataSet/Soil_Ecological_Data/Smap_OriginData` | `I:/Geograph_DataSet/Soil_Moisture/SMAP_Origin_Data` |

**Tools/ 脚本（10 个文件）：**
| 文件 | 旧路径片段 | 新路径片段 |
|------|-----------|-----------|
| `Tools/export_overlay_assets.py` | `Soil_Ecological_Data\DDCA\DDCA_DH\H` | `Soil_Moisture\DDCA\DDCA_DH\H` |
| `Tools/export_overlay_assets.py` | `Soil_Ecological_Data\SmapSoil_VOD_SM` | `Soil_Moisture\SMAP_Soil_VOD_SM` |
| `Tools/download_smap_2weeks.py` | `I:\Geograph_DataSet\SMAP` | `I:\Geograph_DataSet\Soil_Moisture\SMAP` |
| `Tools/inspect_overlay_bounds.py` | `Soil_Ecological_Data\DDCA\DDCA_DH\H` | `Soil_Moisture\DDCA\DDCA_DH\H` |
| `Tools/inspect_ease_mat.py` | `Soil_Ecological_Data\DDCA\DDCA_DH\H` | `Soil_Moisture\DDCA\DDCA_DH\H` |
| `Tools/test_data_production_e2e.py` | `Geograph_DataSet/SMAP/` | `Geograph_DataSet/Soil_Moisture/SMAP/` |
| `Tools/test_data_production_e2e.py` | `Soil_Ecological_Data/SmapSoil_VOD_SM` | `Soil_Moisture/SMAP_Soil_VOD_SM` |
| `Tools/_inspect_mats.py` | `Soil_Ecological_Data\DDCA\DDCA_DH\H` | `Soil_Moisture\DDCA\DDCA_DH\H` |
| `Tools/_run_new_exports.py` | `Soil_Ecological_Data\SmapSoil_VOD_SM` | `Soil_Moisture\SMAP_Soil_VOD_SM` |
| `Tools/verify_all_datasets.py` | `Soil_Ecological_Data` + `InversionResults` | `Soil_Moisture` + `Inversion_Results` |
| `Tools/_inspect_vod.py` | 3 处 `Soil_Ecological_Data\...` | 对应 `Soil_Moisture\...` |

**文档文件（3 个，非阻塞但应更新）：**
| 文件 | 说明 |
|------|------|
| `Tools/DATA_PLANNING.md` | 引用旧目录名 Soil_Ecological_Data |
| `Doc/课题组数据需求与产出说明.md` | 引用旧目录名 Soil_Ecological_Data |
| `Doc/数据源与工作流对照说明-2026-07-21.md` | 多处引用旧路径（SMAP、Soil_Ecological_Data） |

**历史报告（可保留不动）：**
| 文件 | 说明 |
|------|------|
| `Tools/reports/overlay_audit_report.md` | 自动生成的审计报告，属历史快照 |

### 1.3 project_memory.md（未更新 ❌）

第 24 行仍引用旧目录名：`二氧化碳数据, 交通数据, 行政区数据, 灾害数据, 栅格气象数据, DEM, Gosat, ISD-Lite, Soil_Ecological_Data`

---

## 二、执行计划

### 步骤 1：修复 `.env` 文件（P0 关键）

修改 `Code/backend/.env` 第 32 行 `BACKEND_REMOTE_LAYER_DATA_URIS`：
- `I:/Geograph_DataSet/SMAP` → `I:/Geograph_DataSet/Soil_Moisture/SMAP`
- `I:/Geograph_DataSet/Soil_Ecological_Data/NDVI/VIIRS_9km_tif` → `I:/Geograph_DataSet/Ecological_Vegetation/NDVI/VIIRS_9km_tif`
- `I:/Geograph_DataSet/Soil_Ecological_Data/Smap_OriginData` → `I:/Geograph_DataSet/Soil_Moisture/SMAP_Origin_Data`

### 步骤 2：修复 Tools/ 脚本（P1）

逐一修改 10 个 Python 脚本中的旧路径引用，路径映射表：

| 旧路径片段 | 新路径片段 |
|-----------|-----------|
| `Geograph_DataSet/SMAP` (裸SMAP) | `Geograph_DataSet/Soil_Moisture/SMAP` |
| `Geograph_DataSet\SMAP` (裸SMAP) | `Geograph_DataSet\Soil_Moisture\SMAP` |
| `Soil_Ecological_Data\DDCA` | `Soil_Moisture\DDCA` |
| `Soil_Ecological_Data/SmapSoil_VOD_SM` | `Soil_Moisture/SMAP_Soil_VOD_SM` |
| `Soil_Ecological_Data\SmapSoil_VOD_SM` | `Soil_Moisture\SMAP_Soil_VOD_SM` |
| `Soil_Ecological_Data\Smap_OriginData` | `Soil_Moisture\SMAP_Origin_Data` |
| `Soil_Ecological_Data\CustomNC_SM_CalData` | `Soil_Moisture\CustomNC_SM_CalData` |
| `Soil_Ecological_Data\NDVI` | `Ecological_Vegetation\NDVI` |
| `Soil_Ecological_Data/Ancillary` | `Soil_Moisture/Ancillary` |
| `Soil_Ecological_Data/China_Soil` | `Soil_Moisture/China_Soil` |
| `Soil_Ecological_Data/FY_MWRI` | `Soil_Moisture/FY_MWRI` |
| `"InversionResults"` | `"Inversion_Results"` |

### 步骤 3：更新文档文件（P2）

更新 3 个文档文件中的旧路径引用，使其与新目录结构一致。

### 步骤 4：更新 project_memory.md（P1）

将第 24 行的旧目录名列表替换为新目录结构说明：
```
Local data must be stored under `I:\Geograph_DataSet\` (external HDD); 
top-level directories use English category names with underscores: 
Admin_Boundary, Atmospheric, Ecological_Vegetation, Geological, Hazards, 
Inversion_Results, Meteorological, ProjectOutput, Socio_Economic, 
Soil_Moisture, Station_Observation, workflow_definitions
```

同时在 Lessons Learned 中添加数据丢失教训。

### 步骤 5：验证（P0）

1. **grep 残留检查**：全仓库搜索 `Soil_Ecological_Data`、裸 `Geograph_DataSet/SMAP`（不含 `/Soil_Moisture/`）、`InversionResults`（不含下划线），确认代码文件中无残留
2. **后端测试**：`cd Code/backend && pytest tests/test_workflow_graph_compiler.py -q`
3. **前端测试**：`cd Code/frontend && npm run test && npm run lint && npm run build`
4. **算法包测试**：`cd Code/algorithms/providers/Python && pytest tests/ -q`

### 步骤 6：数据恢复建议（P2，非阻塞）

大部分目录数据在上一轮重组中丢失。恢复方案：
- 通过 `Tools/remote_data_scanner.py` 扫描远程服务器（win11 E盘 / nas Z盘）
- 使用 `Tools/remote_data_downloader.py` 按需下载到对应新目录
- Inversion_Results 可通过运行 `omega_avg_daily_smap_single` 工作流重新生成
