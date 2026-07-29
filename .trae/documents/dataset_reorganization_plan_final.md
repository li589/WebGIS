# 数据集目录整理与路径修复 — 最终计划

> 日期: 2026-07-24 | 状态: 待审批

## 一、现状评估

### 1.1 顶层目录（已完成规范化）

`I:\Geograph_DataSet\` 顶层 12 个目录均已使用英文大类命名 + 下划线，**无需改动**：

| 目录 | 说明 | 实际数据 |
|------|------|---------|
| `Admin_Boundary` | 行政区划 | 仅 .gitkeep |
| `Atmospheric` | 大气数据 | 仅 .gitkeep |
| `Ecological_Vegetation` | 生态植被 | 2 个 zip 文件 |
| `Geological` | 地质 | 仅 .gitkeep |
| `Hazards` | 灾害 | **500+ tif + 28 个文件** |
| `Inversion_Results` | 反演结果 | 仅 .gitkeep |
| `Meteorological` | 气象 | 仅 .gitkeep |
| `ProjectOutput` | 项目产出 | **大量 overlay PNG/JSON** |
| `Socio_Economic` | 社会经济 | 仅 .gitkeep |
| `Soil_Moisture` | 土壤水分 | 仅 .gitkeep |
| `Station_Observation` | 站点观测 | 仅 .gitkeep |
| `workflow_definitions` | 工作流定义 | 13 个 JSON |

### 1.2 子目录命名不一致问题

| 当前路径 | 问题描述 | 拟改名 | 有数据? |
|---------|---------|--------|---------|
| `Atmospheric/Gosat` | 首字母未大写 | `GOSAT` | 否 |
| `Hazards/DWAA_result` | "result" 未大写 | `DWAA_Result` | **是 (500+文件)** |
| `Hazards/Landslide/fatal_landslides_database` | 全小写 | `Fatal_Landslides_Database` | **是 (17文件)** |
| `Meteorological/NC_2mTemp` | "2mTemp" 未分词 | `NC_2m_Temp` | 否 |
| `Meteorological/NC_Dewpoint_2mTemp` | "2mTemp" 未分词 | `NC_Dewpoint_2m_Temp` | 否 |
| `Meteorological/Weather/WindField` | camelCase | `Wind_Field` | 否 |

### 1.3 文件放置问题

| 文件 | 当前位置 | 拟移至 |
|------|---------|--------|
| `CLCD_1985_2023_China_LandCover.zip` | `Ecological_Vegetation/LandCover/` | `Ecological_Vegetation/LandCover/CLCD/` |
| `Guangdong_Forest_Change.zip` | `Ecological_Vegetation/LandCover/` | `Ecological_Vegetation/LandCover/Forest_Change/` |

## 二、代码路径问题（P0 — 运行时失败）

### 2.1 `Tools/export_overlay_assets.py` — 7 处旧路径（缺大类前缀）

| 行号 | 当前路径 | 修正路径 |
|------|---------|---------|
| 513 | `I:\Geograph_DataSet\DEM\ETOPO_2022\...` | `I:\Geograph_DataSet\Geological\DEM\ETOPO_2022\...` |
| 805 | `I:\Geograph_DataSet\Weather\Precipitation\Precipitation\dataset` | `I:\Geograph_DataSet\Meteorological\Precipitation\GPCP\dataset` |
| 869 | `I:\Geograph_DataSet\DEM\GEBCO_2024.nc` | `I:\Geograph_DataSet\Geological\DEM\GEBCO_2024.nc` |
| 921 | `I:\Geograph_DataSet\Precipitation\pre_2002_01.tif` | `I:\Geograph_DataSet\Meteorological\Precipitation\pre_2002_01.tif` |
| 972 | `I:\Geograph_DataSet\LandCover\CLCD_v01_1997.tif` | `I:\Geograph_DataSet\Ecological_Vegetation\LandCover\CLCD_v01_1997.tif` |
| 1017 | `I:\Geograph_DataSet\Biomass\ESACCI-BIOMASS-...` | `I:\Geograph_DataSet\Ecological_Vegetation\Biomass\ESACCI-BIOMASS-...` |
| 1172 | `I:\Geograph_DataSet\CO2\MidLayerCO2Column\...` | `I:\Geograph_DataSet\Atmospheric\CO2\MidLayerCO2Column\...` |

### 2.2 `Tools/verify_all_datasets.py` — 9 处旧路径（缺大类前缀）

| 行号 | 数据集 | 当前路径 | 修正路径 |
|------|--------|---------|---------|
| 152 | SMAP L3 | `SMAP/...` | `Soil_Moisture/SMAP/...` |
| 156 | MCD12Q1 | `LandCover/...` | `Ecological_Vegetation/LandCover/...` |
| 161 | HFP 2020 | `HumanFootprint/...` | `Socio_Economic/HumanFootprint/...` |
| 174 | GEBCO DEM | `DEM/GEBCO_2024.nc` | `Geological/DEM/GEBCO_2024.nc` |
| 180 | Italy DEM | `DEM/Italy_GEBCO2024/...` | `Geological/DEM/Italy_GEBCO2024/...` |
| 188 | CMFD Pre | `Precipitation/pre_2002_01.tif` | `Meteorological/Precipitation/pre_2002_01.tif` |
| 199 | CLCD 1997 | `LandCover/CLCD_v01_1997.tif` | `Ecological_Vegetation/LandCover/CLCD_v01_1997.tif` |
| 206 | BIOMASS | `Biomass/ESACCI-...` | `Ecological_Vegetation/Biomass/ESACCI-...` |
| 240 | CO2 | `CO2/MidLayerCO2Column/TIF/...` | `Atmospheric/CO2/MidLayerCO2Column/TIF/...` |

### 2.3 `Tools/inspect_overlay_bounds.py` — 1 处旧路径

| 行号 | 当前路径 | 修正路径 |
|------|---------|---------|
| 90 | `I:\Geograph_DataSet\Precipitation\pre_2002_01.tif` | `I:\Geograph_DataSet\Meteorological\Precipitation\pre_2002_01.tif` |

### 2.4 `Code/algorithms/providers/Python/tests/test_e2e_output_pipeline.py` — 旧中文路径

| 行号 | 当前代码 | 修正代码 |
|------|---------|---------|
| 662 | `backend.resolve_path("栅格气象数据", "VIIRS_NDVI")` | `backend.resolve_path("Ecological_Vegetation", "NDVI/VIIRS")` |
| 663 | `self.assertIn("栅格气象数据", resolved)` | `self.assertIn("Ecological_Vegetation", resolved)` |

### 2.5 `Code/algorithms/providers/Python/dataset_config.py` — 错误映射

| 行号 | 键 | 当前 relative_path | 修正 relative_path | 原因 |
|------|-----|-------------------|-------------------|------|
| 363 | `STATION_ISD_LITE` | `Station_Observation/China_Station_Rainfall` | `Station_Observation/ISD_Lite` | ISD-Lite ≠ 中国站点降水 |
| 440 | `ARIDITY_INDEX` | `Others` | `Hazards/Drought_Index` | "Others" 目录不存在 |

> 注: 需同时在 `I:\Geograph_DataSet\Station_Observation\` 下创建 `ISD_Lite` 目录。

### 2.6 `Code/backend/app/services/overlay_registry.py` — 路径不匹配

| 行号 | 当前路径 | 修正路径 | 原因 |
|------|---------|---------|------|
| 265 | `Meteorological\Precipitation\GPCP\dataset` | `Meteorological\Precipitation\GPCP` | "dataset" 子目录不存在 |
| 586 | `Geological\DEM\GEBCO_2024.nc` | 保留但标注 `# 不存在时 fallback` | 文件可能未下载 |

