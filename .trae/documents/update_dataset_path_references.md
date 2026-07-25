# 计划：更新 3 个文档文件中的过时数据集路径引用

## 概述

数据集目录 `I:\Geograph_DataSet\` 已重组，需将 3 个文档文件中的旧目录名更新为新目录名。共计 **45 处**路径引用需要更新，涉及 3 类替换规则：`Soil_Ecological_Data` 子目录重命名、裸 `SMAP` 目录归入 `Soil_Moisture`、`InversionResults` 更名为 `Inversion_Results`。

## 当前状态分析

已通过 Read 和 Grep 完整扫描 3 个文件，确认所有需更新的路径引用及其行号：

### 文件 1: `Tools/DATA_PLANNING.md` — 21 处变更

**InversionResults → Inversion_Results（15 处）：**
- 行 119, 142, 143, 161, 229, 424, 435, 450, 549, 550, 551, 632, 657, 715, 727
- 所有 `InversionResults` 均为目录名/路径引用，统一替换为 `Inversion_Results`

**Soil_Ecological_Data 引用（2 处）：**
- 行 126: `` `Soil_Ecological_Data/` ``（表格行，顶层目录，内容为"DDCA、2m温度、森林变化、WHU_CLCD"）→ `` `Soil_Moisture/` ``（多数子目录映射至 Soil_Moisture）
- 行 150: `` `Soil_Ecological_Data/WHU_CLCD_1985_2023/` `` → `` `Ecological_Vegetation/LandCover/CLCD_1985_2023/` ``（前缀 `Soil_Ecological_Data/WHU_CLCD` 替换为 `Ecological_Vegetation/LandCover/CLCD`，保留 `_1985_2023/` 后缀）

**裸 SMAP 引用（4 处）：**
- 行 125: `` `SMAP/` `` → `` `Soil_Moisture/SMAP/` ``（表格中的目录名，反引号包裹）
- 行 156: `├── SMAP\` → `├── Soil_Moisture\SMAP\`（目录树代码块）
- 行 539: `| SMAP |` → `| Soil_Moisture/SMAP |`（下载状态表，目录列）
- 行 540: `| SMAP |` → `| Soil_Moisture/SMAP |`（下载状态表，目录列）

### 文件 2: `Doc/课题组数据需求与产出说明.md` — 1 处变更

- 行 133: `├── Soil_Ecological_Data\` → `├── Soil_Moisture\`（目录树中的顶层目录，子目录为"中国土壤数据"即 China_Soil，映射至 Soil_Moisture）

### 文件 3: `Doc/数据源与工作流对照说明-2026-07-21.md` — 23 处变更

**InversionResults → Inversion_Results（9 处）：**
- 行 95, 96, 103, 104, 232, 233, 236, 237, 293
- 包含完整路径（`I:\Geograph_DataSet\InversionResults\...`）、相对路径（`InversionResults\smap_avg\...`）和数据源名称（表格中的 `InversionResults`）

**Soil_Ecological_Data 引用（12 处）：**
- 行 45: `Soil_Ecological_Data\FY_MWRI\` → `Soil_Moisture\FY_MWRI\`
- 行 47: `Soil_Ecological_Data\NDVI\VIIRS\` → `Ecological_Vegetation\NDVI\VIIRS\`
- 行 48: `Soil_Ecological_Data\NDVI\MODIS\` → `Ecological_Vegetation\NDVI\MODIS\`
- 行 80: `Soil_Ecological_Data\China_Soil\` → `Soil_Moisture\China_Soil\`
- 行 97: `Soil_Ecological_Data\Ancillary\` → `Soil_Moisture\Ancillary\`
- 行 105: `Soil_Ecological_Data\DDCA\` → `Soil_Moisture\DDCA\`
- 行 106: `Soil_Ecological_Data\SmapSoil_VOD_SM\` → `Soil_Moisture\SMAP_Soil_VOD_SM\`
- 行 107: `Soil_Ecological_Data\SmapSoil_VOD_SM\` → `Soil_Moisture\SMAP_Soil_VOD_SM\`
- 行 108: `Soil_Ecological_Data\SmapSoil_VOD_SM\` → `Soil_Moisture\SMAP_Soil_VOD_SM\`
- 行 234: `Soil_Ecological_Data\DDCA\` → `Soil_Moisture\DDCA\`
- 行 235: `Soil_Ecological_Data\SmapSoil_VOD_SM\` → `Soil_Moisture\SMAP_Soil_VOD_SM\`
- 行 283: `Soil_Ecological_Data\NDVI\VIIRS\` → `Ecological_Vegetation\NDVI\VIIRS\`

**裸 SMAP 引用（2 处）：**
- 行 43: `I:\Geograph_DataSet\SMAP\` → `I:\Geograph_DataSet\Soil_Moisture\SMAP\`
- 行 44: `I:\Geograph_DataSet\SMAP\` → `I:\Geograph_DataSet\Soil_Moisture\SMAP\`

## 实施方案

使用 Python 脚本进行批量有序字符串替换，确保最具体的模式先替换，避免冲突。

### 替换顺序（按特异性从高到低）

**第 1 步：Soil_Ecological_Data 子目录替换（反斜杠 \ 变体）**
1. `Soil_Ecological_Data\WHU_CLCD` → `Ecological_Vegetation\LandCover\CLCD`
2. `Soil_Ecological_Data\FY_MWRI` → `Soil_Moisture\FY_MWRI`
3. `Soil_Ecological_Data\SmapSoil_VOD_SM` → `Soil_Moisture\SMAP_Soil_VOD_SM`
4. `Soil_Ecological_Data\Smap_OriginData` → `Soil_Moisture\SMAP_Origin_Data`
5. `Soil_Ecological_Data\CustomNC_SM_CalData` → `Soil_Moisture\CustomNC_SM_CalData`
6. `Soil_Ecological_Data\NDVI` → `Ecological_Vegetation\NDVI`
7. `Soil_Ecological_Data\Ancillary` → `Soil_Moisture\Ancillary`
8. `Soil_Ecological_Data\China_Soil` → `Soil_Moisture\China_Soil`
9. `Soil_Ecological_Data\DDCA` → `Soil_Moisture\DDCA`

**第 2 步：Soil_Ecological_Data 子目录替换（正斜杠 / 变体）**
10. `Soil_Ecological_Data/WHU_CLCD` → `Ecological_Vegetation/LandCover/CLCD`
11. `Soil_Ecological_Data/FY_MWRI` → `Soil_Moisture/FY_MWRI`
12. `Soil_Ecological_Data/SmapSoil_VOD_SM` → `Soil_Moisture/SMAP_Soil_VOD_SM`
13. `Soil_Ecological_Data/Smap_OriginData` → `Soil_Moisture/SMAP_Origin_Data`
14. `Soil_Ecological_Data/CustomNC_SM_CalData` → `Soil_Moisture/CustomNC_SM_CalData`
15. `Soil_Ecological_Data/NDVI` → `Ecological_Vegetation/NDVI`
16. `Soil_Ecological_Data/Ancillary` → `Soil_Moisture/Ancillary`
17. `Soil_Ecological_Data/China_Soil` → `Soil_Moisture/China_Soil`
18. `Soil_Ecological_Data/DDCA` → `Soil_Moisture/DDCA`

**第 3 步：剩余裸 Soil_Ecological_Data 顶层目录引用**
19. `Soil_Ecological_Data/` → `Soil_Moisture/`（行 126，DATA_PLANNING.md）
20. `Soil_Ecological_Data\` → `Soil_Moisture\`（行 133，课题组数据需求与产出说明.md）

**第 4 步：裸 SMAP 完整路径替换**
21. `I:\Geograph_DataSet\SMAP\` → `I:\Geograph_DataSet\Soil_Moisture\SMAP\`（文件 3 行 43, 44）
22. `I:\Geograph_DataSet/SMAP/` → `I:\Geograph_DataSet/Soil_Moisture/SMAP/`（如存在正斜杠变体）

**第 5 步：DATA_PLANNING.md 中不带 Geograph_DataSet 前缀的裸 SMAP 引用**
23. `` `SMAP/` `` → `` `Soil_Moisture/SMAP/` ``（行 125，反引号包裹的表格目录名）
24. `├── SMAP\` → `├── Soil_Moisture\SMAP\`（行 156，目录树）
25. `| SMAP |` → `| Soil_Moisture/SMAP |`（行 539, 540，下载状态表）

**第 6 步：InversionResults 全局替换**
26. `InversionResults` → `Inversion_Results`（所有剩余出现，覆盖文件 1 的 15 处和文件 3 的 9 处）

### 脚本位置

- 脚本文件：`c:\Users\likr\.trae-cn\work\6a632a70243d5a61eb58f056\update_paths.py`（中间产物）
- 脚本逻辑：读取各文件 → 按上述顺序应用 str.replace → 写回文件 → 打印每步替换计数

## 假设与决策

1. **`Soil_Ecological_Data/` 顶层引用（DATA_PLANNING.md 行 126）**：该行内容为"DDCA、2m温度、森林变化、WHU_CLCD"，跨 Soil_Moisture 和 Ecological_Vegetation 两个新目录。决策：更新为 `Soil_Moisture/`，因为多数子目录（DDCA/Ancillary/China_Soil/FY_MWRI 等）映射至 Soil_Moisture，且 DDCA 为主要数据量来源。

2. **`WHU_CLCD_1985_2023` 子目录名**：映射 `Soil_Ecological_Data/WHU_CLCD` → `Ecological_Vegetation/LandCover/CLCD` 作为前缀替换，`Soil_Ecological_Data/WHU_CLCD_1985_2023/` 变为 `Ecological_Vegetation/LandCover/CLCD_1985_2023/`（`WHU_` 前缀被去除，`_1985_2023` 后缀保留）。

3. **裸 SMAP 替换范围**：仅替换路径/目录引用中的 SMAP（如 `` `SMAP/` ``、`├── SMAP\`、`| SMAP |`、`I:\Geograph_DataSet\SMAP\`），不替换文本中指代卫星/数据集的 "SMAP"（如"SMAP L3 土壤水分"、"SMAP 数据"等）。

4. **`InversionResults` 全局替换安全性**：搜索字符串 `InversionResults`（无下划线）不会匹配已替换的 `Inversion_Results`（有下划线），无双重替换风险。文件中不存在预先存在的 `Inversion_Results` 引用。

5. **不修改 `Tools/reports/overlay_audit_report.md`**：历史审计报告，保持原样。

6. **文件 2 目录树中的其他旧目录名**：文件 2 的目录树还包含中文目录名（栅格气象数据、二氧化碳数据、行政区数据等），这些不在本次更新范围内，仅更新 `Soil_Ecological_Data\`。

## 验证步骤

1. 脚本执行后，用 Grep 在 3 个文件中搜索 `Soil_Ecological_Data`，确认返回 0 结果
2. 用 Grep 在 3 个文件中搜索 `InversionResults`（无下划线），确认返回 0 结果
3. 用 Grep 搜索 `Geograph_DataSet\SMAP\` 和 `Geograph_DataSet/SMAP/`（不带 Soil_Moisture），确认返回 0 结果
4. 用 Grep 搜索 `` `SMAP/` `` 和 `| SMAP |`（DATA_PLANNING.md 中的裸 SMAP 模式），确认返回 0 结果
5. 用 Grep 搜索新路径名（`Soil_Moisture`、`Ecological_Vegetation`、`Inversion_Results`），确认数量与预期一致
6. 人工抽查关键行（如文件 3 行 105 的 DDCA 路径、文件 1 行 150 的 WHU_CLCD 路径），确认替换正确且上下文完整
