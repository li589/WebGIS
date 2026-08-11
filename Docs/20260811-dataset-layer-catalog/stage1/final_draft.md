# CGDA 综合地理数据分析系统 · 数据集与图层综合对照表

> 面向导师交付的项目数据集 / 图层体系总览
> 编制日期：2026-08-11 ｜ 事实来源：系统图层目录（`Code/backend/app/catalog_seeds/`）、数据源与工作流对照说明、项目现状简报

---

## 一、报告概述（结论先行）

CGDA（综合地理数据分析系统）是面向课题组与大气研究院研究员的科研数据分析平台，以 MapLibre 2D 地图为主链，统一承载多源数据接入（本地 / GEE / Open-Meteo / 商业天气源）、动态时空结果展示与工作流算法编排。

本报告围绕「图层」与「数据集」两大核心概念，交付以下内容：

1. **一张综合对照表**：将系统当前全部 **41 个目录图层** 的图层名称、数据集名称、内部分类、内部 ID 一一对应列出，按 6 大类组织，可直接用于验收与汇报；
2. **一套命名与分类规则**：解释内部 ID（`layer_id`）前缀、数据集标识（`dataset_key`）与分类体系（`category`）的设计逻辑；
3. **一组说明解释**：覆盖数据来源（星 / 地 / 气 / 辅 / 开放）、算法引擎、就绪状态与扩展方式，帮助导师快速理解平台的数据能力。

**关键数字速览**

| 指标 | 数值 |
|------|------|
| 目录图层总数 | 41 个（17 个在线天气 + 24 个科研/静态产品） |
| 内部分类 | 6 大类（天气 / 课题组 / 气候灾害 / 植被 / 土地利用 / 地形） |
| 课题组子分类 | 3 类（模型输入 / 模型输出 / 辅助数据） |
| 系统工作流种子 | 33 个（覆盖数据下载 / 预处理 / GIS 分析 / 反演 / 统计） |
| 数据源大类 | 星（卫星遥感）/ 地（站点观测）/ 气（气象再分析）/ 辅（地形覆盖）/ 开放（门户下载） |

---

## 二、四个核心字段的含义

在进入综合表格之前，先明确「图层名称、数据集名称、内部分类、内部 ID」四个字段在系统中的准确定义——它们分别对应图层目录（`layer_catalog`）中的 `display_name`、`dataset_key`、`category`、`layer_id`。

| 字段 | 系统标识 | 通俗含义 | 示例 |
|------|----------|----------|------|
| **图层名称** | `display_name` | 地图图层面板上展示给用户的中文名，面向地理工作者，允许重复 | `SMAP L3 土壤水分` |
| **数据集名称** | `dataset_key` | 图层背后绑定的数据集标识，同一数据集可多次导入/产出，靠实例 ID 区分 | `smap_sm_ts_dec2025` |
| **内部分类** | `category` | 图层所属的大类（英文 ID 与前端对齐），课题组数据另有子分类 | `research-group` → `模型输入` |
| **内部 ID** | `layer_id` | 全系统唯一、稳定不变的图层主键，绑定瓦片 URL、工作流关联与导出文件名 | `ref-smap-sm-202512-l3` |

**内部 ID 的前缀规则**（新增图层必须遵守）：

| 前缀 | 语义 | 示例 |
|------|------|------|
| `ref-` | 参考数据（官方产品 / 课题组参考序列） | `ref-smap-sm-202512-l3` |
| `prod-` | 生产融合产品 | `prod-fy_smap_station-sm_vod_omega-202512-fusion` |
| `method-` | 算法方法产出（可运行工作流） | `method-smap-omega-doy-avg` |
| `obs-` | 站点观测 | `obs-station-sm-daily` |
| `imported-` | 本地导入 / 工作流运行产物 | `imported-{hex}` |