### 2.7 `Code/backend/app/services/layer_catalog.py` — 路径不匹配

| 行号 | 当前路径 | 说明 |
|------|---------|------|
| 900 | `Geological/DEM/GEBCO_2024.nc` | 文件不存在，实际为 ETOPO_2022；加 fallback 注释 |

### 2.8 `Code/frontend/src/stores/layers/catalog.ts` — 显示标签

| 行号 | 当前 sourceLabel | 修正 sourceLabel |
|------|-----------------|-----------------|
| 893 | `SMAP L3 + InversionResults` | `SMAP L3 + Inversion_Results` |
| 963 | `SMAP InversionResults` | `SMAP Inversion_Results` |
| 1124 | `SMAP InversionResults fy_avg` | `SMAP Inversion_Results fy_avg` |

## 三、文档更新（P2）

| 文件 | 问题 | 处理方式 |
|------|------|---------|
| `Doc/课题组数据需求与产出说明.md` | 目录树用中文旧名 | 更新为英文新名 |
| `Tools/DATA_PLANNING.md` | 部分旧名引用 | 更新映射表 |
| `Tools/reports/download_log.txt` | 旧路径日志 | 保留（历史记录，不改） |
| `.trae/documents/*.md` | 历史规划文档 | 保留（历史记录，不改） |

## 四、执行步骤

