"""配置驱动的叠加图层注册中心。

支持静态图层（单张 PNG）和时间序列图层（按时间索引的多张 PNG）。
每个图层包含：
- 地理配准 PNG 预览
- bounds JSON（边界 + 元数据）
- 可选的时间序列（time_list + default_time）
- 可选的源数据路径（用于 /overlay-value 点查询）

前端通过 /overlay-preview/{layer_id}?time=... 和 /overlay-bounds/{layer_id} 访问。
通过 /overlay-value/{layer_id}?lng=...&lat=...&time=... 查询像素值。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import HTTPException

# 引入 algorithms providers 目录以复用 universal_reader
# 注意：必须 append 而非 insert(0)，否则 providers/Python/algorithms 会遮蔽顶层 algorithms 包
_PROVIDER_ROOT = Path(
    r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\algorithms\providers\Python"
)
if str(_PROVIDER_ROOT) not in sys.path:
    sys.path.append(str(_PROVIDER_ROOT))


@dataclass
class OverlaySpec:
    """单个叠加图层的配置。"""

    layer_id: str
    """前端 catalogId，与 layer_catalog 中 layer_id 对齐。"""

    overlay_dir: Path
    """存放 PNG 与 bounds JSON 的目录。"""

    category: str = "static"
    """static | time-series。"""

    png_filename: str | None = None
    """静态图层使用的 PNG 文件名（相对 overlay_dir）。"""

    bounds_filename: str | None = None
    """静态图层使用的 bounds JSON 文件名。"""

    time_pattern: str | None = None
    """时间序列图层的 PNG 文件名模板，使用 {time} 占位符，例如 'smap_sm_{time}.png'。"""

    bounds_pattern: str | None = None
    """时间序列图层的 bounds JSON 文件名模板。若为 None，则使用静态 bounds_filename。"""

    time_list: list[str] = field(default_factory=list)
    """时间序列图层可选的时间标签列表（例如 ['20230101', '20230103', ...]）。"""

    default_time: str | None = None
    """初始展示的时间标签。"""

    palette: str = "viridis"
    """配色方案名称（仅作为元数据传给前端，渲染由 PNG 导出阶段决定）。"""

    vmin: float | None = None
    vmax: float | None = None
    unit: str = ""
    opacity: float = 0.7

    # ── 坐标系（用于 bounds 解释）──────────────────────────────────────────
    crs: str = "EPSG:4326"
    """图层 bounds 所用坐标系。默认 WGS84。

    导入非 WGS84 栅格时由 ``/import/raster/confirm`` 写入（通常写入 ``"EPSG:4326"``，
    因为 confirm 流程已将 PNG 与 bounds 重投影到 WGS84）。前端 ``overlay-image-module``
    根据 ``meta.crs`` 决定是否做防御性校验。
    """

    # ── 源数据配置（用于 /overlay-value 点查询）─────────────────────────────
    source_path: Path | None = None
    """静态图层的源数据文件路径（NetCDF/MAT/GeoTIFF）。"""

    source_pattern: str | None = None
    """时间序列图层的源数据文件名模板（含 {time} 占位符，可含 glob 通配符）。"""

    source_variable: str | None = None
    """读取的变量名（HDF5/NetCDF/MAT）。GeoTIFF 忽略。"""

    source_reader: str = "auto"
    """auto | mat | netcdf | geotiff | hdf5。auto 按文件扩展名判断。"""

    def resolve_png(self, time: str | None = None) -> Path:
        if self.category == "time-series":
            t = time or self.default_time
            if t is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Time-series overlay {self.layer_id} requires 'time' parameter",
                )
            if self.time_list and t not in self.time_list:
                raise HTTPException(
                    status_code=404,
                    detail=f"Time {t} not available for overlay {self.layer_id}",
                )
            if self.time_pattern is None:
                raise HTTPException(
                    status_code=500,
                    detail=f"Time-series overlay {self.layer_id} missing time_pattern",
                )
            return self.overlay_dir / self.time_pattern.format(time=t)
        # static
        if self.png_filename is None:
            raise HTTPException(
                status_code=500,
                detail=f"Static overlay {self.layer_id} missing png_filename",
            )
        return self.overlay_dir / self.png_filename

    def resolve_bounds(self, time: str | None = None) -> Path:
        if self.category == "time-series" and self.bounds_pattern:
            t = time or self.default_time
            return self.overlay_dir / self.bounds_pattern.format(time=t)
        if self.bounds_filename is None:
            raise HTTPException(
                status_code=500,
                detail=f"Overlay {self.layer_id} missing bounds file config",
            )
        return self.overlay_dir / self.bounds_filename

    def meta_dict(self) -> dict[str, Any]:
        """返回图层元数据（用于 /overlay-bounds 响应）。"""
        return {
            "layer_id": self.layer_id,
            "category": self.category,
            "palette": self.palette,
            "vmin": self.vmin,
            "vmax": self.vmax,
            "unit": self.unit,
            "opacity": self.opacity,
            "crs": self.crs,
            "time_list": list(self.time_list),
            "default_time": self.default_time,
            "current_time": self.default_time,
        }

    def resolve_source_path(self, time: str | None = None) -> Path | None:
        """解析源数据文件路径。返回 None 表示未配置源数据。"""
        if self.category == "time-series":
            if self.source_pattern is None:
                return None
            t = time or self.default_time
            if t is None:
                return None
            pattern = self.source_pattern.format(time=t)
            # 支持 glob 通配符（如 SMAP R 编号）
            if "*" in pattern or "?" in pattern:
                p = Path(pattern)
                # 统一使用 parent.glob(name) 避免绝对路径 glob 异常
                parent = p.parent
                matches = sorted(parent.glob(p.name)) if parent.exists() else []
                if not matches:
                    return None
                return matches[0]
            p = Path(pattern)
            return p if p.exists() else None
        # static
        if self.source_path is None:
            return None
        return self.source_path if self.source_path.exists() else None

    def resolve_value(
        self, lng: float, lat: float, time: str | None = None
    ) -> dict[str, Any]:
        """查询图层在 (lng, lat) 点的像素值。

        读取源数据文件，用最近邻法采样。返回:
            {"value": float | None, "unit": str, "layer_id": str,
             "time": str | None, "lng": float, "lat": float}
        若未配置源数据或文件不可用，value=None。
        """
        result: dict[str, Any] = {
            "value": None,
            "unit": self.unit,
            "layer_id": self.layer_id,
            "time": time,
            "lng": lng,
            "lat": lat,
        }
        try:
            src_path = self.resolve_source_path(time)
            if src_path is None:
                return result

            from data_access.universal_reader import UniversalDataReader

            reader = UniversalDataReader(src_path)
            # 读取变量（GeoTIFF 忽略 variable）
            variable = self.source_variable if self.source_reader != "geotiff" else None
            data_array = reader.read_variable(variable=variable)
            values = data_array.values
            lat_arr = data_array.lat
            lon_arr = data_array.lon

            if lat_arr is None or lon_arr is None:
                return result

            # 统一为一维坐标
            lat_1d = lat_arr.ravel() if lat_arr.ndim > 1 else lat_arr
            lon_1d = lon_arr.ravel() if lon_arr.ndim > 1 else lon_arr

            # 二维数据 (lat, lon): 找最近邻行列
            if values.ndim == 2:
                # 若坐标为一维，按行列索引
                if (
                    lat_1d.ndim == 1
                    and lon_1d.ndim == 1
                    and lat_1d.size == values.shape[0]
                    and lon_1d.size == values.shape[1]
                ):
                    row = int(np.argmin(np.abs(lat_1d - lat)))
                    col = int(np.argmin(np.abs(lon_1d - lng)))
                    val = float(values[row, col])
                else:
                    # 二维坐标（如 SMAP EASE-Grid）：逐像素距离
                    flat_idx = int(
                        np.argmin((lat_arr - lat) ** 2 + (lon_arr - lng) ** 2)
                    )
                    val = float(values.ravel()[flat_idx])
            elif values.ndim == 3:
                # 3D (time, lat, lon): 取第一个时间片
                if (
                    lat_1d.ndim == 1
                    and lon_1d.ndim == 1
                    and lat_1d.size == values.shape[1]
                    and lon_1d.size == values.shape[2]
                ):
                    row = int(np.argmin(np.abs(lat_1d - lat)))
                    col = int(np.argmin(np.abs(lon_1d - lng)))
                    val = float(values[0, row, col])
                else:
                    val = float("nan")
            else:
                val = float("nan")

            if not np.isfinite(val):
                result["value"] = None
            else:
                result["value"] = val
        except Exception as e:
            # 源数据读取失败时返回 None 而非抛错（降级）
            result["value"] = None
            result["error"] = str(e)
        return result


# ──────────────────────────────────────────────────────────────────────────────
# 数据根目录
# ──────────────────────────────────────────────────────────────────────────────

_PROJECT_OUTPUT = Path(r"I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion")
_DEM_DIR = Path(r"I:\Geograph_DataSet\DEM\ETOPO_2022")
_GPCP_DIR = Path(r"I:\Geograph_DataSet\Weather\Precipitation\Precipitation\dataset")
_STAGE2_ALIGNED = _PROJECT_OUTPUT / "stage2_aligned"
_OMEGA_SOURCE = Path(r"I:\Geograph_DataSet\InversionResults\smap_avg\doy_017.mat")
_DEM_SOURCE_TIF = _DEM_DIR / "ETOPO_2022_v1_60s_N90W180_surface.tif"

# ── 课题组派生 9km EASE-Grid 数据根 ──────────────────────────────────────────
_INVERSION_RESULTS_ROOT = Path(r"I:\Geograph_DataSet\InversionResults")
_OMEGA_SMAP_AVG_DIR = _INVERSION_RESULTS_ROOT / "smap_avg"
_OMEGA_FY_AVG_DIR = _INVERSION_RESULTS_ROOT / "fy_avg"
_SOIL_DDCA_H_DIR = Path(r"I:\Geograph_DataSet\Soil_Ecological_Data\DDCA\DDCA_DH\H")

# ── Phase 2: 课题组 VOD/SM 产品族（2025-12 时间序列，EASE-Grid 9km）──────────
# SmapSoil_VOD_SM/YYYYMMDD.mat (v7.3 HDF5) 含 OMEGA / SM / VOD 三个变量，shape (1624, 3856)
_SMAP_SOIL_VOD_SM_DIR = Path(
    r"I:\Geograph_DataSet\Soil_Ecological_Data\SmapSoil_VOD_SM"
)

_OVERLAY_PNG_ROOT = _PROJECT_OUTPUT / "_overlays"
"""所有导出 PNG 的统一存放目录（由 Tools/export_overlay_assets.py 生成）。"""


def _smap_time_list() -> list[str]:
    """从 stage1_smap_mat 目录推断 SMAP 时间序列标签。"""
    smap_dir = _PROJECT_OUTPUT / "stage1_smap_mat"
    if not smap_dir.exists():
        return []
    tags: list[str] = []
    for f in sorted(smap_dir.glob("SMAP_L3_SM_P_*.mat")):
        # SMAP_L3_SM_P_20230101_R18290_001.mat -> 20230101
        # 寻找 8 位数字部分作为日期标签
        for part in f.stem.split("_"):
            if len(part) == 8 and part.isdigit():
                tags.append(part)
                break
    return tags


def _gpcp_time_list(limit: int = 24) -> list[str]:
    """从 GPCP NetCDF 目录采样时间标签（取最近 limit 个月）。"""
    if not _GPCP_DIR.exists():
        return []
    tags: list[str] = []
    for f in sorted(_GPCP_DIR.glob("GPCPMON_L3_*_V3.2.nc4")):
        # GPCPMON_L3_198301_V3.2.nc4 -> 198301
        parts = f.stem.split("_")
        if len(parts) >= 3 and len(parts[2]) == 6 and parts[2].isdigit():
            tags.append(parts[2])
    if len(tags) > limit:
        # 均匀采样
        step = max(1, len(tags) // limit)
        tags = tags[::step][:limit]
    return tags


def _doy_time_list(directory: Path, prefix: str = "doy_") -> list[str]:
    """从 InversionResults/smap_avg|fy_avg 目录推断 doy 时间序列标签。

    文件名形如 ``doy_017.mat`` → 标签 ``'017'``。
    """
    if not directory.exists():
        return []
    tags: list[str] = []
    for f in sorted(directory.glob(f"{prefix}*.mat")):
        # doy_017.mat -> 017
        stem = f.stem  # 'doy_017'
        if stem.startswith(prefix):
            tag = stem[len(prefix) :]
            if tag.isdigit():
                tags.append(tag)
    return tags


def _soil_ddca_time_list(limit: int = 60) -> list[str]:
    """从 Soil_Ecological_Data/DDCA/DDCA_DH/H 目录推断日期时间序列标签。

    文件名形如 ``20150401.mat`` → 标签 ``'20150401'``。
    限制最多 limit 个标签，避免时间轴过长。
    """
    if not _SOIL_DDCA_H_DIR.exists():
        return []
    tags: list[str] = []
    for f in sorted(_SOIL_DDCA_H_DIR.glob("*.mat")):
        stem = f.stem
        if len(stem) == 8 and stem.isdigit():
            tags.append(stem)
    if len(tags) > limit:
        step = max(1, len(tags) // limit)
        tags = tags[::step][:limit]
    return tags


def _date8_time_list(directory: Path, limit: int | None = None) -> list[str]:
    """通用 8 位日期时间序列标签扫描：YYYYMMDD.mat → 'YYYYMMDD'。

    与 ``_soil_ddca_time_list`` 逻辑一致，但接受任意目录参数，且 ``limit=None``
    时不采样（返回全部日期）。供 Phase 2 VOD/SM 产品族使用。

    Args:
        directory: 包含 YYYYMMDD.mat 文件的目录
        limit: 可选，最大标签数（均匀采样）；None 表示返回全部

    Returns:
        排序后的 8 位日期字符串列表
    """
    if not directory.exists():
        return []
    tags: list[str] = []
    for f in sorted(directory.glob("*.mat")):
        stem = f.stem
        if len(stem) == 8 and stem.isdigit():
            tags.append(stem)
    if limit is not None and len(tags) > limit:
        step = max(1, len(tags) // limit)
        tags = tags[::step][:limit]
    return tags


_SMAP_TIMES = _smap_time_list()
_GPCP_TIMES = _gpcp_time_list(limit=24)
_OMEGA_SMAP_TIMES = _doy_time_list(_OMEGA_SMAP_AVG_DIR)
_OMEGA_FY_TIMES = _doy_time_list(_OMEGA_FY_AVG_DIR)
_SOIL_DDCA_TIMES = _soil_ddca_time_list(limit=60)
# Phase 2: VOD/SM/Omega 2025-12 时间序列（31 天，全量不采样）
_VOD_SM_TIMES = _date8_time_list(_SMAP_SOIL_VOD_SM_DIR, limit=None)


# ──────────────────────────────────────────────────────────────────────────────
# 注册表
# ──────────────────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, OverlaySpec] = {}


def register_overlay(spec: OverlaySpec) -> None:
    _REGISTRY[spec.layer_id] = spec


def unregister_overlay(layer_id: str) -> OverlaySpec | None:
    """Remove a dynamically registered overlay; returns the removed spec if any."""
    return _REGISTRY.pop(layer_id, None)


def get_overlay_spec(layer_id: str) -> OverlaySpec | None:
    return _REGISTRY.get(layer_id)


def list_overlay_ids() -> list[str]:
    return list(_REGISTRY.keys())


# ─── 静态图层 ─────────────────────────────────────────────────────────────────

# SMAP/Omega 交叉分析 14 天均值（保留旧 layer_id 兼容前端）
register_overlay(
    OverlaySpec(
        layer_id="lab-output",
        overlay_dir=_PROJECT_OUTPUT,
        png_filename="smap_sm_overlay.png",
        bounds_filename="smap_sm_overlay_bounds.json",
        category="static",
        palette="magenta-yellow",
        vmin=0.0,
        vmax=0.5,
        unit="m³/m³",
        opacity=0.7,
        source_path=_OMEGA_SOURCE,
        source_variable="OMEGA_AVG",
        source_reader="mat",
    )
)

# DEM ETOPO_2022 bed topography（全球）
register_overlay(
    OverlaySpec(
        layer_id="dem-etopo",
        overlay_dir=_OVERLAY_PNG_ROOT / "dem",
        png_filename="etopo_bed_overlay.png",
        bounds_filename="etopo_bed_overlay_bounds.json",
        category="static",
        palette="terrain",
        vmin=-8000.0,
        vmax=8000.0,
        unit="m",
        opacity=0.85,
        source_path=_DEM_SOURCE_TIF,
        source_reader="geotiff",
    )
)

# MCD12Q1 土地覆盖（中国区域 0.25°）
register_overlay(
    OverlaySpec(
        layer_id="landcover-cn",
        overlay_dir=_OVERLAY_PNG_ROOT / "thematic",
        png_filename="landcover_overlay.png",
        bounds_filename="landcover_overlay_bounds.json",
        category="static",
        palette="igbp",
        vmin=0.0,
        vmax=17.0,
        unit="IGBP class",
        opacity=0.8,
        source_path=_STAGE2_ALIGNED / "landcover_025.mat",
        source_variable="landcover",
        source_reader="mat",
    )
)

# Human Footprint 2018（中国区域 0.25°）
register_overlay(
    OverlaySpec(
        layer_id="hfp-cn",
        overlay_dir=_OVERLAY_PNG_ROOT / "thematic",
        png_filename="hfp_overlay.png",
        bounds_filename="hfp_overlay_bounds.json",
        category="static",
        palette="hot",
        vmin=0.0,
        vmax=50.0,
        unit="HFP score",
        opacity=0.8,
        source_path=_STAGE2_ALIGNED / "hfp_025.mat",
        source_variable="hfp",
        source_reader="mat",
    )
)

# Aridity Index（中国区域 0.25°）
register_overlay(
    OverlaySpec(
        layer_id="aridity-cn",
        overlay_dir=_OVERLAY_PNG_ROOT / "thematic",
        png_filename="aridity_overlay.png",
        bounds_filename="aridity_overlay_bounds.json",
        category="static",
        palette="brg",
        vmin=0.0,
        vmax=2.0,
        unit="AI",
        opacity=0.8,
        source_path=_STAGE2_ALIGNED / "aridity_025.mat",
        source_variable="aridity",
        source_reader="mat",
    )
)

# Omega 反演结果均值时间序列（doy 017-030，14 天）
register_overlay(
    OverlaySpec(
        layer_id="omega-output",
        overlay_dir=_OVERLAY_PNG_ROOT / "omega_ts",
        time_pattern="omega_avg_{time}.png",
        bounds_pattern="omega_avg_{time}_bounds.json",
        bounds_filename="omega_avg_overlay_bounds.json",  # 通用 bounds 备用
        category="time-series",
        time_list=_OMEGA_SMAP_TIMES,
        default_time=_OMEGA_SMAP_TIMES[0] if _OMEGA_SMAP_TIMES else None,
        palette="plasma",
        vmin=0.0,
        vmax=1.0,
        unit="Omega",
        opacity=0.75,
        source_pattern=str(_OMEGA_SMAP_AVG_DIR / "doy_{time}.mat"),
        source_variable="OMEGA_AVG",
        source_reader="mat",
    )
)


# ─── 时间序列图层 ────────────────────────────────────────────────────────────

# SMAP 土壤湿度时间序列（2023-01，13 天）
register_overlay(
    OverlaySpec(
        layer_id="smap-sm-ts",
        overlay_dir=_OVERLAY_PNG_ROOT / "smap_ts",
        time_pattern="smap_sm_{time}.png",
        bounds_pattern="smap_sm_{time}_bounds.json",
        bounds_filename="smap_sm_ts_bounds.json",  # 通用 bounds 备用
        category="time-series",
        time_list=_SMAP_TIMES,
        default_time=_SMAP_TIMES[0] if _SMAP_TIMES else None,
        palette="magenta-yellow",
        vmin=0.0,
        vmax=0.5,
        unit="m³/m³",
        opacity=0.7,
        source_pattern=str(
            _PROJECT_OUTPUT / "stage1_smap_mat" / "SMAP_L3_SM_P_{time}_R*.mat"
        ),
        source_variable="sm_dca",
        source_reader="mat",
    )
)

# GPCP 月降水时间序列（采样 24 个月）
register_overlay(
    OverlaySpec(
        layer_id="gpcp-precip-ts",
        overlay_dir=_OVERLAY_PNG_ROOT / "gpcp_ts",
        time_pattern="gpcp_{time}.png",
        bounds_pattern="gpcp_{time}_bounds.json",
        bounds_filename="gpcp_ts_bounds.json",
        category="time-series",
        time_list=_GPCP_TIMES,
        default_time=_GPCP_TIMES[-1] if _GPCP_TIMES else None,
        palette="blues",
        vmin=0.0,
        vmax=800.0,
        unit="mm/month",
        opacity=0.8,
        source_pattern=str(_GPCP_DIR / "GPCPMON_L3_{time}_V3.2.nc4"),
        source_variable="sat_gauge_precip",
        source_reader="netcdf",
    )
)


# ─── 新增数据集图层（10 个，静态） ────────────────────────────────────────────

# 源数据根目录
_GEBCO_NC = Path(r"I:\Geograph_DataSet\DEM\GEBCO_2024.nc")
_CMFD_TIF = Path(r"I:\Geograph_DataSet\Precipitation\pre_2002_01.tif")
_CLCD_TIF = Path(r"I:\Geograph_DataSet\LandCover\CLCD_v01_1997.tif")
_BIOMASS_NC = Path(
    r"I:\Geograph_DataSet\Biomass\ESACCI-BIOMASS-L4-AGB-MERGED-100m-2020-fv6.0.nc"
)
_ERA5_DWAA_TIF = Path(
    r"I:\Geograph_DataSet\Hazards\DWAA_result\DW_T7\ERA5_2020_DW_SMCI.tif"
)
_ERA5_WDAA_TIF = Path(
    r"I:\Geograph_DataSet\Hazards\DWAA_result\WD_T7\ERA5_2020_WD_SMCI.tif"
)
_CO2_TIF = Path(r"I:\Geograph_DataSet\CO2\MidLayerCO2Column\TIF\MeanCarbonDioxide.tif")
_SOIL_DDCA_MAT = Path(
    r"I:\Geograph_DataSet\Soil_Ecological_Data\DDCA\DDCA_DH\H\20150401.mat"
)
_OMEGA_FY_MAT = Path(r"I:\Geograph_DataSet\InversionResults\fy_avg\doy_025.mat")
_FOREST_RATIO_MAT = Path(
    r"I:\Geograph_DataSet\InversionResults\Forest_Ratio_9KM_2020.mat"
)


# GEBCO 2024 DEM（中国区域）
register_overlay(
    OverlaySpec(
        layer_id="gebco-dem-cn",
        overlay_dir=_OVERLAY_PNG_ROOT / "gebco_dem",
        png_filename="gebco_dem_overlay.png",
        bounds_filename="gebco_dem_overlay_bounds.json",
        category="static",
        palette="terrain",
        vmin=-2000.0,
        vmax=6000.0,
        unit="m",
        opacity=0.85,
        source_path=_GEBCO_NC,
        source_variable="elevation",
        source_reader="netcdf",
    )
)

# CMFD 降水（中国 1km，2002-01）
register_overlay(
    OverlaySpec(
        layer_id="cmfd-precip-cn",
        overlay_dir=_OVERLAY_PNG_ROOT / "cmfd_precip",
        png_filename="cmfd_precip_overlay.png",
        bounds_filename="cmfd_precip_overlay_bounds.json",
        category="static",
        palette="YlGnBu",
        vmin=0.0,
        vmax=400.0,
        unit="mm",
        opacity=0.8,
        source_path=_CMFD_TIF,
        source_reader="geotiff",
    )
)

# CLCD 1997 土地覆盖（中国）
register_overlay(
    OverlaySpec(
        layer_id="clcd-cn",
        overlay_dir=_OVERLAY_PNG_ROOT / "clcd",
        png_filename="clcd_overlay.png",
        bounds_filename="clcd_overlay_bounds.json",
        category="static",
        palette="tab10",
        vmin=1.0,
        vmax=9.0,
        unit="class",
        opacity=0.85,
        source_path=_CLCD_TIF,
        source_reader="geotiff",
    )
)

# ESACCI BIOMASS 2020（中国区域）
register_overlay(
    OverlaySpec(
        layer_id="biomass-cn",
        overlay_dir=_OVERLAY_PNG_ROOT / "biomass",
        png_filename="biomass_overlay.png",
        bounds_filename="biomass_overlay_bounds.json",
        category="static",
        palette="YlGn",
        vmin=0.0,
        vmax=300.0,
        unit="Mg/ha",
        opacity=0.85,
        source_path=_BIOMASS_NC,
        source_variable="agb",
        source_reader="netcdf",
    )
)

# ERA5 DWAA SMCI 2020（白天热浪事件计数）
register_overlay(
    OverlaySpec(
        layer_id="era5-dwaa-cn",
        overlay_dir=_OVERLAY_PNG_ROOT / "era5_dwaa",
        png_filename="era5_dwaa_overlay.png",
        bounds_filename="era5_dwaa_overlay_bounds.json",
        category="static",
        palette="YlOrRd",
        vmin=0.0,
        vmax=10.0,
        unit="events",
        opacity=0.8,
        source_path=_ERA5_DWAA_TIF,
        source_reader="geotiff",
    )
)

# ERA5 WDAA SMCI 2020（夜间热浪事件计数）
register_overlay(
    OverlaySpec(
        layer_id="era5-wdaa-cn",
        overlay_dir=_OVERLAY_PNG_ROOT / "era5_wdaa",
        png_filename="era5_wdaa_overlay.png",
        bounds_filename="era5_wdaa_overlay_bounds.json",
        category="static",
        palette="YlGnBu",
        vmin=0.0,
        vmax=15.0,
        unit="events",
        opacity=0.8,
        source_path=_ERA5_WDAA_TIF,
        source_reader="geotiff",
    )
)

# MeanCarbonDioxide（中国区域）
register_overlay(
    OverlaySpec(
        layer_id="co2-cn",
        overlay_dir=_OVERLAY_PNG_ROOT / "co2",
        png_filename="co2_overlay.png",
        bounds_filename="co2_overlay_bounds.json",
        category="static",
        palette="RdYlGn_r",
        vmin=386.0,
        vmax=391.0,
        unit="ppm",
        opacity=0.8,
        source_path=_CO2_TIF,
        source_reader="geotiff",
    )
)

# Soil DDCA 时间序列（中国 9km，2015-04-01 至 2015-05-17，60 天采样）
register_overlay(
    OverlaySpec(
        layer_id="soil-ddca",
        overlay_dir=_OVERLAY_PNG_ROOT / "soil_ddca_ts",
        time_pattern="soil_ddca_{time}.png",
        bounds_pattern="soil_ddca_{time}_bounds.json",
        bounds_filename="soil_ddca_overlay_bounds.json",  # 通用 bounds 备用
        category="time-series",
        time_list=_SOIL_DDCA_TIMES,
        default_time=_SOIL_DDCA_TIMES[0] if _SOIL_DDCA_TIMES else None,
        palette="viridis",
        vmin=0.0,
        vmax=3.0,
        unit="",
        opacity=0.8,
        source_pattern=str(_SOIL_DDCA_H_DIR / "{time}.mat"),
        source_variable="DH",
        source_reader="mat",
    )
)

# Omega FY avg 时间序列（全球 9km，doy 025-030，6 天）
register_overlay(
    OverlaySpec(
        layer_id="omega-fy-output",
        overlay_dir=_OVERLAY_PNG_ROOT / "omega_fy_ts",
        time_pattern="omega_fy_{time}.png",
        bounds_pattern="omega_fy_{time}_bounds.json",
        bounds_filename="omega_fy_overlay_bounds.json",  # 通用 bounds 备用
        category="time-series",
        time_list=_OMEGA_FY_TIMES,
        default_time=_OMEGA_FY_TIMES[0] if _OMEGA_FY_TIMES else None,
        palette="magma",
        vmin=0.0,
        vmax=1.0,
        unit="Omega",
        opacity=0.75,
        source_pattern=str(_OMEGA_FY_AVG_DIR / "doy_{time}.mat"),
        source_variable="OMEGA_AVG",
        source_reader="mat",
    )
)

# Landscape Metrics 9km 2020（全球 EASE-Grid 9km，静态）
# Phase 1.4 新增：课题组派生景观指数数据，与 Forest_Ratio 同源
# .mat 含 4 个景观指数：PD/ED/SHDI/CONTAG；Phase 1 先暴露 SHDI（Shannon 多样性指数），
# 其余 3 个可在后续 Phase 通过相似方式扩展。
_LANDSCAPE_METRICS_MAT = (
    _INVERSION_RESULTS_ROOT / "Landscape_Metrics_LandOnly_9KM_2020.mat"
)
register_overlay(
    OverlaySpec(
        layer_id="landscape-metrics-9km",
        overlay_dir=_OVERLAY_PNG_ROOT / "landscape_metrics",
        png_filename="landscape_metrics_overlay.png",
        bounds_filename="landscape_metrics_overlay_bounds.json",
        category="static",
        palette="cividis",
        vmin=0.0,
        vmax=2.0,
        unit="SHDI",
        opacity=0.8,
        source_path=_LANDSCAPE_METRICS_MAT,
        source_variable="SHDI",
        source_reader="mat",
    )
)

# Forest Ratio 9KM 2020（全球 9km）
register_overlay(
    OverlaySpec(
        layer_id="forest-ratio",
        overlay_dir=_OVERLAY_PNG_ROOT / "forest_ratio",
        png_filename="forest_ratio_overlay.png",
        bounds_filename="forest_ratio_overlay_bounds.json",
        category="static",
        palette="YlGn",
        vmin=0.0,
        vmax=1.0,
        unit="ratio",
        opacity=0.85,
        source_path=_FOREST_RATIO_MAT,
        source_variable="Forest_Ratio",
        source_reader="mat",
    )
)


# ─── Phase 2: 课题组 VOD/SM/Omega 2025-12 产品族 ──────────────────────────────
# 数据源：I:\Geograph_DataSet\Soil_Ecological_Data\SmapSoil_VOD_SM\YYYYMMDD.mat
# v7.3 HDF5，含 OMEGA / SM / VOD 三个变量，shape (1624, 3856) on EASE-Grid 9km
# 每个图层导出 31 天（2025-12-01 ~ 2025-12-31）的 PNG + bounds JSON

# VOD 植被光学厚度时间序列（2025-12，31 天，magma 色表）
register_overlay(
    OverlaySpec(
        layer_id="vod-dec2025",
        overlay_dir=_OVERLAY_PNG_ROOT / "vod_ts",
        time_pattern="vod_ts_{time}.png",
        bounds_pattern="vod_ts_{time}_bounds.json",
        bounds_filename="vod_ts_overlay_bounds.json",  # 通用 bounds 备用
        category="time-series",
        time_list=_VOD_SM_TIMES,
        default_time=_VOD_SM_TIMES[0] if _VOD_SM_TIMES else None,
        palette="magma",
        vmin=0.0,
        vmax=1.0,
        unit="VOD",
        opacity=0.8,
        source_pattern=str(_SMAP_SOIL_VOD_SM_DIR / "{time}.mat"),
        source_variable="VOD",
        source_reader="mat",
    )
)

# SM 土壤湿度时间序列（2025-12，31 天，YlGnBu 色表）
register_overlay(
    OverlaySpec(
        layer_id="sm-dec2025",
        overlay_dir=_OVERLAY_PNG_ROOT / "sm_ts",
        time_pattern="sm_ts_{time}.png",
        bounds_pattern="sm_ts_{time}_bounds.json",
        bounds_filename="sm_ts_overlay_bounds.json",  # 通用 bounds 备用
        category="time-series",
        time_list=_VOD_SM_TIMES,
        default_time=_VOD_SM_TIMES[0] if _VOD_SM_TIMES else None,
        palette="YlGnBu",
        vmin=0.0,
        vmax=0.6,
        unit="m³/m³",
        opacity=0.8,
        source_pattern=str(_SMAP_SOIL_VOD_SM_DIR / "{time}.mat"),
        source_variable="SM",
        source_reader="mat",
    )
)

# Omega 反演时间序列（2025-12，31 天，plasma 色表）
# 与现有 omega-output (doy 017-030 多年均值) 互补，提供 2025-12 每日反演结果
register_overlay(
    OverlaySpec(
        layer_id="omega-dec2025",
        overlay_dir=_OVERLAY_PNG_ROOT / "omega_2025_ts",
        time_pattern="omega_2025_ts_{time}.png",
        bounds_pattern="omega_2025_ts_{time}_bounds.json",
        bounds_filename="omega_2025_ts_overlay_bounds.json",  # 通用 bounds 备用
        category="time-series",
        time_list=_VOD_SM_TIMES,
        default_time=_VOD_SM_TIMES[0] if _VOD_SM_TIMES else None,
        palette="plasma",
        vmin=0.0,
        vmax=1.0,
        unit="Omega",
        opacity=0.75,
        source_pattern=str(_SMAP_SOIL_VOD_SM_DIR / "{time}.mat"),
        source_variable="OMEGA",
        source_reader="mat",
    )
)


def read_bounds(layer_id: str, time: str | None = None) -> dict[str, Any]:
    """读取 bounds JSON 并附加元数据。"""
    spec = get_overlay_spec(layer_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No overlay for layer: {layer_id}")
    bounds_path = spec.resolve_bounds(time)
    if not bounds_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Overlay bounds file not found: {bounds_path.name}",
        )
    data = json.loads(bounds_path.read_text(encoding="utf-8"))
    # 合并元数据
    meta = spec.meta_dict()
    if time is not None:
        meta["current_time"] = time
    data.setdefault("meta", {}).update(meta)
    # 确保 bounds 字段存在
    if "bounds" not in data:
        raise HTTPException(
            status_code=500,
            detail=f"Bounds JSON missing 'bounds' field: {bounds_path.name}",
        )
    return data


def read_png_bytes(layer_id: str, time: str | None = None) -> bytes:
    """读取 PNG 字节。"""
    spec = get_overlay_spec(layer_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No overlay for layer: {layer_id}")
    png_path = spec.resolve_png(time)
    if not png_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Overlay preview file not found: {png_path.name}",
        )
    return png_path.read_bytes()