> 约定：`layer_id` 一旦发布即为稳定目录键，不批量改名（已绑定瓦片 URL、工作流 `linked_layer_id` 与工作区快照）；重命名只改显示名，永不改内部 ID。

---

## 三、图层与数据集综合对照表（核心交付）

> 下表为系统图层目录的权威快照（2026-08-11）。表格字段：**内部 ID（layer_id）｜ 图层名称（display_name）｜ 数据集名称（dataset_key）｜ 内部分类（category / 子分类）｜ 时间粒度 ｜ 状态**。

### 3.1 在线天气图层（17 个 · 分类：`weather`）

实时气象数据，由天气引擎（Open-Meteo 在线/本地、可选 WeatherAPI / OpenWeather）按地图视口临时取数、切成瓦片显示；时间粒度以小时计，可随时间轴联动。

| 内部 ID | 图层名称 | 数据集名称 | 内部分类 | 时间粒度 | 状态 |
|---------|----------|------------|----------|----------|------|
| `wind-field` | 风场（10m） | `wind_field` | weather | 小时 | 可用（默认显示） |
| `wind-field-80m` | 风场（80m） | `wind_field_80m` | weather | 小时 | 可用 |
| `wind-field-120m` | 风场（120m） | `wind_field_120m` | weather | 小时 | 可用 |
| `wind-field-180m` | 风场（180m） | `wind_field_180m` | weather | 小时 | 可用 |
| `wind-field-850hPa` | 风场（850hPa） | `wind_field_850hpa` | weather | 小时 | 可用 |
| `wind-field-500hPa` | 风场（500hPa） | `wind_field_500hpa` | weather | 小时 | 可用 |
| `wind-field-200hPa` | 风场（200hPa） | `wind_field_200hpa` | weather | 小时 | 可用 |
| `precipitation` | 降水量 | `precipitation` | weather | 小时 | 可用 |
| `temperature` | 气温（2m） | `temperature` | weather | 小时 | 可用 |
| `temperature-80m` | 气温（80m） | `temperature_80m` | weather | 小时 | 可用 |
| `temperature-120m` | 气温（120m） | `temperature_120m` | weather | 小时 | 可用 |
| `temperature-180m` | 气温（180m） | `temperature_180m` | weather | 小时 | 可用 |
| `pressure` | 海平面气压 | `pressure` | weather | 小时 | 可用 |
| `humidity` | 相对湿度 | `humidity` | weather | 小时 | 可用 |
| `visibility` | 能见度 | `visibility` | weather | 小时 | 可用（GFS 模型） |
| `cloud-cover` | 云量 | `cloud-cover` | weather | 小时 | 可用 |
| `dewpoint` | 露点温度 | `dewpoint` | weather | 小时 | 可用 |

### 3.2 课题组数据图层（11 个 · 分类：`research-group`）

课题组的科研核心图层，涵盖土壤水分反演主链（SMAP / FY-3）、站点观测与辅助数据集，按「模型输入 / 模型输出 / 辅助数据」三个子分类组织。