### Step 1: 子目录重命名（仅空目录，低风险）

使用 `Rename-Item`（目录为空，无数据丢失风险）：

```
Atmospheric/Gosat          → Atmospheric/GOSAT
Meteorological/NC_2mTemp   → Meteorological/NC_2m_Temp
Meteorological/NC_Dewpoint_2mTemp → Meteorological/NC_Dewpoint_2m_Temp
Meteorological/Weather/WindField  → Meteorological/Weather/Wind_Field
```

### Step 2: 子目录重命名（有数据，需 robocopy）

使用 `robocopy /MOVE`（避免 Move-Item 中文/NTFS 问题）：

```
Hazards/DWAA_result                      → Hazards/DWAA_Result
Hazards/Landslide/fatal_landslides_database → Hazards/Landslide/Fatal_Landslides_Database
```

### Step 3: 文件移动

```
Ecological_Vegetation/LandCover/CLCD_1985_2023_China_LandCover.zip
  → Ecological_Vegetation/LandCover/CLCD/CLCD_1985_2023_China_LandCover.zip

Ecological_Vegetation/LandCover/Guangdong_Forest_Change.zip
  → Ecological_Vegetation/LandCover/Forest_Change/Guangdong_Forest_Change.zip
```

### Step 4: 创建缺失目录

```
Station_Observation/ISD_Lite   (用于 STATION_ISD_LITE 数据集)
```

### Step 5: 修复代码路径（P0）

按 §2.1–§2.8 逐文件修复，使用 `SearchReplace` 精确替换。

涉及文件（共 8 个）：
1. `Tools/export_overlay_assets.py` — 7 处
2. `Tools/verify_all_datasets.py` — 9 处
3. `Tools/inspect_overlay_bounds.py` — 1 处
4. `Code/algorithms/providers/Python/tests/test_e2e_output_pipeline.py` — 2 处
5. `Code/algorithms/providers/Python/dataset_config.py` — 2 处 + 注释更新
6. `Code/backend/app/services/overlay_registry.py` — 2 处
7. `Code/backend/app/services/layer_catalog.py` — 1 处注释
8. `Code/frontend/src/stores/layers/catalog.ts` — 3 处

### Step 6: 更新文档

更新 `Doc/课题组数据需求与产出说明.md` 和 `Tools/DATA_PLANNING.md` 中的目录树。

### Step 7: 更新 dataset_config.py 注释

将中文注释（"二氧化碳数据""行政区数据""灾害数据"）更新为英文或保留中文但确保路径正确。

### Step 8: 验证

1. `grep -r "Geograph_DataSet\\\\DEM\\\\" Code/ Tools/` — 确认无 `DEM\` 直接引用（应为 `Geological\DEM\`）
2. `grep -r "Geograph_DataSet\\\\Precipitation\\\\" Code/ Tools/` — 确认无 `Precipitation\` 直接引用
3. `grep -r "Geograph_DataSet\\\\LandCover\\\\" Code/ Tools/` — 确认无 `LandCover\` 直接引用
4. `grep -r "Geograph_DataSet\\\\Biomass\\\\" Code/ Tools/` — 确认无 `Biomass\` 直接引用
5. `grep -r "Geograph_DataSet\\\\CO2\\\\" Code/ Tools/` — 确认无 `CO2\` 直接引用（应为 `Atmospheric\CO2\`）
6. `grep -r "Geograph_DataSet\\\\Weather\\\\" Code/ Tools/` — 确认无 `Weather\` 直接引用（应为 `Meteorological\`）
7. `grep -r "栅格气象数据\|InversionResults\|Soil_Ecological_Data" Code/` — 确认无旧名残留
8. 后端测试: `cd Code/backend && pytest tests/ -q --timeout=30`（关键测试子集）
9. 前端检查: `cd Code/frontend && npm run lint && npm run build`

## 五、风险评估与缓解

| 风险 | 缓解措施 |
|------|---------|
| 有数据目录重命名导致数据丢失 | 使用 `robocopy /MOVE`，先复制再删除源 |
| 代码路径遗漏 | 全量 grep 扫描 + 测试验证 |
| dataset_config.py 映射错误 | 逐条核对 `relative_path` 与实际目录 |
| GEBCO_2024.nc 不存在 | 加 fallback 逻辑，不阻塞启动 |

## 六、不在本次范围内

- 远程数据重新下载（需单独执行 `Tools/remote_data_scanner.py` + 下载脚本）
- `Tools/reports/download_log.txt` 历史日志更新
- `.trae/documents/` 历史规划文档更新
- 前端组件功能测试（仅做 lint + build）
