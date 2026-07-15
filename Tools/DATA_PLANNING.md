# 远程数据规划与组织方案

> 生成时间: 2026-07-14
> 最后更新: 2026-07-15
> 扫描工具: `Tools/remote_data_scanner.py`
> 数据根目录: `I:\Geograph_DataSet\`

## 1. 远程数据源

### 1.1 Win11 E盘 (https://win11file.personaltunnel.dpdns.org)
- **说明**: 映射远端电脑 E 盘，包含数据和软件
- **权限**: 只读
- **扫描状态**: 部分扫描（3600 目录，3249 文件，5.0 GB）
- **目录结构**: 深度 0(1) → 深度 1(8) → 深度 2(3591)

**主要数据类型**:
| 目录 | 数据类型 | 格式 | 大小 | 说明 |
|------|----------|------|------|------|
| `/google54/ALOS_*` | ALOS PALSAR 雷达数据 | .tif | ~30 文件, 256 KB | 2019/2021 年，经纬度切片 |
| `/1/S1_*.tif` | Sentinel-1 SAR 数据 | .tif | 大量, 0.1-3.4 MB/文件 | 2017 年，8天合成 |
| `/bio_result/` | 生物结果数据 | .tif | 137.9 MB (9km_6933.tif) | 9km 分辨率 |
| `/google/Google AI Studio/` | Google AI Studio 数据 | .csv | 37.8 MB | — |

### 1.2 NAS Z盘 (https://nasfile.personaltunnel.dpdns.org)
- **说明**: 映射 NAS 网络驱动器 Z 盘，包含课题组成员数据
- **权限**: 只读
- **扫描状态**: 完整扫描（524 目录，1286 文件，1.2 TB）
- **目录结构**: 深度 0(1) → 深度 1(6) → 深度 2(89) → 深度 3(428)

**文件格式分布**:
| 格式 | 文件数 | 总大小 | 用途 |
|------|--------|--------|------|
| .tif | 579 | 475.9 GB | GeoTIFF 栅格数据 |
| .nc | 292 | 386.7 GB | NetCDF 网格数据 |
| .csv | 108 | 351.7 GB | 表格数据（气象配对事件） |
| .h5 | 74 | 20.5 GB | HDF5 数据 |
| .mat | 67 | 418.5 MB | MATLAB 数据 |
| .txt | 116 | 51.2 MB | 文本/说明文件 |
| .shp | 15 | 2.5 GB | Shapefile 矢量数据 |
| .xlsx | 12 | 31.8 MB | Excel 表格 |
| .json | 16 | 68.1 KB | JSON 配置/元数据 |
| .dat | 6 | 480 B | 二进制数据 |
| .xls | 1 | 36.5 KB | Excel 97-2003 |

## 2. 课题组成员数据分布

### 2.1 LiuSJ/（刘师兄）— 最大数据量
| 子目录 | 文件数 | 大小 | 主要内容 |
|--------|--------|------|----------|
| `Data_0.1/` | 96 | 12.7 GB | 0.1度分辨率数据 |
| `Saved/` | 60 | 89.0 GB | 保存的处理结果 |
| `Data/` | 53 | 33.0 GB | Human Footprint (hfp2005-2018, 2.2GB/文件) |
| `WF&DWA/` | 37 | 1.4 GB | WF/DWA 分析数据 |

### 2.2 Liuzheng/（刘正）— 植被与土壤反演
| 子目录 | 文件数 | 大小 | 主要内容 |
|--------|--------|------|----------|
| `Data/` | 60 | 43.3 GB | canopy_height (Forest_height_2019, 2-6 GB/文件) |
| `omega_final/` | 60 | 203.7 MB | omega 反演结果 (smap_avg_ω, fy_avg_ω) |
| `H2/` | 8 | 32.2 MB | H2 参数数据 |
| `ISMN和FLUXz站点匹配/` | 4 | 793 KB | ISMN/FLUX 站点匹配 |
| `Attribute_ω/` | 3 | 3.9 KB | omega 属性 |
| `DIEBACK/` | 3 | 20.5 KB | Dieback 分析 |
| `Delta_R2_by_ω/` | 1 | 14.4 KB | R² 变化分析 |
| `H1/` | 1 | 21.1 KB | H1 参数 |
| `ω_globalview/` | 1 | 28.3 KB | omega 全局视图 |

### 2.3 Chenhaojun/（陈浩军）
| 子目录 | 文件数 | 大小 | 主要内容 |
|--------|--------|------|----------|
| `Data/` | 40 | 19.8 GB | 主要数据集 |
| `Paper/` | 3 | 5.6 MB | 论文相关 |
| `事件图/` | 3 | 9.6 MB | 事件图表 |

### 2.4 Wangxd/（王XD）
- `N盘/GRADES/` — GRADES 河流数据 (16.5 GB, .nc)

## 3. 关键数据集详情

### 3.1 土壤水分相关
- **SMAP 数据**: .h5 格式，74 个文件，20.5 GB
- **ISMN 站点**: 站点观测数据，用于土壤水分验证
- **FLUX 站点**: 通量塔数据，与 ISMN 站点匹配

### 3.2 植被相关
- **ESACCI-BIOMASS**: 生物量数据，.nc 格式，2007-2020 年，16-17 GB/文件
- **Forest_height_2019**: 森林高度，.tif 格式，按大洲切片（SAM, SAFR, NAM, SASIA, NASIA, NAFR）
- **Human Footprint (hfp)**: 人类足迹指数，.tif 格式，2005-2020 年，~2.2 GB/文件（hfp2018=2255 MB，hfp2019/2020=546 MB）
- **ALOS PALSAR**: 雷达数据，.tif 格式，2019/2021 年，经纬度切片
- **Sentinel-1 SAR**: 合成孔径雷达，.tif 格式，2017 年，8天合成

### 3.3 气象与降水
- **CMFD**: 中国气象驱动数据，.nc 格式，月度 0.1° 分辨率，1979-2018
- **GLDAS**: 全球陆面数据同化系统，.csv 格式，配对事件数据（13-52 GB/文件）
- **ERA5 SMCI**: 土壤水分气候指数，.nc 格式，~2.8 GB/文件
- **GPM/TRMM**: 降水数据，.nc 格式

### 3.4 地形与土地覆盖
- **DEM**: 数字高程模型，.tif 格式
- **MCD12Q1**: MODIS 土地覆盖，sinusoidal 投影，463.3m 分辨率，IGBP 分类 (1-17)
- **CLCD**: 中国土地覆盖动态，EPSG:4326，~30m 分辨率，值 0-9

## 4. 本地数据组织方案

### 4.1 当前目录结构（全部英文命名，已完成重组）

所有中文目录已重命名为英文。当前 `I:\Geograph_DataSet\` 结构:

| 目录 | 文件数 | 大小 | 内容说明 | 来源 |
|------|--------|------|----------|------|
| `AdminBoundary/` | 211 | — | 行政边界矢量 | 原有（原"行政区数据"） |
| `Biomass/` | 0 | 0 | 生物量（待下载 ESACCI-BIOMASS） | 远程 |
| `CO2/` | 7416 | — | OCO2、中层二氧化碳柱浓度 | 原有（原"二氧化碳数据"） |
| `DEM/` | 9 | — | GEBCO_2024、Italy_DEM | 原有 |
| `ForestHeight/` | 0 | 0 | 森林高度（待下载） | 远程 |
| `Gosat/` | 276 | — | GOSAT L2/L4 CO2 数据 | 原有 |
| `Hazards/` | 7340 | — | DWAA干旱、滑坡、自然灾害统计 | 原有（原"灾害数据"） |
| `HumanFootprint/` | 3 | 2146 MB | hfp2018-2020.tif | 远程 |
| `InversionResults/` | 20 | 189 MB | omega .mat (smap_avg + fy_avg) + Landscape Metrics | 远程 |
| `LandCover/` | 4 | 838 MB | MCD12Q1 2019-2021 + CLCD 1997 | 远程 |
| `Others/` | 1 | 0.1 MB | AridityIndex | 远程 |
| `Precipitation/` | 3 | 231 MB | China 1km 降水 2002-01~03 | 远程 |
| `River/` | 0 | 0 | 河流数据（待下载） | 远程 |
| `SAR/` | 0 | 0 | 雷达数据（待下载） | 远程 |
| `SMAP/` | 5 | 174 MB | SMAP L3 SM HDF5 (2022-2023) | 远程 |
| `Soil_Ecological_Data/` | 10766 | — | DDCA、2m温度、森林变化、WHU_CLCD | 原有 |
| `Station/` | 322430 | 16472 MB | ISD-Lite + ISMN/FLUX 匹配 | 原有+远程 |
| `Transport/` | 26 | — | 出租车轨迹、通行路号 | 原有（原"交通数据"） |
| `Weather/` | 388 | 18209 MB | CMFD + China 1km tmp + PET/温度/降水 | 原有+远程 |

**子目录结构**:
- `AdminBoundary/China/Admin/` — 中国行政区
- `AdminBoundary/Global/WorldMap_shp/` — 全球地图
- `AdminBoundary/Beijing/ProvinceCityDistrictVillage/` — 北京省市乡村
- `AdminBoundary/Guangzhou/` — 广州
- `CO2/MidLayerCO2Column/` — 中层二氧化碳柱浓度
- `Hazards/ChinaDisasterStats/` — 全国自然灾害统计
- `Hazards/GlobalCompoundDisaster_1980_2020/` — 全球复合灾害（含 Flood/Typhoon/Earthquake 等子目录）
- `Hazards/DroughtIndex/` — 干旱指数
- `Hazards/Landslide/` — 滑坡数据（含 6 个子目录）
- `Hazards/FireData/` — 火灾数据
- `InversionResults/smap_avg/` — omega SMAP 平均（14 个 doy_*.mat）
- `InversionResults/fy_avg/` — omega FY 平均（6 个 doy_*.mat）
- `Station/China_Station_Rainfall/` — 全国观测站降雨数据（含 DataDescription/Guangzhou 子目录）
- `Station/Global_20yr/` — 近 20 年全球数据
- `Transport/Taxi_RoadNumber/` — 出租车通行路号
- `Weather/Temperature/` — 温度数据
- `Weather/Precipitation/` — 降水数据（含 ChinaData/dataset 子目录）
- `Weather/PET/` — 蒸散发数据
- `Soil_Ecological_Data/WHU_CLCD_1985_2023/` — 武汉大学 CLCD

### 4.2 新增目录（用于远程数据下载）

```
I:\Geograph_DataSet\
├── SMAP\                    # 土壤水分（SMAP HDF5）✓ 已下载 5 个文件
├── Biomass\                 # 生物量（ESACCI-BIOMASS .nc）待下载
├── ForestHeight\            # 森林高度 待下载
├── HumanFootprint\          # 人类足迹 ✓ 已下载 3 个文件（hfp2018 不完整）
├── SAR\                     # 雷达数据 待下载
├── InversionResults\        # 反演结果 ✓ 已下载 20 个文件
│   ├── smap_avg\            #   omega SMAP 平均 (14 文件)
│   ├── fy_avg\              #   omega FY 平均 (6 文件)
│   ├── Landscape_Metrics_LandOnly_9KM_2020.mat
│   └── Forest_Ratio_9KM_2020.mat
├── Precipitation\           # 降水 ✓ 已下载 3 个文件
├── LandCover\               # 土地覆盖 ✓ 已下载 4 个文件
├── Station\                 # 站点观测 ✓ 已下载 ISMN_vs_Fluxnet2015.csv
├── River\                   # 河流数据 待下载
└── Others\                  # 其他 ✓ 已下载 AridityIndex
```

### 4.3 数据下载优先级

**高优先级（植被与土壤研究核心数据）**:
1. ✓ SMAP 土壤水分数据 (.h5) — 5 个文件，174 MB
2. ⏳ ESACCI-BIOMASS 生物量数据 (.nc) — 17.3 GB/文件
3. ⏳ Forest_height_2019 森林高度 (.tif) — ~30 GB
4. ✓ ISMN/FLUX 站点匹配数据 — 1 个 CSV
5. ✓ omega 反演结果 (.mat) — 20 个文件

**中优先级（辅助数据）**:
6. ⏳ ALOS PALSAR 数据 (.tif)
7. ⏳ Sentinel-1 SAR 数据 (.tif)
8. ✓ 土地覆盖数据 (MCD12Q1 + CLCD) — 4 个文件
9. ⏳ DEM 地形数据
10. ✓ Human Footprint 数据 — 3 个文件（hfp2018 需重新下载）

**低优先级（按需下载）**:
11. ⏳ GLDAS/ERA5 气象数据 (.csv) — 351 GB（体积过大，建议远程处理）
12. ✓ China 1km 降水/温度 — 6 个文件
13. ⏳ 行政区划数据

## 5. 数据检查结果

### 5.1 SMAP HDF5 (土壤水分)

**文件**: `SMAP_L3_SM_P_20230110_R18290_001.h5` (30.9 MB)
**格式**: HDF5, 包含 `Soil_Moisture_Retrieval_Data_AM` 和 `_PM` 两个组
**网格**: 406 × 964 (EASE-Grid 2.0)
**坐标系**: 包含 latitude/longitude 变量（不是 lat/lon）

**关键反演变量（AM 组）**:
| 变量名 | 形状 | 数据类型 | 值范围 | 说明 |
|--------|------|----------|--------|------|
| soil_moisture | (406, 964) | float32 | 0-0.79 | 土壤水分 (m³/m³) |
| surface_temperature | (406, 964) | float32 | 0-311.5 | 地表温度 (K) |
| tb_h_corrected | (406, 964) | float32 | 0-311.1 | 校正后水平极化亮温 (K) |
| tb_v_corrected | (406, 964) | float32 | 0-339.2 | 校正后垂直极化亮温 (K) |
| vegetation_water_content | (406, 964) | float32 | 0-19.11 | 植被含水量 (kg/m²) |
| clay_fraction | (406, 964) | float32 | 0-0.601 | 黏粒含量 (fraction) |
| bulk_density | (406, 964) | float32 | 0-1.72 | 容重 (g/cm³) |
| albedo | (406, 964) | float32 | 0-0.1 | 反照率 |
| roughness_coefficient | (406, 964) | float32 | 0-9.89 | 粗糙度系数 |
| static_water_body_fraction | (406, 964) | float32 | 0-1 | 水体比例 |
| vegetation_opacity | (406, 964) | float32 | 0-2.39 | 植被不透明度 |
| latitude | (406, 964) | float32 | -90 to 83.63 | 纬度 |
| longitude | (406, 964) | float32 | -180 to 180 | 经度 |

**填充值**: -9999 (所有 float32 变量)
**注意事项**: 
- 变量名为 `latitude`/`longitude`（不是 `lat`/`lon`），系统别名需添加
- `sand_fraction` 不存在（SMAP 只提供 clay_fraction）
- PM 组变量名带 `_pm` 后缀

### 5.2 omega .mat v7.3 (反演结果)

**格式**: MAT v7.3 (HDF5-based)，h5py 可正常读取
**文件**: `InversionResults/smap_avg/doy_017.mat` (3.25 MB)

**变量**:
| 变量名 | 形状 | 数据类型 | 值范围 | 说明 |
|--------|------|----------|--------|------|
| OMEGA_AVG | (3856, 1624) | float32 | 0-1 | omega 平均值 |
| count_grid | (3856, 1624) | uint16 | 0-10 | 有效年数 |
| used_years | (1, 1) | float64 | 10 | 使用的年数 |

**SMAP avg vs FY avg**:
- smap_avg: 14 个文件 (doy_017~030)，OMEGA_AVG mean ≈ 0.099
- fy_avg: 6 个文件 (doy_025~030)，OMEGA_AVG mean ≈ 0.134

### 5.3 CMFD NetCDF (月度气象数据)

**文件**: `lrad_CMFD_V0106_B-01_01mo_010deg_197901-201812.nc` (256.4 MB)
**来源**: 中国科学院青藏高原研究所 ITPCAS 数据融合系统
**时间范围**: 1979-01 到 2018-12（480 个月）
**空间范围**: 400 (lat) × 700 (lon)，0.1° 分辨率，中国区域

**变量**:
| 变量名 | 形状 | 数据类型 | 单位 | 说明 |
|--------|------|----------|------|------|
| lrad | (480, 400, 700) | int16 | W m-2 | 地表向下长波辐射 |
| srad | (480, 400, 700) | int16 | W m-2 | 地表向下短波辐射 |
| lat | (400,) | float32 | degrees_north | 纬度 |
| lon | (700,) | float32 | degrees_east | 经度 |
| time | (480,) | float64 | hours since 1900-1-1 | 时间 |

**编码**: int16 with scale_factor=0.25, add_offset=685.0, _FillValue=-32767

### 5.4 MCD12Q1 GeoTIFF (土地覆盖)

**文件**: `MCD12Q1_2019.tif` (18.2 MB)
**格式**: GeoTIFF, uint8, 1 band
**网格**: 40800 × 19201
**坐标系**: Sinusoidal (MODIS)，463.31m 分辨率
**范围**: X=[-3335851.56, 15567307.28], Y=[0, 8896067.47]
**值**: 1-17 (IGBP 分类), NoData=255
**有效像素**: 30.9% (241,920,000 / 783,400,800)
**注意**: 不是 WGS84 投影，使用时需重投影

### 5.5 CLCD GeoTIFF (中国土地覆盖动态)

**文件**: `CLCD_v01_1997.tif` (783.4 MB)
**格式**: GeoTIFF, uint8, 1 band
**网格**: 228579 × 131361
**坐标系**: EPSG:4326 (WGS84)，~30m 分辨率 (0.000269°)
**范围**: X=[73.49, 135.09], Y=[18.16, 53.56] (中国区域)
**值**: 0-9 (CLCD 分类)
**注意**: 文件较大，读取时建议分块

### 5.6 China 1km GeoTIFF (降水/温度)

**文件**: `pre_2002_01.tif` (77.1 MB), `tmp_2002_01.tif` (77.1 MB)
**来源**: 彭守彰 "1km monthly temperature and precipitation dataset for China from 1901 to 2017" (ESSD, 2019)
**格式**: GeoTIFF, int16, 1 band
**网格**: 7849 × 5146
**坐标系**: EPSG:4326 (WGS84)，~1km 分辨率 (0.008333°)
**范围**: X=[71.29, 136.69], Y=[15.75, 58.64] (中国区域)
**值**:
- 降水 (pre): 0-4875，**单位 0.1mm** (实际值 0-487.5mm)
- 温度 (tmp): -432 to 316，**单位 0.1℃** (实际值 -43.2~31.6℃)
**NoData**: -32768
**有效像素**: 80.7%
**远程数据**: 2000-2024 年共 301 个月 (pre_tif/ + tmp_tif/)

### 5.7 Human Footprint GeoTIFF

**文件**: `hfp2019.tif`, `hfp2020.tif` (各 546.2 MB)
**格式**: GeoTIFF, float32, 1 band
**网格**: 36081 × 16382
**坐标系**: ESRI:54009 (Mollweide 投影)，1000m 分辨率
**范围**: 全球覆盖
**值**: 0-50 (人类足迹指数), NoData=nan
**有效像素**: 22.7% (134,154,306 / 591,078,942)，其余为海洋 nan

**hfp2018.tif**: ✓ 已重新下载完成 (2255.0 MB，36081×16382，22.7% finite，值 0-50，mean 7.56)

### 5.8 AridityIndex GeoTIFF

**文件**: `AridityIndex_MSWEP-prcp_div_GLEAM-Ep_1980-2020.tif` (0.12 MB)
**格式**: GeoTIFF, float32, 1 band
**网格**: 360 × 180 (1° 分辨率)
**坐标系**: EPSG:4326 (WGS84)
**范围**: 全球
**值**: -239329.77 to 328274.97 (含异常值，实际有效范围待确认)
**NoData**: -3.4e+38

### 5.9 ISMN vs FLUXNET CSV (站点匹配)

**文件**: `ISMN_vs_Fluxnet2015.csv` (0.03 MB)
**行数**: 101 (101 个站点)
**列数**: 31

**主要列**:
| 列名 | 说明 |
|------|------|
| network | ISMN 网络 |
| station | 站点名 |
| latitude, longitude | 站点经纬度 |
| start_year, end_year | 数据起止年 |
| smap_lat, smap_lon | SMAP 网格坐标 |
| MAP | 年平均降水 (Mean Annual Precipitation) |
| MAT | 年平均温度 (Mean Annual Temperature) |
| MEAN_PET | 平均潜在蒸散发 |
| AI | 干燥度指数 |
| LAI_max, LAI_mean | 叶面积指数最大值/平均值 |
| SITE_ID_Fluxnet | FLUXNET 站点 ID |
| IGBP_Fluxnet | FLUXNET IGBP 分类 |
| Matched_Distance_km | 匹配距离 (km) |

### 5.10 Landscape Metrics .mat

**文件**: `Landscape_Metrics_LandOnly_9KM_2020.mat` (119.4 MB)
**格式**: MAT v5 (scipy.io.loadmat 可读)
**变量**: PD, ED, SHDI, CONTAG, Forest_Ratio (景观格局指数)

**文件**: `Forest_Ratio_9KM_2020.mat` (23.9 MB)
**格式**: MAT v5
**变量**: Forest_Ratio (森林比例)

### 5.11 ERA5 SMCI NetCDF (土壤水分气候异常指数)

**文件**: `ERA5_2018_SMCI-T7.nc`, `ERA5_2019_SMCI-T7.nc`, `ERA5_2020_SMCI-T7.nc` (各 ~2.8 GB)
**格式**: NetCDF, 包含 4 个变量
**网格**: 365 天 × 721 lat × 1440 lon (0.25° 全球)

**变量**:
| 变量名 | 形状 | 数据类型 | 单位 | 说明 |
|--------|------|----------|------|------|
| time | (365,) | str | "YYYYMMDD" | 日期字符串，如 "20180101" |
| lat | (721,) | float32 | degrees_north | 纬度 90 to -90，步长 -0.25 |
| lon | (1440,) | float32 | degrees_east | 经度 0 to 359.75，步长 0.25 |
| SMCI | (365, 721, 1440) | float64 | — | 土壤水分气候异常指数 |

**值范围**: -0.93 to 0.92 (SMCI 异常指数，正值偏湿，负值偏干)
**填充值**: nan (_FillValue=nan)
**注意事项**:
- Day 0 (1月1日) 全 NaN，其余天 100% 有效像素
- `time` 为字符串类型，非标准 CF 时间编码，读取时需解析 "YYYYMMDD" 格式
- 变量名 `SMCI`，T7 表示 7 层土壤温度合成方案
- 全球 0.25° 分辨率，中国区域裁剪范围: lat[15.75, 58.64], lon[73.49, 136.69]

### 5.12 SMAP L3 SM P 2周序列 (2023-01)

**文件**: 14 个 `SMAP_L3_SM_P_202301*.h5` (2023-01-01 ~ 2023-01-31，共 242.4 MB)
**日期列表**: 20230101, 20230103, 20230105, 20230107, 20230109, 20230112, 20230114, 20230115, 20230120, 20230122, 20230124, 20230127, 20230130, 20230131
**格式**: 同 Section 5.1 (HDF5, 406×964 EASE-Grid 2.0)
**用途**: 日尺度土壤水分反演测试，验证 SMAP 数据读取流程
**完整 SMAP 目录**: 19 个文件 (14 L3 SM P 2周 + 1 L3 SM P_E 2022-09 + 4 原有其他文件)，共 568 MB

### 5.13 ESACCI-BIOMASS NetCDF (地上生物量)

**文件**: `ESACCI-BIOMASS-L4-AGB-MERGED-100m-2020-fv6.0.nc` (17302.2 MB, ✓ 完整下载)
**来源**: ESA CCI Biomass project, GAMMA Remote Sensing
**平台**: ALOS-2 PALSAR-2 + Sentinel-1A/B SAR-C
**格式**: NetCDF4 (CF-1.7), EPSG:4326 (WGS84)
**网格**: 1 × 157500 lat × 405000 lon (100m 分辨率, 0.00088889°)
**范围**: lat[-60, 80], lon[-180, 180] (全球陆地)
**时间**: 2020-01-01 ~ 2020-12-31 (days since 1990-01-01, value=10957)

**变量**:
| 变量名 | 形状 | 数据类型 | 单位 | 说明 |
|--------|------|----------|------|------|
| agb | (1, 157500, 405000) | int16 | Mg/ha | 地上生物量 |
| agb_sd | (1, 157500, 405000) | int16 | Mg/ha | 生物量标准差 |
| lat | (157500,) | float64 | degrees_north | 纬度 80 to -60 |
| lon | (405000,) | float64 | degrees_east | 经度 -180 to 180 |
| time | (1,) | float64 | days since 1990-01-01 | 时间 |
| crs | () | — | — | 坐标系定义 (WGS84) |

**值范围**: 0 ~ 406 Mg/ha (采样块统计)
**填充值**: -32768 (int16)
**有效像素**: 58.3% (赤道附近采样块)
**统计**: 均值 10.31 Mg/ha, 标准差 31.69 Mg/ha
**注意事项**:
- 文件巨大 (17.3 GB)，建议按区域裁剪后使用
- int16 存储，无 scale_factor，值为实际 Mg/ha
- 中国区域裁剪: lat[15.75, 58.64], lon[73.49, 136.69]

### 5.14 通用读取验证结果汇总 (UniversalDataReader)

> 验证时间: 2026-07-15
> 验证脚本: `Tools/verify_all_datasets.py` + `Tools/verify_datasets_supplement.py` + `Tools/verify_datasets_final.py`
> 报告路径: `Tools/reports/dataset_verification.json`, `dataset_verification_supplement.json`, `dataset_verification_final.json`
> 中国区域 bbox: (73.0, 15.0, 137.0, 59.0)

#### 验证结果总览

| # | 数据集 | 格式 | 状态 | 有效率 | 值域 | 均值 | 备注 |
|---|--------|------|------|--------|------|------|------|
| 1 | SMAP L3 SM P 20230110 | HDF5 | ✅ | 12.3% | [0.02, 0.64] | 0.265 | 中国区域 121×172, SM m³/m³ |
| 2 | MCD12Q1 2020 | GeoTIFF | ✅ | 69.8% | [1, 17] | 12.26 | Sinusoidal 投影, IGBP 分类 |
| 3 | HFP 2020 | GeoTIFF | ✅ | 63.2% | [0, 50] | 9.52 | ESRI:54009 Mollweide, 中国区域 4934×8615 |
| 4 | InversionResults smap_avg doy_017 | MAT v7.3 | ✅ | 13.7% | [0, 1] | 0.099 | OMEGA_AVG 变量 (非 omega) |
| 5 | GEBCO 2024 DEM | NetCDF | ✅ | 100% | [-8403, 8627] | 495.16 | elevation 变量, 中国区域 10560×15361 |
| 6 | Italy DEM GEBCO2024 | GeoTIFF | ✅ | 100% | [-4450, 4655] | -427.30 | EPSG:4326, 3000×3120 (意大利区域) |
| 7 | CMFD Precipitation 2002-01 | GeoTIFF | ✅ | 80.6% | [0, 4875] | 151.55 | int16, 单位 0.1mm, 5146×7644 |
| 8 | CMFD Precipitation 2002-02 | GeoTIFF | ✅ | 80.6% | [0, 3491] | 117.44 | 2月降水较低, 符合季节规律 |
| 9 | CLCD 1997 | GeoTIFF | ✅* | 100% | [0, 9] | — | *需分块读取, 北京窗口采样验证 |
| 10 | ESACCI BIOMASS 2020 | NetCDF | ✅* | 100% | [0, 563] | 27.27 | *需分块读取, 中国区域 49500×72000 |
| 11 | ERA5 DWAA SMCI 2020 | GeoTIFF | ✅ | 0.1% | {0,1} | — | 事件标识层, 366波段, uint8 |
| 12 | ERA5 WDAA SMCI 2020 | GeoTIFF | ✅ | 0.1% | {0,1} | — | 事件标识层, 366波段, uint8 |
| 13 | MeanCarbonDioxide | GeoTIFF | ✅ | 100% | [386.38, 390.61] | 388.85 | 2.5°×2.0° 低分辨率, 22×26 |
| 14 | Soil DDCA 20150401 | MAT v5 | ✅ | 5.9% | [0, 3] | 0.587 | DH 变量, 1624×3856 |
| 15 | InversionResults fy_avg doy_025 | MAT v7.3 | ✅ | 13.4% | [0, 1] | 0.134 | OMEGA_AVG, fy_avg > smap_avg |
| 16 | Forest_Ratio_9KM_2020 | MAT v5 | ✅ | 27.3% | [0, 1] | 0.168 | 森林比例, 9km 网格 |

#### ERA5 DWAA 辅助文件验证 (2020年 band 100)

| 文件 | dtype | bands | nodata | 有效像素 | 值域 | 均值 | 说明 |
|------|-------|-------|--------|----------|------|------|------|
| DW_SMCI | uint8 | 366 | 255 | 29/45056 | {1} | — | 事件标识 (0/1/255) |
| DW_duration | uint16 | 366 | 65535 | 29/45056 | [1, 2] | 1.03 | 过渡期天数 (0-5天) |
| DW_intensity | float32 | 366 | -3.4e38 | 29/45056 | [0.12, 0.80] | 0.31 | SMA变化量/天 |
| DW_start_date | uint16 | 366 | 65535 | 29/45056 | [94, 97] | 95.52 | 年内第N天 (0-based) |
| DW_end_date | uint16 | 366 | 65535 | 29/45056 | [103, 106] | 104.93 | 年内第N天 (0-based) |

#### 关键发现与已知问题

1. **InversionResults smap_avg 变量名**: 变量名是 `OMEGA_AVG`，不是 `omega`。脚本中已修正。
2. **CLCD 大文件内存问题**: 228579×131361 uint8 = 28 GiB，`UniversalDataReader` 转 float64 需 224 GiB。
   - **解决方案**: 使用 rasterio 窗口读取 (`from_bounds` + `intersection`)，保持 uint8 dtype。
   - **采样验证** (北京窗口 110-120°E, 35-45°N): 37106×37106, 100% 有效, 值分布: 1(森林)=483M, 4(草地)=554M, 0(耕地)=103M, 2(灌木)=144M, 8(湿地)=65M。
3. **ESACCI BIOMASS 大文件内存问题**: 157500×405000 int16 = 1.28 TB，bool mask 需 3.28 GiB。
   - **解决方案**: 分块读取 (chunk_size=5000 行)，逐块统计后聚合。
   - **中国区域**: 49500×72000 = 3.56G 像素, 100% 有效, 值域 [0, 563] Mg/ha, 均值 27.27。
4. **ERA5 DWAA/WDAA SMCI 数据特性**: 这是**事件标识层**，不是连续的 SMCI 值。
   - 366 波段对应 366 天 (2020 闰年)
   - 值: 0=无事件, 1=有DW事件 (SMCI极小值点), 255=无数据
   - band_1 (1月1日) 全 NaN 是正常现象 (年初无足够数据计算极小值)
   - 大部分像素为 0 或 255，值为 1 的像素稀疏 (事件点)
   - 辅助文件 (duration/intensity/start_date/end_date) 仅在事件点有有效值
5. **Italy DEM 坐标缺失**: `UniversalDataReader` 未返回 lat/lon (transform 解析问题)，但数据本身正常 (3000×3120, EPSG:4326)。
6. **GEBCO 2024 DEM CRS 异常**: 返回 `"EPSG:EPSG:4326"` (重复前缀)，是 NetCDF crs 变量的 epsg_code 属性格式问题。
7. **BIOMASS scale_factor**: `attrs.get('scale_factor')` 返回 None，int16 值即为实际 Mg/ha，无需缩放。

#### UniversalDataReader 改进建议

1. **GeoTIFF 分块读取**: 当前 `_read_geotiff` 一次性读取整个窗口并转 float64，对大文件 (CLCD 783MB) 会 OOM。建议添加 `window` 参数支持 rasterio 窗口读取，保持原 dtype。
2. **NetCDF 分块读取**: 当前 `_read_netcdf` 对 3D 数据 (BIOMASS 17.3GB) 创建全尺寸 bool mask。建议对大数组使用分块迭代统计。
3. **MAT 文件变量自动选择**: 已在验证脚本中实现 (跳过坐标变量，选第一个数据变量)，建议集成到 `UniversalDataReader.read_variable(variable=None)`。
4. **GeoTIFF 坐标解析**: Italy DEM 的 transform 分辨率显示为 0.00 (实际 0.004165)，需检查 rasterio transform 解析逻辑。

## 6. 系统集成方案

### 6.1 已支持的格式适配器
| 格式 | 适配器 | Python 库 | 说明 |
|------|--------|-----------|------|
| .tif/.tiff | GeoTIFFAdapter | rasterio | 支持 COG、裁剪、重投影 |
| .nc | NetCDFAdapter | netCDF4, scipy.io | 支持 HDF5 和 NetCDF4 |
| .hdf/.h5/.he5 | HDF5Adapter | h5py | 支持 SMAP HDF5 |
| .mat | MATAdapter | scipy.io, h5py | 自动检测 v5/v7.3 |
| .csv | CSVAdapter | pandas | 表格数据 |
| .shp | ShapefileAdapter | geopandas | 矢量数据 |

### 6.2 变量别名配置
系统支持通过 `DailyBundleConfig` 配置变量别名。✓ 已更新 (2026-07-14):
- TBv: `("TBv", "tbv", "tb_v_corrected")` — 添加 SMAP HDF5 原生变量名
- TBh: `("TBh", "tbh", "tb_h_corrected")` — 添加 SMAP HDF5 原生变量名
- Ts: `("Ts", "ts", "surface_temperature")` — 添加 SMAP HDF5 原生变量名
- SM: `("sm_dca", "SM", "sm", "soil_moisture")` — 添加 SMAP HDF5 原生变量名
- CF: `("CF", "clay_fraction")` — 添加 SMAP HDF5 原生变量名
- Lat: `("lat_9km", "lat", "latitude")` — 添加通用和 SMAP HDF5 变量名
- Lon: `("lon_9km", "lon", "longitude")` — 添加通用和 SMAP HDF5 变量名
- VWC: `("vwc", "vegetation_water_content")` — 添加 SMAP HDF5 原生变量名
- OMEGA: `("OMEGA_AVG",)` — 在 INVERSION_OMEGA_SMAP/FY 数据集中注册

### 6.3 数据接入步骤
1. 将远程数据下载到 `I:\Geograph_DataSet\{Category}\`
2. 在 `dataset_config.py` 中注册数据集路径映射
3. 配置变量别名（如使用非标准变量名）
4. 创建工作流预设（指定数据源、时间范围、研究区域）
5. 通过 `/workflow-runs` API 提交反演任务

## 7. 远程数据访问

### 7.1 FileBrowser API
- **登录**: `POST /api/login` → 返回 JWT token
- **列目录**: `GET /api/resources/{path}` → 返回 items 列表
- **下载文件**: `GET /api/raw/{path}` → 返回文件内容
- **必需头**: `User-Agent`（Cloudflare 隧道要求）
- **超时建议**: 大文件 (>1GB) 需设置 600s+ 超时

### 7.2 扫描工具使用
```bash
# 快速扫描（深度 3）
python remote_data_scanner.py scan --quick