| 内部 ID | 图层名称 | 数据集名称 | 内部分类（子分类） | 时间粒度 | 状态 |
|---------|----------|------------|--------------------|----------|------|
| `ref-smap-sm-202512-l3` | SMAP L3 土壤水分 | `smap_sm_ts_dec2025` | research-group（模型输入） | 日 | 可用（默认显示） |
| `prod-fy_smap_station-sm_vod_omega-202512-fusion` | 多源融合土壤水分 | `sm_multisource_dec2025` | research-group（模型输入） | 日 | 可用 |
| `ref-fy-tb-202512-mwri` | FY-3 MWRI 亮温 | `fy_mwri` | research-group（模型输入） | 日 | 可用 |
| `obs-station-sm-daily` | 站点土壤水分 | `ismn_casmos` | research-group（模型输入） | 日 | 可用 |
| `ref-ddca-sm-201504-202512` | DDCA 土壤水分 | `soil_moisture_ddca` | research-group（辅助数据） | 日 | 可用 |
| `forest-ratio` | 森林覆盖率 | `forest_cover_ratio_9km` | research-group（辅助数据） | 静态 | 可用 |
| `landscape-metrics-9km` | 景观多样性 SHDI | `landscape_metrics_9km` | research-group（辅助数据） | 静态 | 可用 |
| `method-smap-omega-doy-dynamic` | SMAP 动态 ω 反演 | `omega_sf_fenkuai_smap` | research-group（模型输出） | 日 | 可用（需先跑工作流） |
| `method-fy-omega-doy-dynamic` | FY 动态 ω 反演 | `omega_sf_fenkuai_fy` | research-group（模型输出） | 日 | 可用（需先跑工作流） |
| `method-smap-omega-doy-avg` | SMAP 日均 ω 反演 | `omega_avg_daily_smap` | research-group（模型输出） | 日 | 可用（需先跑工作流） |
| `method-fy-omega-doy-avg` | FY 日均 ω 反演 | `omega_avg_daily_fy` | research-group（模型输出） | 日 | 可用（需先跑工作流） |

### 3.3 气候与灾害图层（6 个 · 分类：`climate`）

历史气候、热浪灾害、CO₂ 与干旱指标等离线静态/时间序列产品。

| 内部 ID | 图层名称 | 数据集名称 | 内部分类 | 时间粒度 | 状态 |
|---------|----------|------------|----------|----------|------|
| `aridity-cn` | 干旱指数 AI | `aridity_index_cn` | climate | 静态 | 可用 |
| `gpcp-precip-ts` | GPCP 月降水 | `gpcp_v32_monthly` | climate | 月 | 可用 |
| `cmfd-precip-cn` | CMFD 区域降水 | `cmfd_precip_cn` | climate | 静态 | 可用 |
| `era5-dwaa-cn` | ERA5 白天热浪 | `era5_dwaa_smci_2020` | climate | 静态 | 可用 |
| `era5-wdaa-cn` | ERA5 夜间热浪 | `era5_wdaa_smci_2020` | climate | 静态 | 可用 |
| `co2-cn` | GOSAT CO₂ 柱浓度 | `gosat_midlayer_co2` | climate | 静态 | 可用 |

### 3.4 植被相关图层（2 个 · 分类：`vegetation`）

| 内部 ID | 图层名称 | 数据集名称 | 内部分类 | 时间粒度 | 状态 |
|---------|----------|------------|----------|----------|------|
| `ndvi` | 植被指数 NDVI | `ndvi_viirs_9km` | vegetation | 月 | 可用（基础数据就绪） |
| `biomass-cn` | 地上生物量 AGB | `agb_china_30m` | vegetation | 静态 | 可用 |

### 3.5 土地利用图层（3 个 · 分类：`landcover`）

| 内部 ID | 图层名称 | 数据集名称 | 内部分类 | 时间粒度 | 状态 |
|---------|----------|------------|----------|----------|------|
| `landcover-cn` | MODIS 土地覆盖 | `mcd12q1_cn` | landcover | 年 | 可用 |
| `clcd-cn` | CLCD 土地利用 | `clcd_30m` | landcover | 年 | 可用 |
| `hfp-cn` | 人类足迹指数 HFP | `human_footprint_cn` | landcover | 静态 | 可用 |

### 3.6 地形数据图层（2 个 · 分类：`terrain`）

| 内部 ID | 图层名称 | 数据集名称 | 内部分类 | 时间粒度 | 状态 |
|---------|----------|------------|----------|----------|------|
| `dem-etopo` | ETOPO 地形高程 | `etopo_1` | terrain | 静态 | 可用 |
| `gebco-dem-cn` | GEBCO 海底地形 | `gebco_2023` | terrain | 静态 | 可用 |

### 3.7 本地导入图层（动态 · 分类：`imported`）

