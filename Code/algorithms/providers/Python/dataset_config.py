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
        "NDVI_VIIRS"      → I:\\Geograph_DataSet\\栅格气象数据\\VIIRS_NDVI
        "ISMN_STATION"    → I:\\Geograph_DataSet\\ISD-Lite\\ISMN
        "SMAP_L3"         → I:\\Geograph_DataSet\\栅格气象数据\\SMAP
        "CASMOS_STATION"  → I:\\Geograph_DataSet\\ISD-Lite\\CASMOS
        "CHINA_STATION"   → I:\\Geograph_DataSet\\Soil_Ecological_Data\\中国土壤数据
        "GOSAT_XCO2"      → I:\\Geograph_DataSet\\二氧化碳数据
        "ADMIN_BOUNDARY"  → I:\\Geograph_DataSet\\行政区数据
        "DEM_SRTM"        → I:\\Geograph_DataSet\\DEM
        "LANDCOVER_MODIS" → I:\\Geograph_DataSet\\栅格气象数据\\LandCover

    示例（MinIO 模式）：
        "NDVI_VIIRS" → s3://geodata/栅格气象数据/VIIRS_NDVI
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
# 已确认存在的数据集（根据 I:\\ 探查结果）
# ---------------------------------------------------------------------------

DATASET_REGISTRY: dict[str, DatasetInfo] = {
    # ---- 栅格气象数据 ----
    "NDVI_VIIRS": DatasetInfo(
        name="VIIRS NDVI 16天合成产品",
        logical_name="NDVI_VIIRS",
        relative_path="栅格气象数据/VIIRS_NDVI",
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
        relative_path="栅格气象数据/MODIS_NDVI",
        description="MODIS 卫星 16 天合成 NDVI 栅格数据（HDF 格式）",
        file_format="hdf",
        variables=("NDVI",),
        time_range=None,
        resolution="250m",
        crs="EPSG:4326",
        tags=("vegetation", "ndvi", "modis", "satellite"),
    ),
    "SMAP_L3": DatasetInfo(
        name="SMAP L3 土壤水分产品",
        logical_name="SMAP_L3",
        relative_path="栅格气象数据/SMAP",
        description="NASA SMAP L3 土壤水分被动微波遥感产品（HDF5 格式）",
        file_format="hdf5",
        variables=("soil_moisture", "TBh", "TBv"),
        time_range=None,
        resolution="9km",
        crs="EPSG:4326",
        tags=("soil_moisture", "smos", "satellite"),
    ),
    "FY_MWRI_HDF": DatasetInfo(
        name="FY-3 MWRI 亮温产品",
        logical_name="FY_MWRI_HDF",
        relative_path="fy",
        description="风云三号 MWRI 微波成像仪轨道 HDF 数据，用于亮温产品生成。",
        file_format="hdf",
        variables=("10V", "10H", "18V", "18H", "23V", "36V", "36H", "89V", "89H"),
        time_range=None,
        resolution=None,
        crs="EPSG:4326",
        tags=("fy", "mwri", "brightness_temperature", "satellite"),
    ),
    "LANDCOVER": DatasetInfo(
        name="MODIS 土地覆盖产品",
        logical_name="LANDCOVER",
        relative_path="栅格气象数据/LandCover",
        description="MODIS IGBP 土地覆盖类型分类（1km 分辨率）",
        file_format="hdf",
        variables=("LC",),
        time_range=None,
        resolution="1km",
        crs="EPSG:4326",
        tags=("landcover", "igbp", "modis"),
    ),
    "RAINFUSION": DatasetInfo(
        name="融合降水数据",
        logical_name="RAINFUSION",
        relative_path="栅格气象数据/降雨融合",
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
        relative_path="栅格气象数据/WindField",
        description="ECMWF 风场再分析数据（NetCDF 格式）",
        file_format="nc",
        variables=("u10", "v10", "wind_speed"),
        time_range=None,
        resolution="0.25deg",
        crs="EPSG:4326",
        tags=("wind", "ecmwf", "reanalysis"),
    ),
    # ---- 二氧化碳数据 ----
    "GOSAT_XCO2": DatasetInfo(
        name="GOSAT XCO2 柱浓度数据",
        logical_name="GOSAT_XCO2",
        relative_path="二氧化碳数据",
        description="GOSAT 卫星反演的大气 CO2 柱浓度数据（.mat 格式）",
        file_format="mat",
        variables=("xco2",),
        time_range=None,
        resolution="point",
        crs="EPSG:4326",
        tags=("co2", "gosat", "xco2", "atmospheric"),
    ),
    # ---- 站点数据 ----
    "ISMN_STATION": DatasetInfo(
        name="ISMN 全球土壤水分站点数据",
        logical_name="ISMN_STATION",
        relative_path="ISD-Lite/ISMN",
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
        relative_path="ISD-Lite/CASMOS",
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
        relative_path="Soil_Ecological_Data/中国土壤数据",
        description="中国生态系统研究网络（CERN）土壤温湿度长期观测数据",
        file_format="txt",
        variables=("soil_moisture", "soil_temperature"),
        time_range=None,
        resolution="point",
        crs="EPSG:4326",
        tags=("soil_moisture", "station", "china", "cern", "in_situ"),
    ),
    # ---- 行政区数据 ----
    "ADMIN_BOUNDARY_CN": DatasetInfo(
        name="中国行政区划边界",
        logical_name="ADMIN_BOUNDARY_CN",
        relative_path="行政区数据",
        description="中国省/市/区县行政区划矢量边界（GeoJSON/SHP 格式）",
        file_format="json",
        variables=("boundary",),
        time_range=None,
        resolution=None,
        crs="EPSG:4326",
        tags=("boundary", "admin", "china", "vector"),
    ),
    # ---- DEM ----
    "DEM_SRTM": DatasetInfo(
        name="SRTM 数字高程模型",
        logical_name="DEM_SRTM",
        relative_path="DEM",
        description="SRTM 数字高程模型（90m 分辨率）",
        file_format="tif",
        variables=("elevation",),
        time_range=None,
        resolution="90m",
        crs="EPSG:4326",
        tags=("dem", "elevation", "srtm", "terrain"),
    ),
    # ---- 辅助数据集（可能在 ProjectBackup 中） ----
    "ANCILLARY_MODIS": DatasetInfo(
        name="MODIS 地表参数辅助数据",
        logical_name="ANCILLARY_MODIS",
        relative_path="栅格气象数据/辅助场",
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
