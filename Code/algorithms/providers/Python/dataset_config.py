"""
数据集配置模块。

将逻辑数据集名称映射到实际存储路径（本地文件系统或 MinIO）。
同时定义了每个数据集的元信息（描述、文件格式、可用时间范围等）。

使用方式：
    from mat2py.core.dataset_config import (
        resolve_dataset_path,
        get_dataset_info,
        list_available_datasets,
        BACKEND_DATA_ROOT,
        BACKEND_OUTPUT_ROOT,
    )

环境变量：
    BACKEND_STORAGE_BACKEND: "local" | "minio"，默认 "local"
    BACKEND_DATA_ROOT: 本地地理数据根目录，默认为 I:\\Geograph_DataSet
    BACKEND_OUTPUT_ROOT: 产物输出根目录，默认为 I:\\GeoOutput
    BACKEND_MINIO_ENDPOINT / _ACCESS_KEY / _SECRET_KEY / _BUCKET / _SECURE: MinIO 配置

路径映射约定：
    逻辑数据集名 → 相对于数据根目录的子路径

    示例（本地文件系统，BACKEND_DATA_ROOT="I:\\Geograph_DataSet"）：
        "SMAP_L3"           → I:\\Geograph_DataSet\\SMAP
        "ERA5_SMCI"         → I:\\Geograph_DataSet\\Weather
        "BIOMASS_ESACCI"    → I:\\Geograph_DataSet\\Biomass
        "GOSAT_XCO2"        → I:\\Geograph_DataSet\\CO2
        "ADMIN_BOUNDARY_CN" → I:\\Geograph_DataSet\\AdminBoundary
        "DEM_SRTM"          → I:\\Geograph_DataSet\\DEM
        "LANDCOVER_MODIS"   → I:\\Geograph_DataSet\\LandCover
        "HUMAN_FOOTPRINT"   → I:\\Geograph_DataSet\\HumanFootprint
        "INVERSION_OMEGA"   → I:\\Geograph_DataSet\\InversionResults

    示例（MinIO 模式）：
        "SMAP_L3" → s3://geodata/SMAP
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.base import StorageBackend

# ===========================================================================
# 根目录配置
# ===========================================================================

# 地理数据根目录
_BACKEND_DATA_ROOT_DEFAULT = r"I:\Geograph_DataSet"
_BACKEND_DATA_ROOT_ENV = os.getenv("BACKEND_DATA_ROOT", _BACKEND_DATA_ROOT_DEFAULT)

# 产物输出根目录
_BACKEND_OUTPUT_ROOT_DEFAULT = r"I:\GeoOutput"
_BACKEND_OUTPUT_ROOT_ENV = os.getenv("BACKEND_OUTPUT_ROOT", _BACKEND_OUTPUT_ROOT_DEFAULT)

# 存储后端类型
_BACKEND_STORAGE_BACKEND = os.getenv("BACKEND_STORAGE_BACKEND", "local")


def _get_data_root() -> Path:
    """获取数据根目录，优先使用环境变量，否则使用默认值。"""
    root = Path(_BACKEND_DATA_ROOT_ENV)
    if root.exists():
        return root
    # Fallback: 尝试默认路径
    default = Path(_BACKEND_DATA_ROOT_DEFAULT)
    if default.exists():
        return default
    return root  # 返回配置路径（即使不存在，供后续检查）


def _get_output_root() -> Path:
    """获取产物输出根目录。"""
    root = Path(_BACKEND_OUTPUT_ROOT_ENV)
    if root.exists():
        return root
    # Fallback: 尝试默认路径
    default = Path(_BACKEND_OUTPUT_ROOT_DEFAULT)
    if default.exists():
        return default
    return root


# ProjectBackup 根目录（用于 resolve_dataset_path 的兜底递归搜索）
_BACKEND_PROJECTBACKUP_ROOT_DEFAULT = r"I:\ProjectBackup\GeoPaper"


def _get_projectbackup_root() -> Path:
    """获取 ProjectBackup 根目录，优先使用环境变量，否则使用默认值。"""
    root = Path(os.getenv("BACKEND_PROJECTBACKUP_ROOT", _BACKEND_PROJECTBACKUP_ROOT_DEFAULT))
    if root.exists():
        return root
    # Fallback: 尝试默认路径
    default = Path(_BACKEND_PROJECTBACKUP_ROOT_DEFAULT)
    if default.exists():
        return default
    return root


# 公开属性
BACKEND_DATA_ROOT: Path = _get_data_root()
BACKEND_OUTPUT_ROOT: Path = _get_output_root()
BACKEND_STORAGE_BACKEND: str = _BACKEND_STORAGE_BACKEND


# ===========================================================================
# 数据集元信息定义
# ===========================================================================


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    """数据集元信息"""

    name: str
    logical_name: str
    relative_path: str  # 相对于 BACKEND_DATA_ROOT 的路径
    description: str
    file_format: str  # "hdf5" | "mat" | "tif" | "csv" | "nc" | "txt"
    variables: tuple[str, ...]  # 主要变量名
    time_range: tuple[str, str] | None = None  # ("YYYY-MM-DD", "YYYY-MM-DD") 或 None
    resolution: str | None = None  # "1km" | "9km" | "250m" | ...
    crs: str | None = None  # "EPSG:4326" | ...
    tags: tuple[str, ...] = field(default_factory=())
    requires_download: bool = False  # 是否需要从远程下载


# ---------------------------------------------------------------------------
# 已确认存在的数据集（根据 I:\Geograph_DataSet 探查结果，2026-07-14 更新）
# ---------------------------------------------------------------------------

DATASET_REGISTRY: dict[str, DatasetInfo] = {
    # ---- 土壤水分 ----
    "SMAP_L3": DatasetInfo(
        name="SMAP L3 土壤水分产品",
        logical_name="SMAP_L3",
        relative_path="SMAP",
        description="NASA SMAP L3 土壤水分被动微波遥感产品（HDF5 格式），2023-01 两周序列 + 2022-09",
        file_format="hdf5",
        variables=("soil_moisture", "surface_temperature", "tb_h_corrected", "tb_v_corrected",
                   "vegetation_water_content", "clay_fraction", "vegetation_opacity"),
        time_range=("2022-09-20", "2023-01-31"),
        resolution="9km",
        crs="EPSG:4326",
        tags=("soil_moisture", "smap", "satellite", "brightness_temperature"),
    ),
    "ERA5_SMCI": DatasetInfo(
        name="ERA5 土壤水分气候异常指数",
        logical_name="ERA5_SMCI",
        relative_path="Weather",
        description="ERA5 SMCI-T7 土壤水分气候异常指数（NetCDF 格式），365天日数据，0.25° 全球",
        file_format="nc",
        variables=("SMCI",),
        time_range=("2018-01-01", "2020-12-31"),
        resolution="0.25deg",
        crs="EPSG:4326",
        tags=("soil_moisture", "era5", "reanalysis", "anomaly"),
    ),
    # ---- 植被与生物量 ----
    "BIOMASS_ESACCI": DatasetInfo(
        name="ESA CCI 地上生物量",
        logical_name="BIOMASS_ESACCI",
        relative_path="Biomass",
        description="ESA CCI Biomass L4 AGB 产品（NetCDF 格式），100m 分辨率，ALOS-2+Sentinel-1",
        file_format="nc",
        variables=("agb", "agb_sd"),
        time_range=("2020-01-01", "2020-12-31"),
        resolution="100m",
        crs="EPSG:4326",
        tags=("biomass", "esa_cci", "agb", "vegetation", "satellite"),
    ),
    "HUMAN_FOOTPRINT": DatasetInfo(
        name="Human Footprint 人类足迹指数",
        logical_name="HUMAN_FOOTPRINT",
        relative_path="HumanFootprint",
        description="Human Footprint 人类足迹指数（GeoTIFF 格式），1000m Mollweide 投影",
        file_format="tif",
        variables=("hfp",),
        time_range=("2018-01-01", "2020-12-31"),
        resolution="1km",
        crs="ESRI:54009",
        tags=("human_footprint", "anthropogenic", "global"),
    ),
    # ---- 气象数据 ----
    "CMFD_LRAD": DatasetInfo(
        name="CMFD 地表向下长波辐射",
        logical_name="CMFD_LRAD",
        relative_path="Weather",
        description="CMFD 月度地表向下长波辐射（NetCDF 格式），0.1° 中国区域，1979-2018",
        file_format="nc",
        variables=("lrad",),
        time_range=("1979-01-01", "2018-12-31"),
        resolution="0.1deg",
        crs="EPSG:4326",
        tags=("radiation", "cmfd", "china", "monthly"),
    ),
    "CMFD_SRAD": DatasetInfo(
        name="CMFD 地表向下短波辐射",
        logical_name="CMFD_SRAD",
        relative_path="Weather",
        description="CMFD 月度地表向下短波辐射（NetCDF 格式），0.1° 中国区域，1979-2018",
        file_format="nc",
        variables=("srad",),
        time_range=("1979-01-01", "2018-12-31"),
        resolution="0.1deg",
        crs="EPSG:4326",
        tags=("radiation", "cmfd", "china", "monthly"),
    ),
    "CHINA_1KM_TEMP": DatasetInfo(
        name="China 1km 月度温度",
        logical_name="CHINA_1KM_TEMP",
        relative_path="Weather",
        description="彭守彰 1km 月度温度数据集（GeoTIFF 格式），单位 0.1℃，2002-01~03",
        file_format="tif",
        variables=("tmp",),
        time_range=("2002-01-01", "2002-03-31"),
        resolution="1km",
        crs="EPSG:4326",
        tags=("temperature", "china", "monthly", "1km"),
    ),
    "CHINA_1KM_PRECIP": DatasetInfo(
        name="China 1km 月度降水",
        logical_name="CHINA_1KM_PRECIP",
        relative_path="Precipitation",
        description="彭守彰 1km 月度降水数据集（GeoTIFF 格式），单位 0.1mm，2002-01~03",
        file_format="tif",
        variables=("pre",),
        time_range=("2002-01-01", "2002-03-31"),
        resolution="1km",
        crs="EPSG:4326",
        tags=("precipitation", "china", "monthly", "1km"),
    ),
    # ---- 土地覆盖 ----
    "LANDCOVER_MODIS": DatasetInfo(
        name="MODIS MCD12Q1 土地覆盖",
        logical_name="LANDCOVER_MODIS",
        relative_path="LandCover",
        description="MODIS MCD12Q1 IGBP 土地覆盖分类（GeoTIFF 格式），463m Sinusoidal 投影，2019-2021",
        file_format="tif",
        variables=("LC",),
        time_range=("2019-01-01", "2021-12-31"),
        resolution="463m",
        crs="Sinusoidal",
        tags=("landcover", "igbp", "modis", "mcd12q1"),
    ),
    "LANDCOVER_CLCD": DatasetInfo(
        name="武汉大学 CLCD 中国土地覆盖",
        logical_name="LANDCOVER_CLCD",
        relative_path="LandCover",
        description="武汉大学 CLCD 中国土地覆盖动态（GeoTIFF 格式），30m EPSG:4326，值 0-9",
        file_format="tif",
        variables=("LC",),
        time_range=("1997-01-01", "1997-12-31"),
        resolution="30m",
        crs="EPSG:4326",
        tags=("landcover", "clcd", "china", "whu"),
    ),
    # ---- 反演结果 ----
    "INVERSION_OMEGA_SMAP": DatasetInfo(
        name="omega 反演结果 (SMAP 平均)",
        logical_name="INVERSION_OMEGA_SMAP",
        relative_path="InversionResults/smap_avg",
        description="omega 植被光学厚度反演结果（MAT v7.3 格式），SMAP 平均，doy 017-030",
        file_format="mat",
        variables=("OMEGA_AVG", "count_grid", "used_years"),
        time_range=None,
        resolution="9km",
        crs="EPSG:4326",
        tags=("omega", "inversion", "smap", "vegetation_opacity"),
    ),
    "INVERSION_OMEGA_FY": DatasetInfo(
        name="omega 反演结果 (FY 平均)",
        logical_name="INVERSION_OMEGA_FY",
        relative_path="InversionResults/fy_avg",
        description="omega 植被光学厚度反演结果（MAT v7.3 格式），FY 平均，doy 025-030",
        file_format="mat",
        variables=("OMEGA_AVG", "count_grid", "used_years"),
        time_range=None,
        resolution="9km",
        crs="EPSG:4326",
        tags=("omega", "inversion", "fy", "vegetation_opacity"),
    ),
    "LANDSCAPE_METRICS": DatasetInfo(
        name="景观格局指数",
        logical_name="LANDSCAPE_METRICS",
        relative_path="InversionResults",
        description="景观格局指数（MAT v5 格式），9km 分辨率，2020 年",
        file_format="mat",
        variables=("PD", "ED", "SHDI", "CONTAG", "Forest_Ratio"),
        time_range=("2020-01-01", "2020-12-31"),
        resolution="9km",
        crs="EPSG:4326",
        tags=("landscape", "metrics", "fragmentation"),
    ),
    # ---- 工作流中间产物（daily_bundle / timeseries_bundle 输出，作为反演工作流输入）----
    "daily_bundle_mat": DatasetInfo(
        name="单日合成数据 (daily_bundle 输出)",
        logical_name="daily_bundle_mat",
        relative_path="Soil_Ecological_Data/DDCA/DDCA_DH/H",
        description="daily_bundle 模块输出的单日合成 .mat 文件（含 TB/SM 等矩阵），可作为 inversion_daily 输入",
        file_format="mat",
        variables=("TB", "SM", "DH"),
        time_range=("2015-04-01", "2016-11-13"),
        resolution="9km",
        crs="EPSG:4326",
        tags=("daily_bundle", "inversion_input", "soil_moisture"),
    ),
    "timeseries_bundle_mat": DatasetInfo(
        name="时间序列合成数据 (timeseries_bundle 输出)",
        logical_name="timeseries_bundle_mat",
        relative_path="InversionResults/smap_avg",
        description="timeseries_bundle 模块输出的时间序列 .mat 文件，可作为 block_inversion / omega_block 输入",
        file_format="mat",
        variables=("OMEGA_AVG", "count_grid"),
        time_range=None,
        resolution="9km",
        crs="EPSG:4326",
        tags=("timeseries_bundle", "inversion_input", "omega"),
    ),
    # ---- 站点数据 ----
    "ISMN_FLUXNET_MATCH": DatasetInfo(
        name="ISMN 与 FLUXNET 站点匹配",
        logical_name="ISMN_FLUXNET_MATCH",
        relative_path="Station",
        description="ISMN 与 FLUXNET2015 站点匹配表（CSV 格式），101 个站点，31 列属性",
        file_format="csv",
        variables=("network", "station", "latitude", "longitude", "MAP", "MAT", "AI", "IGBP_Fluxnet"),
        time_range=None,
        resolution="point",
        crs="EPSG:4326",
        tags=("station", "ismn", "fluxnet", "match", "in_situ"),
    ),
    "STATION_ISD_LITE": DatasetInfo(
        name="ISD-Lite 全球站点气象数据",
        logical_name="STATION_ISD_LITE",
        relative_path="Station/China_Station_Rainfall",
        description="中国地区 ISD-Lite 地面气象观测站数据（ZIP 格式），1942-2021",
        file_format="txt",
        variables=("soil_moisture", "soil_temperature"),
        time_range=("1942-01-01", "2021-12-31"),
        resolution="point",
        crs="EPSG:4326",
        tags=("station", "isd_lite", "china", "in_situ"),
    ),
    # ---- 二氧化碳数据 ----
    "GOSAT_XCO2": DatasetInfo(
        name="GOSAT XCO2 柱浓度数据",
        logical_name="GOSAT_XCO2",
        relative_path="Gosat",
        description="GOSAT 卫星反演的大气 CO2 柱浓度数据（L2/L3/L4 产品）",
        file_format="mat",
        variables=("xco2",),
        time_range=None,
        resolution="point",
        crs="EPSG:4326",
        tags=("co2", "gosat", "xco2", "atmospheric"),
    ),
    "CO2_MIDLAYER": DatasetInfo(
        name="中层二氧化碳柱浓度",
        logical_name="CO2_MIDLAYER",
        relative_path="CO2/MidLayerCO2Column",
        description="中层二氧化碳柱浓度 GeoTIFF 数据",
        file_format="tif",
        variables=("co2",),
        time_range=None,
        resolution=None,
        crs="EPSG:4326",
        tags=("co2", "mid_layer", "atmospheric"),
    ),
    # ---- 行政区数据 ----
    "ADMIN_BOUNDARY_CN": DatasetInfo(
        name="中国行政区划边界",
        logical_name="ADMIN_BOUNDARY_CN",
        relative_path="AdminBoundary",
        description="中国省/市/区县/乡镇行政区划矢量边界（SHP/GeoJSON 格式）",
        file_format="shp",
        variables=("boundary",),
        time_range=None,
        resolution=None,
        crs="EPSG:4326",
        tags=("boundary", "admin", "china", "vector"),
    ),
    # ---- DEM ----
    "DEM_SRTM": DatasetInfo(
        name="GEBCO 数字高程模型",
        logical_name="DEM_SRTM",
        relative_path="DEM",
        description="GEBCO_2024 全球数字高程模型（NetCDF + GeoTIFF 格式）",
        file_format="nc",
        variables=("elevation",),
        time_range=None,
        resolution="450m",
        crs="EPSG:4326",
        tags=("dem", "elevation", "gebco", "terrain"),
    ),
    # ---- 灾害数据 ----
    "HAZARDS_DWAA": DatasetInfo(
        name="ERA5 干旱指数 DWAA",
        logical_name="HAZARDS_DWAA",
        relative_path="Hazards/DWAA_result",
        description="ERA5 干旱加权异常指数（DWAA）SMCI-T7（GeoTIFF 格式），1979-2024 年度数据",
        file_format="tif",
        variables=("DW_SMCI", "WD_SMCI"),
        time_range=("1979-01-01", "2024-12-31"),
        resolution="0.25deg",
        crs="EPSG:4326",
        tags=("drought", "era5", "hazards", "dwaa"),
    ),
    # ---- 其他 ----
    "ARIDITY_INDEX": DatasetInfo(
        name="全球干燥度指数",
        logical_name="ARIDITY_INDEX",
        relative_path="Others",
        description="全球干燥度指数（GeoTIFF 格式），MSWEP降水/GLEAM蒸散发，1980-2020",
        file_format="tif",
        variables=("AI",),
        time_range=("1980-01-01", "2020-12-31"),
        resolution="1deg",
        crs="EPSG:4326",
        tags=("aridity", "climate", "global"),
    ),
    # ---- 兼容旧逻辑名（数据可能尚未存在于新路径，resolve_dataset_path 会返回 None） ----
    "NDVI_VIIRS": DatasetInfo(
        name="VIIRS NDVI 16天合成产品",
        logical_name="NDVI_VIIRS",
        relative_path="Soil_Ecological_Data/NDVI/VIIRS",
        description="VIIRS 卫星 16 天合成 NDVI 栅格数据（HDF 格式），用于植被监测",
        file_format="hdf",
        variables=("NDVI",),
        time_range=None,
        resolution="750m",
        crs="EPSG:4326",
        tags=("vegetation", "ndvi", "viirs", "satellite"),
    ),
    "NDVI_MODIS": DatasetInfo(
        name="MODIS NDVI 16天合成产品",
        logical_name="NDVI_MODIS",
        relative_path="Soil_Ecological_Data/NDVI/MODIS",
        description="MODIS 卫星 16 天合成 NDVI 栅格数据（HDF 格式）",
        file_format="hdf",
        variables=("NDVI",),
        time_range=None,
        resolution="250m",
        crs="EPSG:4326",
        tags=("vegetation", "ndvi", "modis", "satellite"),
    ),
    "FY_MWRI_HDF": DatasetInfo(
        name="FY-3 MWRI 亮温产品",
        logical_name="FY_MWRI_HDF",
        relative_path="Soil_Ecological_Data/FY_MWRI",
        description="风云三号 MWRI 微波成像仪轨道 HDF 数据，用于亮温产品生成。",
        file_format="hdf",
        variables=("10V", "10H", "18V", "18H", "23V", "36V", "36H", "89V", "89H"),
        time_range=None,
        resolution=None,
        crs="EPSG:4326",
        tags=("fy", "mwri", "brightness_temperature", "satellite"),
    ),
    "RAINFUSION": DatasetInfo(
        name="融合降水数据",
        logical_name="RAINFUSION",
        relative_path="Precipitation/Fusion",
        description="卫星-站点融合降水数据（GRID）",
        file_format="tif",
        variables=("precipitation",),
        time_range=None,
        resolution=None,
        crs="EPSG:4326",
        tags=("precipitation", "fusion", "grid"),
    ),
    "WIND_FIELD": DatasetInfo(
        name="ECMWF 风场再分析数据",
        logical_name="WIND_FIELD",
        relative_path="Weather/WindField",
        description="ECMWF 风场再分析数据（NetCDF 格式）",
        file_format="nc",
        variables=("u10", "v10", "wind_speed"),
        time_range=None,
        resolution="0.25deg",
        crs="EPSG:4326",
        tags=("wind", "ecmwf", "reanalysis"),
    ),
    "ISMN_STATION": DatasetInfo(
        name="ISMN 全球土壤水分站点数据",
        logical_name="ISMN_STATION",
        relative_path="Station/ISMN",
        description="International Soil Moisture Network 全球土壤水分站点数据（STM 格式）",
        file_format="txt",
        variables=("soil_moisture", "soil_temperature"),
        time_range=None,
        resolution="point",
        crs="EPSG:4326",
        tags=("soil_moisture", "station", "ismn", "in_situ"),
    ),
    "CASMOS_STATION": DatasetInfo(
        name="CASMOS 中国土壤水分站点数据",
        logical_name="CASMOS_STATION",
        relative_path="Station/CASMOS",
        description="中国土壤水分观测网络站点数据（CASMOS 项目）",
        file_format="txt",
        variables=("soil_moisture", "soil_temperature"),
        time_range=None,
        resolution="point",
        crs="EPSG:4326",
        tags=("soil_moisture", "station", "china", "in_situ"),
    ),
    "CHINA_STATION": DatasetInfo(
        name="中国生态站网土壤数据",
        logical_name="CHINA_STATION",
        relative_path="Soil_Ecological_Data/China_Soil",
        description="中国生态系统研究网络（CERN）土壤温湿度长期观测数据",
        file_format="txt",
        variables=("soil_moisture", "soil_temperature"),
        time_range=None,
        resolution="point",
        crs="EPSG:4326",
        tags=("soil_moisture", "station", "china", "cern", "in_situ"),
    ),
    "LANDCOVER": DatasetInfo(
        name="MODIS 土地覆盖产品（兼容别名）",
        logical_name="LANDCOVER",
        relative_path="LandCover",
        description="MODIS IGBP 土地覆盖类型分类（兼容旧逻辑名，等同于 LANDCOVER_MODIS）",
        file_format="tif",
        variables=("LC",),
        time_range=("2019-01-01", "2021-12-31"),
        resolution="463m",
        crs="Sinusoidal",
        tags=("landcover", "igbp", "modis"),
    ),
    "ANCILLARY_MODIS": DatasetInfo(
        name="MODIS 地表参数辅助数据",
        logical_name="ANCILLARY_MODIS",
        relative_path="Soil_Ecological_Data/Ancillary",
        description="MODIS 地表温度/反射率等辅助参数",
        file_format="hdf",
        variables=("LST", "albedo"),
        time_range=None,
        resolution="1km",
        crs="EPSG:4326",
        tags=("ancillary", "modis", "lst", "albedo"),
    ),
}


# ===========================================================================
# 路径解析函数
# ===========================================================================


@lru_cache(maxsize=128)
def resolve_dataset_path(logical_name: str) -> Path | None:
    """
    将逻辑数据集名解析为实际绝对路径。

    查找顺序：
        1. DATASET_REGISTRY 中定义的数据集 → 拼接 BACKEND_DATA_ROOT + relative_path
        2. 直接将 logical_name 作为相对路径解析
        3. 尝试从多个已知数据根目录查找

    返回：
        Path 对象，如果数据集存在；否则返回 None
    """
    info = DATASET_REGISTRY.get(logical_name)
    if info is not None:
        candidate = BACKEND_DATA_ROOT / info.relative_path
        if candidate.exists():
            return candidate

    # 直接按逻辑名作为相对路径
    candidate = BACKEND_DATA_ROOT / logical_name
    if candidate.exists():
        return candidate

    # 尝试从 ProjectBackup 根目录查找
    backup_root = _get_projectbackup_root()
    if backup_root.exists():
        # 递归搜索（深度限制为 3 层）
        for parent in (backup_root / "数据", backup_root):
            if parent.exists():
                for sub in parent.rglob(logical_name):
                    if sub.is_dir():
                        return sub

    return None


def get_dataset_info(logical_name: str) -> DatasetInfo | None:
    """获取数据集元信息（不检查路径是否存在）"""
    return DATASET_REGISTRY.get(logical_name)


def list_available_datasets() -> list[str]:
    """列出所有已注册的数据集名称"""
    return sorted(DATASET_REGISTRY.keys())


def is_dataset_available(logical_name: str) -> bool:
    """检查数据集是否可用（注册且路径存在）"""
    return resolve_dataset_path(logical_name) is not None


def get_dataset_summary() -> list[dict[str, str | bool]]:
    """
    获取所有数据集的可用性摘要。

    返回：
        包含 name / logical_name / available / path / description 的列表
    """
    results = []
    for logical_name, info in sorted(DATASET_REGISTRY.items()):
        path = resolve_dataset_path(logical_name)
        results.append({
            "name": info.name,
            "logical_name": logical_name,
            "available": path is not None,
            "path": str(path) if path else "",
            "description": info.description,
            "file_format": info.file_format,
            "resolution": info.resolution or "",
        })
    return results


# ===========================================================================
# Storage Backend 工厂（可选）
# ===========================================================================


def get_storage_backend() -> "StorageBackend | None":
    """
    获取当前配置的存储后端实例。

    返回：
        StorageBackend 实例（local 或 minio），如果导入失败则返回 None
    """
    try:
        from mat2py.core.storage import get_storage_backend as _get
        return _get()
    except ImportError:
        # Storage 模块尚未安装依赖，返回 None
        return None


def get_output_storage_backend() -> "StorageBackend | None":
    """
    获取产物输出存储后端。

    MinIO 模式下产物也会写入 MinIO；
    local 模式下产物写入 BACKEND_OUTPUT_ROOT。
    """
    try:
        from mat2py.core.storage import get_output_storage_backend as _get
        return _get()
    except ImportError:
        return None