除上述 41 个目录图层外，系统支持将**本地文件或工作流运行产物**导入为临时图层，内部 ID 采用 `imported-{hex}` 形式（如 `imported-1cb4e9591f39`）。当前导入实例多为：

- 工作流运行输出的栅格产品（如 `run-{id}_OMEGA_omega_pix_map.tif`、`OMEGA_BLOCK_OMEGA.tif`）；
- 时间序列导入层（`category = time-series`）；
- 用户上传的矢量 / 栅格文件（GeoJSON / GeoTIFF / SHP 等）。

导入层可重命名显示名（不改内部 ID），其数据集标识、文件源名（stem）作为导出文件名回退依据。

---

## 四、数据来源体系（星 / 地 / 气 / 辅 / 开放）

系统数据根目录由 `BACKEND_DATA_ROOT` 指定（联调示例 `I:\Geograph_DataSet`），原始数据按语义目录组织。按「星、地、气、辅、开放」五大类梳理如下：

| 大类 | 代表数据源 | 典型工作流 / 引擎 | 典型图层产出 |
|------|------------|-------------------|--------------|
| **星（卫星遥感）** | SMAP L3、FY-3 MWRI、VIIRS/MODIS NDVI、Sentinel-2（GEE）、GOSAT、ESA BIOMASS、GPCP | `smap_daily` / `fy_daily` / `ndvi_daily` / GEE bridge / 本地产品直接叠图 | 土壤湿度、亮温、NDVI、VOD/Omega、生物量、CO₂、月降水 |
| **地（地面站点）** | ISMN、CASMOS、中国生态站网 | `station_daily`（日值处理与验证） | 站点土壤湿度序列、订正/验证报告 |
| **气（气象）** | Open-Meteo 多模型、可选商业天气 API；ERA5 灾害指标产品 | 天气引擎实时瓦片 / 本地灾害栅格叠图 | 风、温、湿、压、云、降水、能见度；热浪事件图 |
| **辅（地形/覆盖等）** | ETOPO、GEBCO、MCD12Q1、CLCD、HFP、干旱指数、森林比例、景观指数 | 多为直接展示（overlay_registry） | 地形、土地覆盖、人类足迹、干旱、森林/景观指标 |
| **开放（门户临时下载）** | NOAA（NOMADS/GOES/Earthdata）、NSIDC、ESA Copernicus 预设 | 画布「门户数据下载」→ 解压 → 读变量 → 转格式 → 上图 | 用户指定文件对应的中间/最终图层 |

**Open-Meteo 常用预报模型白名单**：ECMWF IFS（0.25°，约 15 天）、GFS（0.25°，约 16 天）、ICON（0.25°，约 7.5 天）、ICON-EU（约 6–7 km 区域）等；天气瓦片按当前视口（z/x/y）临时取数，不做全球全时段落盘。

**远程数据接入**：支持 `smb://`、`sftp://`、`ftp(s)://`、`gs://`、`s3://` 等协议（只读），可通过设置页凭证或环境变量把远程 URI 注入到图层数据源候选最前端（`BACKEND_REMOTE_LAYER_DATA_URIS`），本地路径作回退。联调环境已接入两台远程 FileBrowser 服务器（Win11 电脑、NAS 课题组成员数据盘）。

---

## 五、算法引擎与渲染方式

系统图层按「能否运行算法」分为两类引擎，这是理解图层行为的关键：

| 引擎 | 含义 | 覆盖图层 |
|------|------|----------|
| `python_provider` | 可提交分析工作流：后端调度 Python 算法包模块（如 `smap_daily`、`omega_sf_fenkuai`、`ndvi_daily`）生成结果再上图 | NDVI、SMAP L3、FY 亮温、4 个 method-* 反演图层 |
| `overlay_registry` | 静态/产品叠加层：读取本地已就绪的栅格/PNG 直接展示，**不**从图层面板提交分析 | 地形、土地覆盖、气候灾害、辅助数据等绝大多数产品层 |
| `weather_tile` | 在线天气引擎：按视口实时取数渲染标准 z/x/y 瓦片 | 全部 17 个天气图层 |