# 标准扫描（深度 4）
python remote_data_scanner.py scan

# 只扫描 NAS
python remote_data_scanner.py scan --server nas --quick

# 下载精选数据
python download_curated.py            # 48 个精选文件（小文件）
python download_resumable.py hfp      # hfp2018 重下（断点续传）
python download_resumable.py era5     # ERA5 SMCI 3 年（断点续传）
python download_resumable.py biomass  # ESACCI-BIOMASS（17.3 GB）
python download_resumable.py          # 全部待下载文件
```

## 8. 下载状态汇总

### 8.1 已完成下载（65 个文件）

| 目录 | 文件 | 大小 | 状态 |
|------|------|------|------|
| SMAP | 14 个 .h5 (L3 SM P 2023-01 两周序列) | 242 MB | ✓ 完成 (8 新 + 6 已有) |
| SMAP | 5 个 .h5 (原有 L3 SM P + L3 SM P_E 2022-09) | 326 MB | ✓ 完成 |
| Weather | 3 个 ERA5 SMCI .nc (2018/2019/2020) | 8409 MB | ✓ 完成 (断点续传) |
| Weather | 2 个 CMFD .nc (lrad, srad 1979-2018) | 513 MB | ✓ 完成 |
| Weather | 3 个 China 1km tmp .tif (2002-01~03) | 231 MB | ✓ 完成 |
| Biomass | ESACCI-BIOMASS-L4-AGB-MERGED-100m-2020.nc | 17302 MB | ✓ 完成 (断点续传, 100%) |
| HumanFootprint | hfp2018.tif, hfp2019.tif, hfp2020.tif | 3238 MB | ✓ 完成（hfp2018 已重下 2255 MB） |
| LandCover | 3 个 MCD12Q1 .tif (2019-2021) | 55 MB | ✓ 完成 |
| LandCover | CLCD_v01_1997.tif | 783 MB | ✓ 完成 |
| Precipitation | 3 个 China 1km pre .tif (2002-01~03) | 231 MB | ✓ 完成 |
| InversionResults/smap_avg | 14 个 omega .mat (doy 017-030) | 46 MB | ✓ 完成 |
| InversionResults/fy_avg | 6 个 omega .mat (doy 025-030) | 20 MB | ✓ 完成 |
| InversionResults | Landscape_Metrics + Forest_Ratio .mat | 143 MB | ✓ 完成 |
| Station | ISMN_vs_Fluxnet2015.csv | 0.03 MB | ✓ 完成 |
| Others | AridityIndex .tif | 0.12 MB | ✓ 完成 |

### 8.2 下载中

（无）

### 8.3 待决定

| 文件 | 远程大小 | 说明 |
|------|----------|------|
| Forest_height_2019 (按大洲) | ~30 GB | 需选择研究区域（SAM/SAFR/NAM/SASIA/NASIA/NAFR），用户已决定暂不下载 |
| ALOS PALSAR | ~30 文件, 256 KB/文件 | 小文件，可按需下载 |
| Sentinel-1 SAR | 大量 | 需选择时间/区域 |

### 8.4 下载注意事项

1. **断点续传**: 已实现 HTTP Range 断点续传，支持中断后恢复（`download_resumable.py`）
2. **超时设置**: 大文件使用 3600s 超时，3 次重试，指数退避
3. **下载速度**: 约 1.3-3.3 MB/s（Cloudflare 隧道带宽限制，速度波动）
4. **并发限制**: 同一时间只能运行一个下载任务（带宽争抢）

## 9. 待确认事项

1. **研究区域**: ✓ 已确认 — 中国区域
2. **时间范围**: 需要确认研究时间范围，以便筛选时间序列数据
3. ~~ERA5 SMCI 数据~~: ✓ 已确认 — 变量 SMCI (float64)，值 -0.93~0.92，365天日数据，0.25° 全球
4. ~~China 1km 数据单位~~: ✓ 已确认 — 降水 0.1mm, 温度 0.1℃ (彭守彰数据集)
5. **AridityIndex 异常值**: 值范围包含 -239329 和 328274 等异常值，需确认有效范围
6. ~~BIOMASS 下载~~: ✓ 已完成 — 17.3 GB, 100% 完整, int16, 100m 分辨率, agb 变量 0-406 Mg/ha
7. **GLDAS/ERA5 CSV**: 351 GB 气象数据体积过大，建议在远程服务器上处理
8. **SMAP 2周数据**: ✓ 已完成 — 14 个文件 (2023-01-01 ~ 2023-01-31)
9. **ERA5 3年数据**: ✓ 已完成 — 2018/2019/2020 共 8.4 GB

## 10. 扫描报告文件

- **NAS 完整报告**: `Tools/reports/scan_report_20260714_084037.json`
- **Win11 检查点**: `Tools/reports/checkpoint_win11_20260714_072044.json`
- **NAS 检查点**: `Tools/reports/checkpoint_nas_20260714_084037.json`
- **下载候选清单**: `Tools/reports/download_candidates.json` (207 文件, 154.1 GB)
- **数据检查报告**: `Tools/reports/data_inspection.json`

> 注: Win11 服务器扫描未完成（目录结构非常宽，深度 2 有 3591+ 目录），但已获取足够数据用于规划。

---

## 11. 实际项目规划（2026-07-15 制定，待用户确认）

> 本章为进入实际项目阶段的执行规划，确认后开始实施。

### 11.1 项目目标

**核心目标**: 在中国区域生产 2023 年 1 月两周的日尺度 Omega（植被光学厚度）反演产品，并对多源遥感数据做交叉分析与站点验证。

**子目标**:
1. **反演生产**: 用 SMAP L3 SM 数据 + 现有 `omega_block` 算法生产日尺度 Omega 时间序列（14 天）
2. **空间对齐**: 将 BIOMASS / MCD12Q1 / HFP / AridityIndex 重采样到 0.25° WGS84 中国网格，与 SMAP/ERA5 共格
3. **交叉分析**: 分析 Omega/SMAP SM 与 BIOMASS、土地覆盖、ERA5 SMCI 的相关性
4. **站点验证**: 用 ISMN/FLUXNET 站点观测验证 SMAP SM 反演结果
5. **可视化报告**: 产出空间地图、时间序列、散点图、分区统计图表

### 11.2 研究区与坐标系

| 项目 | 值 |
|------|-----|
| 研究区 | 中国区域 |
| bbox | lat[15.0, 59.0], lon[73.0, 137.0] |
| 目标网格 | 0.25° WGS84 (与 ERA5/SMAP 对齐) |
| 网格形状 | 176 lat × 256 lon |

### 11.3 数据清单（已就绪）

| 数据集 | 文件 | 时间 | 用途 |
|--------|------|------|------|
| SMAP L3 SM P | 14 个 .h5 (2023-01-01 ~ 01-31) | 2023-01 两周 | Omega 反演主输入（SM/Ts/TBh/TBv/VWC/CF） |
| ERA5 SMCI | 3 个 .nc (2018/2019/2020) | 3 年日数据 | SM 气候异常对比 |
| ESACCI-BIOMASS | 1 个 .nc (2020) | 2020 | 植被生物量交叉分析 |
| MCD12Q1 | 3 个 .tif (2019-2021) | 2019 | IGBP 分区统计 |
| Human Footprint | 3 个 .tif (2018-2020) | 2019 | 人为干扰分析 |
| AridityIndex | 1 个 .tif | 1980-2020 | 干燥度分区 |
| InversionResults/smap_avg | 14 个 .mat (doy 017-030) | 历史均值 | Omega 反演结果对比 |
| ISMN_vs_Fluxnet | 1 个 .csv (101 站点) | 多年 | SMAP SM 验证 |

### 11.4 工作流阶段

**阶段 1: 数据预处理（DataPreprocessor）**
- 输入: SMAP HDF5 14 天数据
- 输出: 14 个日尺度 .mat 文件（SM/Ts/TBh/TBv/VWC/CF/lat/lon）
- 中国区域裁剪: bbox=[73, 15, 137, 59]
- 关键文件: [data_preprocessor.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/data_access/data_preprocessor.py)

**阶段 2: 多源数据空间对齐（SpatialAligner）**
- 目标: 0.25° WGS84 中国网格 (176×256)
- 对齐数据:
  - ESACCI-BIOMASS (100m → 0.25°, 双线性)
  - MCD12Q1 (463m Sinusoidal → 0.25° WGS84, 众数重采样)
  - HFP (1000m Mollweide → 0.25° WGS84, 双线性)
  - AridityIndex (1° → 0.25°, 最近邻)
- 输出: 对齐后的 .mat 文件
- 关键文件: [spatial_aligner.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/data_access/spatial_aligner.py)

**阶段 3: Omega 反演生产**
- 输入: 阶段 1 的日尺度 .mat
- 算法: 现有 `omega_block` 模块（双温度方案 DUAL）
- 输出: 14 天的 OMEGA .mat 时间序列
- 对比: 与 InversionResults/smap_avg 历史均值对比

**阶段 4: 交叉分析（Analysis 模块）**
- 4.1 相关性分析: SMAP SM vs BIOMASS / HFP / AridityIndex（逐像素 Pearson）
- 4.2 分区统计: Omega/SM 按 IGBP 土地覆盖类型统计均值/标准差
- 4.3 时间趋势: ERA5 SMCI 2018-2020 三年趋势（Mann-Kendall）
- 4.4 时空异常: SMAP SM 14 天异常值识别
- 关键文件: [analysis/](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/analysis)

**阶段 5: 站点验证**
- 输入: ISMN_vs_Fluxnet2015.csv (101 站点) + SMAP SM 14 天数据
- 流程: 提取站点对应 SMAP 像元 → 与 ISMN 观测对比
- 指标: R, RMSE, Bias
- 输出: 站点级散点图 + 统计表

**阶段 6: 可视化报告**
- 6.1 Omega 14 天时间序列空间地图（14 张 PNG）
- 6.2 多源数据对齐后的中国区域专题图（BIOMASS/LandCover/HFP）
- 6.3 相关性散点图矩阵
- 6.4 IGBP 分区箱线图
- 6.5 站点验证散点图
- 输出目录: `I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion\`

### 11.5 产出清单

| 产出 | 格式 | 数量 | 说明 |
|------|------|------|------|
| 日尺度 Omega .mat | .mat | 14 | 反演产品 |
| 对齐数据集 .mat | .mat | 4 | BIOMASS/LandCover/HFP/AI 在 0.25° 网格 |
| 空间地图 PNG | .png | ~20 | Omega/SM/BIOMASS/LandCover 等 |
| 统计图表 PNG | .png | ~10 | 散点图/箱线图/时间序列 |
| 站点验证报告 | .csv + .png | 2 | R/RMSE/Bias 表 + 散点图 |
| 项目报告 | .md | 1 | 汇总结果与分析结论 |

### 11.6 系统集成点

- **不修改** ProviderManifest / workflow API（避免改动核心系统）
- 以独立脚本 + 模块调用方式执行，产出物写入 `I:\Geograph_DataSet\ProjectOutput\`
- 使用已验证的模块: UniversalDataReader, DataPreprocessor, SpatialAligner, ZonalStats, TrendAnalysis, CorrelationAnalysis, DataVisualization
- Omega 反演通过 `omega_block` 模块直接调用

### 11.7 执行顺序

1. 创建项目输出目录 `I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion\`
2. 编写项目主脚本 `Tools/run_project_omega.py`
3. 阶段 1: 批量 SMAP → .mat 转换（14 天）
4. 阶段 2: 多源数据对齐（4 个数据集）
5. 阶段 3: Omega 反演（调用 omega_block）
6. 阶段 4: 交叉分析
7. 阶段 5: 站点验证
8. 阶段 6: 生成可视化报告
9. 汇总结果到 `ProjectOutput/REPORT.md`

### 11.8 方案调整（2026-07-15 确认）

经探索 omega_block 模块接口和 Station 数据结构，做如下调整：

1. **Omega 反演算法**: ❌ 不直接运行 omega_block — 该算法需要时序束 .mat（含 IA/SMref/NDVI/SF/B/H 等辅助场），SMAP HDF5 仅提供 SM/Ts/TBh/TBv/VWC/CF，缺少 IA/SMref/NDVI/SF/B/H。构建完整时序束需 TimeSeriesBundlePipeline 多源数据组装，超出本期范围。
   - ✅ 改用现有 `InversionResults/smap_avg` (doy 017-030, 14 个 .mat) 作为 omega 产品
2. **Omega 对比基线**: ✅ 与 SMAP SM 14 天数据交叉分析（omega vs SM/Ts 空间相关性）
3. **站点验证数据**: `Station/` 目录是 ISD-Lite 气象数据（非 ISMN 土壤水分观测），无法做 SM 时间序列验证
   - ✅ 改为站点空间采样: 用 ISMN_vs_Fluxnet2015.csv 的 101 站点坐标，提取 SMAP SM 在站点位置的值，按 IGBP 分类统计
4. **输出位置**: ✅ `I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion\`

### 11.9 实际执行阶段（调整后）

| 阶段 | 内容 | 数据来源 | 工具 |
|------|------|----------|------|
| 1 | SMAP 14 天 → .mat | SMAP HDF5 | DataPreprocessor |
| 2 | 多源数据对齐到 0.25° | BIOMASS/MCD12Q1/HFP/AI | SpatialAligner |
| 3 | Omega 产品加载 | InversionResults/smap_avg | UniversalDataReader |
| 4 | 交叉分析 | SM/Omega vs BIOMASS/LandCover/HFP | CorrelationAnalysis + ZonalStats |
| 5 | 站点空间采样 | ISMN_vs_Fluxnet2015.csv (101 站点) | SMAP SM 像元提取 + IGBP 分组 |
| 6 | 可视化报告 | 全部产出 | DataVisualization |

### 11.10 项目执行结果（2026-07-15 完成）

**执行脚本**: `Tools/run_project_omega.py`（605 行）
**总耗时**: 15.9 秒
**输出目录**: `I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion\`

#### 各阶段完成情况

| 阶段 | 结果 | 关键指标 |
|------|------|----------|
| 1. SMAP → .mat | 13/14 天成功 | 20230120 用 `_002` 后缀; 20230131 HDF5 损坏跳过 |
| 2. 多源对齐 | 3/4 数据集成功 | landcover 99.8%, HFP 79.3%, aridity 83.9% 有效; BIOMASS 跳过 (17.3 GB 需分块) |
| 3. Omega 加载 | 14/14 产品成功 | h5py 读取 v7.3 .mat + 转置; doy_017~030, shape=(1624, 3856) |
| 4. 交叉分析 | 7 项结果 | SM 均值 0.254, SM-Ts 相关 r=0.153, IGBP 分布完整 |
| 5. 站点采样 | 37/101 站点有效 | NaN 坐标过滤修复; GRA/OSH 两类 IGBP 有有效采样 |
| 6. 可视化 | 11 张图 | 14 天均值 + 3 专题图 + omega 空间图 + 散点/直方/站点分布 |

#### 关键科学发现

1. **SMAP SM 统计** (2023-01-01 中国区域): mean=0.254 m³/m³, std=0.101, range=[0.020, 0.620]
2. **SM-Ts 相关性**: Pearson r=0.153 (p<0.001, n=1885) — 冬季中国区域 SM 与表面温度弱正相关
3. **IGBP 分布** (0.25° 网格 44974 有效像元):
   - Grassland 22.2%, Water 21.2%, Cropland 12.5%, Barren 10.8%
   - Woody_Savanna 9.6%, Savanna 6.4%, Mixed_Forest 6.1%
4. **Omega 反演产品** (14 天): doy_017~024 均值 0.099±0.061; doy_025~030 均值 0.134±0.146
5. **站点采样**: 37/101 站点获得有效 SM (GRA: 21 站 SM=0.316, OSH: 16 站 SM=0.317)

#### 产出文件清单

```
stage1_smap_mat/          — 13 个 SMAP .mat 文件 (SM/Ts/TBh/TBv/VWC/CF + lat/lon)
stage2_aligned/           — 3 个对齐 .mat (landcover/hfp/aridity, 0.25° WGS84)
stage4_analysis/          — 6 张图 (SM 空间图, SM-Ts 散点, 3 专题图, omega 直方图)
stage5_station/           — 2 CSV + 1 PNG (站点采样结果 + IGBP 分组统计 + 分布图)
stage6_viz/               — 5 张图 (14 天均值, 3 专题图, omega 空间图)
```

#### 修复的 Bug

1. **`universal_reader._read_mat`**: 返回 lat/lon 坐标 (此前返回 None，导致 SpatialAligner 使用错误的简单重采样)
2. **`universal_reader._read_geotiff`**: bbox 窗口读取后存储 `window_transform` (此前存储全数据集 transform，导致 HFP/AI 重投影 0 有效像元)
3. **`visualization.plot_spatial_map`**: 2D 坐标含 NaN 时提取 1D 网格向量 (此前 pcolormesh 崩溃)
4. **Stage 3 omega 加载**: 改用 h5py 读取 v7.3 .mat + 转置 (此前 scipy.io.loadmat 抛 NotImplementedError)
5. **Stage 5 站点采样**: NaN 坐标预过滤 `np.where(np.isfinite(lat), lat, 1e6)` (此前 argmin 选到 NaN 像元导致 0/101 有效)
6. **Stage 6 形状不一致**: 用 SpatialAligner 将每天 SMAP .mat 对齐到 0.25° WGS84 网格后堆叠 (此前不同天形状不同导致 stack 崩溃)
7. **SMAP 20230120 文件名**: glob 查找 `_R18290_*.h5` (实际文件是 `_002` 后缀)

#### 已知限制

- **BIOMASS 17.3 GB**: 157500×405000 网格需分块读取优化，当前一次性读取超内存
- **SMAP 20230131**: HDF5 文件损坏 (metadata checksum 错误)，需重新下载
- **站点采样覆盖率**: 37/101 (36.6%) — 部分站点在 SMAP 中国区域 bbox 外或位于 NaN 像元