**已注册算法模块（节选）**：`smap_daily`、`ndvi_daily`、`fy_daily`、`station_daily`、`daily_bundle`、`timeseries_bundle`、`inversion_daily`、`block_inversion`、`omega_block`、`omega_avg_daily`、`omega_sf_fenkuai`、`statistics`、`fitting`、`export` 等。

**图层与工作流的绑定**：4 个 `method-*` 反演图层通过 `linked_layer_id` / `workflow_id` 与系统工作流种子绑定（如 `method-smap-omega-doy-avg` ↔ `omega_avg_daily_smap_single`）；运行产出经 `wf-run-{groupId}-{sm|vod|omega}` 形式的运行时 ID 上图。

---

## 六、就绪状态与样例说明

1. **「可用」≠「全球全历史都已下载」**：多数科研图层当前是有限天数/月份的样例（如 SMAP L3 为 2025-12 全月 31 天、GPCP 展示采样 24 个月、DDCA 展示采样 60 天），便于演示与联调；扩库需按同一目录规范继续放数据。
2. **「待下载」数据**：NDVI 原始合成（VIIRS 750 m / MODIS 250 m）、FY MWRI 原始轨道、ISMN/CASMOS 站点文件等：算法与界面已接好，本机缺原始文件时不能出正式结果（图层状态仍标记为可用，运行前会给出就绪提示）。
3. **实时天气 vs 课题产品**：实时天气随视口临时取数，适合态势浏览；课题产品依赖本地库或 GEE/画布流水线，适合科研分析与出图存档。
4. **默认研究框**：华南框（约 109.6°E–117.4°E，20.1°N–25.6°N），部分算法图层以此为默认范围；中国区域框（73°E–137°E，15°N–59°N）用于多数静态产品。

---

## 七、扩展新数据的标准流程

若课题组后续新增数据集，按以下步骤接入（无需改代码即可上图的部分由运维配置完成）：

1. 数据落盘到 `BACKEND_DATA_ROOT/{Category}/` 对应子目录（新数据集用英文目录名）；
2. 在算法包 `dataset_config.py` 的 `DATASET_REGISTRY` 注册元信息（名称 / 逻辑名 / 相对路径 / 格式 / 变量 / 时间范围 / 分辨率 / CRS / 标签）；
3. 可选：在图层目录（`catalog_seeds`）新增 `LayerDescriptor`，声明 `layer_id / display_name / category / default_data_access_sources / capabilities`；
4. 可选：在 `overlay_registry` 配置 PNG 叠加；
5. `python launch.py restart backend` 重启后端，前端图层库即时可见。

**提供新数据时建议写清**：数据名称与来源机构、文件格式、空间范围、时间范围、物理量名称与单位、空间/时间分辨率、质量标记（如站点 `quality_flag`）。

---

## 八、阅读指南与验证方式

- **图层目录真源**：`Code/backend/app/catalog_seeds/`（`layer_descriptors.json` + `weather_descriptors.json` + `layer_categories.json`），前端 `check:catalog` 校验前后端对齐；
- **数据源与工作流对照**：`.ai/docs/specs/数据源与工作流对照说明-2026-07-21.md`、`.ai/docs/specs/当前数据源与产出一览.md`；
- **命名规范**：`.ai/docs/specs/layer-naming.md`；
- **联调入口**：FastAPI `http://127.0.0.1:8000`（`/docs`）、前端 `http://localhost:5175`、天气瓦片 `/weather/tiles/{layer_id}/{z}/{x}/{y}`、底图 `/unified-tiles`。

---

*本报告由系统图层目录与项目文档自动核对生成，供导师验收与后续数据规划使用。*
