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
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from app.services.errors import (
    OverlayConfigError,
    OverlayNotFoundError,
    OverlayValidationError,
)

# 引入 algorithms providers 目录以复用 universal_reader
# 注意：必须 append 而非 insert(0)，否则 providers/Python/algorithms 会遮蔽顶层 algorithms 包
from app.core.config import settings as _settings

_PROVIDER_ROOT = Path(_settings.python_provider_root)
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

    def _assert_time_available(self, t: str | None) -> str | None:
        """校验时序图层的时间值在 time_list 白名单内。

        与 :meth:`resolve_png` 的既有校验保持一致，阻断把用户可控 ``time``
        直接拼进文件路径的路径穿越（G1-01）。静态图层或空白名单时不拦截。
        """
        if self.category == "time-series" and t is None:
            raise OverlayValidationError(
                f"Time-series overlay {self.layer_id} requires 'time' parameter",
            )
        if self.time_list and t not in self.time_list:
            raise OverlayNotFoundError(
                f"Time {t} not available for overlay {self.layer_id}",
            )
        return t

    @staticmethod
    def _assert_no_path_traversal(path: Path) -> Path:
        """防御纵深：拒绝含 ``..`` 段的结果路径（白名单之外的最后一层防护）。"""
        if ".." in path.parts:
            raise OverlayNotFoundError(
                "Invalid overlay path (traversal detected)",
            )
        return path

    def resolve_png(self, time: str | None = None) -> Path:
        if self.category == "time-series":
            t = self._assert_time_available(time or self.default_time)
            if self.time_pattern is None:
                raise OverlayConfigError(
                    f"Time-series overlay {self.layer_id} missing time_pattern",
                )
            return self._assert_no_path_traversal(
                self.overlay_dir / self.time_pattern.format(time=t)
            )
        # static
        if self.png_filename is None:
            raise OverlayConfigError(
                f"Static overlay {self.layer_id} missing png_filename",
            )
        return self.overlay_dir / self.png_filename

    def resolve_bounds(self, time: str | None = None) -> Path:
        if self.category == "time-series" and self.bounds_pattern:
            t = self._assert_time_available(time or self.default_time)
            return self._assert_no_path_traversal(
                self.overlay_dir / self.bounds_pattern.format(time=t)
            )
        if self.bounds_filename is None:
            raise OverlayConfigError(
                f"Overlay {self.layer_id} missing bounds file config",
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
            # 与 resolve_png 一致的白名单校验，阻断 time=../../ 路径穿越（G1-01）
            self._assert_time_available(t)
            pattern = self.source_pattern.format(time=t)
            # 支持 glob 通配符（如 SMAP R 编号）
            if "*" in pattern or "?" in pattern:
                p = Path(pattern)
                self._assert_no_path_traversal(p)
                # 统一使用 parent.glob(name) 避免绝对路径 glob 异常
                parent = p.parent
                matches = sorted(parent.glob(p.name)) if parent.exists() else []
                if not matches:
                    return None
                return matches[0]
            p = Path(pattern)
            self._assert_no_path_traversal(p)
            return p if p.exists() else None
        # static
        if self.source_path is None:
            return None
        return self.source_path if self.source_path.exists() else None

    def _sample_geotiff_projected(
        self, src_path: Path, lng: float, lat: float
    ) -> float | None:
        """GeoTIFF 专用：按栅格自身投影采样。

        UniversalDataReader 对部分 EASE-Grid GeoTIFF 返回 ``lat=None/lon=None``，
        导致 FY/SMAP 8 天块点查恒为 null。这里直接用 rasterio 读取栅格 CRS，
        将 WGS84 点位转换到栅格投影坐标，再最近邻采样。
        """
        with rasterio.open(src_path) as ds:
            if ds.crs is None:
                return None
            # 自校准坐标轴：部分 EPSG 投影（如 6933）在 always_xy=True 下仍返回 (y,x)。
            # 选择非中心、有限像元作为基准，比较直接输出与交换输出对像素中心的还原误差。
            transformer = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
            back = Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)
            row = min(max(ds.height // 3, 0), ds.height - 1)
            col = min(max(ds.width // 3, 0), ds.width - 1)
            tx0, ty0 = ds.transform * (col + 0.5, row + 0.5)
            base_lng, base_lat = back.transform(tx0, ty0)
            tx1, ty1 = transformer.transform(base_lng, base_lat)
            direct_score = abs(tx1 - tx0) + abs(ty1 - ty0)
            swapped_score = abs(tx1 - ty0) + abs(ty1 - tx0)
            need_swap = swapped_score < direct_score
            x, y = transformer.transform(lng, lat)
            if need_swap:
                x, y = y, x
            arr = ds.read(1, masked=True)
            try:
                row, col = ds.index(x, y)
            except Exception:
                return None
            if not (0 <= row < ds.height and 0 <= col < ds.width):
                return None
            val = arr[row, col]
            if np.ma.is_masked(val):
                return None
            out = float(val)
            return out if np.isfinite(out) else None

    # EASE-Grid 2.0 9km 标准参数（与 export_overlay_assets.py 同步）
    _EASE_GRID_9K_CRS = "EPSG:6933"
    _EASE_GRID_9K_PIXEL_SIZE = 9008.0552  # 米
    _EASE_GRID_9K_UL_X = -17367530.45  # 上左角 x（米）
    _EASE_GRID_9K_UL_Y = 7314540.83  # 上左角 y（米）

    def _sample_mat_ease_grid(
        self, src_path: Path, variable: str, lng: float, lat: float
    ) -> float | None:
        """对含 EASE-Grid Transform/CRS 元数据的 .mat 文件做投影采样。

        当 ``UniversalDataReader`` 无法从 .mat 中提取 lat/lon 坐标变量时，
        本方法读取 .mat 的 ``Transform`` 和 ``CRS`` 元数据，用 pyproj 将
        WGS84 查询点转换到源投影坐标系，再通过仿射变换映射到像素行列采样。

        若 .mat 无 Transform/CRS 元数据，回退到默认 EASE-Grid 9km 参数。
        """
        try:
            # 读取 .mat 文件（兼容 v5/v6 和 v7.3）
            mat_data: dict[str, Any] = {}
            try:
                from scipy.io import loadmat

                mat_data = loadmat(str(src_path))
                is_v73 = False
            except NotImplementedError:
                import h5py

                with h5py.File(str(src_path), "r") as f:
                    mat_data = {k: np.array(f[k]) for k in f.keys()}
                is_v73 = True

            if variable not in mat_data:
                return None

            values = np.array(mat_data[variable], dtype=np.float64)
            if values.ndim >= 2 and 1 in values.shape:
                values = values.squeeze()
            if is_v73 and values.ndim >= 2:
                values = values.T  # MAT v7.3 列优先转置

            if values.ndim != 2:
                return None

            n_lat, n_lon = values.shape

            # 尝试从 .mat 读取 Transform 和 CRS
            src_crs = self._EASE_GRID_9K_CRS
            pixel_size = self._EASE_GRID_9K_PIXEL_SIZE
            ul_x = self._EASE_GRID_9K_UL_X
            ul_y = self._EASE_GRID_9K_UL_Y

            if "Transform" in mat_data and "CRS" in mat_data:
                t = np.asarray(mat_data["Transform"]).ravel()
                if len(t) >= 6:
                    px = abs(float(t[1]))
                    scale = 18 if 400 < px < 600 else 1  # 500m → 9km
                    pixel_size = abs(float(t[1])) * scale
                    ul_x = float(t[0])
                    ul_y = float(t[3])
                    # CRS 可能是字符串或字符数组
                    crs_raw = mat_data["CRS"]
                    if isinstance(crs_raw, np.ndarray):
                        crs_flat = crs_raw.ravel()
                        if crs_flat.dtype.kind in ("U", "S"):
                            crs_str = str(crs_flat.ravel()[0])
                        else:
                            crs_str = "".join(
                                chr(int(c)) for c in crs_flat if 32 <= int(c) < 127
                            )
                    else:
                        crs_str = str(crs_raw)
                    if "6933" in crs_str:
                        src_crs = "EPSG:6933"

            # 将 WGS84 查询点转换到源投影坐标
            transformer = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
            x, y = transformer.transform(lng, lat)

            # 仿射变换 → 像素行列（origin = upper-left）
            col = (x - ul_x) / pixel_size
            row = (ul_y - y) / pixel_size

            row_int = int(round(row))
            col_int = int(round(col))

            if not (0 <= row_int < n_lat and 0 <= col_int < n_lon):
                return None

            val = float(values[row_int, col_int])
            if not np.isfinite(val):
                return None
            return val
        except Exception:
            return None

    def _sample_from_bounds_json(
        self, values: np.ndarray, lng: float, lat: float, time: str | None = None
    ) -> float | None:
        """当 .mat 缺少坐标变量且无 EASE-Grid 元数据时，用 bounds JSON
        构建线性 WGS84 网格做最近邻采样。

        适用于 WGS84 等经纬度网格数据（如 0.25° 干旱指数）。
        bounds JSON 记录了重投影后的 WGS84 边界，配合数据 shape
        即可构建线性坐标轴。

        注意：对非等经纬度投影（如 EASE-Grid）数据，此方法为近似采样，
        精度取决于投影变形程度。仅作为最后回退手段。
        """
        try:
            bounds_path = self.resolve_bounds(time)
            if not bounds_path.exists():
                return None
            bdata = json.loads(bounds_path.read_text(encoding="utf-8"))
            bounds = bdata.get("bounds")
            if not bounds or len(bounds) != 4:
                return None
            west, south, east, north = bounds

            if values.ndim != 2:
                return None
            n_lat, n_lon = values.shape

            # 构建线性 WGS84 坐标轴
            # 数据 origin = upper-left → 纬度从北到南降序
            lat_1d = np.linspace(north, south, n_lat)
            lon_1d = np.linspace(west, east, n_lon)

            row = int(np.argmin(np.abs(lat_1d - lat)))
            col = int(np.argmin(np.abs(lon_1d - lng)))

            if not (0 <= row < n_lat and 0 <= col < n_lon):
                return None

            val = float(values[row, col])
            return val if np.isfinite(val) else None
        except Exception:
            return None

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
                result["error"] = (
                    f"Source data file not found or not configured "
                    f"(layer={self.layer_id}, source_path={self.source_path})"
                )
                return result

            if self.source_reader == "geotiff":
                result["value"] = self._sample_geotiff_projected(src_path, lng, lat)
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
                # 回退 1：对 .mat 文件尝试 EASE-Grid 投影采样
                # （读取 Transform/CRS 元数据，将查询点投影到源坐标系采样）
                if self.source_reader == "mat" and self.source_variable:
                    val = self._sample_mat_ease_grid(
                        src_path, self.source_variable, lng, lat
                    )
                    if val is not None:
                        result["value"] = val
                        return result
                    result["error"] = (
                        f"MAT file lacks lat/lon variables and EASE-Grid "
                        f"sampling failed for {self.source_variable}"
                    )

                # 回退 2：用 bounds JSON 构建线性 WGS84 网格采样
                # （适用于等经纬度网格数据，如 0.25° 干旱指数）
                val = self._sample_from_bounds_json(values, lng, lat, time)
                if val is not None:
                    result["value"] = val
                    return result

                if "error" not in result:
                    result["error"] = (
                        "Source data lacks coordinate variables; "
                        "EASE-Grid and bounds-based reconstruction both failed"
                    )
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
# 数据根目录（相对 BACKEND_DATA_ROOT；空根 → 占位路径，exists()=False）
# ──────────────────────────────────────────────────────────────────────────────


def _data_join(*parts: str) -> Path:
    """拼接地理数据路径；未配置 data_root 时返回不存在的占位路径。"""
    from app.core.config import settings

    root = (getattr(settings, "data_root", None) or "").strip()
    if not root:
        return Path(".__cgda_no_data_root__").joinpath(*parts)
    return Path(root).joinpath(*parts)


_PROJECT_OUTPUT = _data_join("ProjectOutput", "2023-01_Omega_Inversion")
_DEM_DIR = _data_join("Geological", "DEM", "ETOPO_2022")
_GPCP_DIR = _data_join("Meteorological", "Precipitation", "GPCP", "dataset")
_STAGE2_ALIGNED = _PROJECT_OUTPUT / "stage2_aligned"
_OMEGA_SOURCE = _data_join("Inversion_Results", "smap_avg", "doy_017.mat")
_DEM_SOURCE_TIF = _DEM_DIR / "ETOPO_2022_v1_60s_N90W180_surface.tif"

# ── 课题组派生 9km EASE-Grid 数据根 ──────────────────────────────────────────
_INVERSION_RESULTS_ROOT = _data_join("Inversion_Results")
_SOIL_DDCA_H_DIR = _data_join("Soil_Moisture", "DDCA", "DDCA_DH", "H")

# ── Phase 2: 课题组 VOD/SM 产品族（2025-12 时间序列，EASE-Grid 9km）──────────
# SmapSoil_VOD_SM/YYYYMMDD.mat (v7.3 HDF5) 含 OMEGA / SM / VOD 三个变量，shape (1624, 3856)
_SMAP_SOIL_VOD_SM_DIR = _data_join("Soil_Moisture", "SMAP_Soil_VOD_SM")

_OVERLAY_PNG_ROOT = _PROJECT_OUTPUT / "_overlays"
"""所有导出 PNG 的统一存放目录（由 Tools/export_overlay_assets.py 生成）。"""


def _uniform_sample(tags: list[str], limit: int | None) -> list[str]:
    """对时间标签列表进行均匀采样，限制数量。"""
    if limit is not None and len(tags) > limit:
        step = max(1, len(tags) // limit)
        return tags[::step][:limit]
    return tags


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
    """从 GPCP NetCDF 目录采样时间标签（取最近 limit 个月）。

    源目录被清理而 PNG 资产仍在时，回退扫描 overlay PNG 目录
    （gpcp_YYYYMM.png），保证时间轴可用；此时 /overlay-value 点查询
    因源数据缺失而不可用。
    """
    tags: list[str] = []
    if _GPCP_DIR.exists():
        for f in sorted(_GPCP_DIR.glob("GPCPMON_L3_*_V3.2.nc4")):
            # GPCPMON_L3_198301_V3.2.nc4 -> 198301
            parts = f.stem.split("_")
            if len(parts) >= 3 and len(parts[2]) == 6 and parts[2].isdigit():
                tags.append(parts[2])
    if not tags:
        for f in sorted((_OVERLAY_PNG_ROOT / "gpcp_ts").glob("gpcp_*.png")):
            parts = f.stem.split("_")
            if len(parts) >= 2 and len(parts[1]) == 6 and parts[1].isdigit():
                tags.append(parts[1])
    return _uniform_sample(tags, limit)


def _date8_time_list(directory: Path, limit: int | None = None) -> list[str]:
    """通用 8 位日期时间序列标签扫描：YYYYMMDD.mat → 'YYYYMMDD'。

    扫描目录下所有 ``*.mat`` 文件，提取文件名 stem 为 8 位纯数字的标签。
    ``limit`` 不为 None 时进行均匀采样。

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
    return _uniform_sample(tags, limit)


_SMAP_TIMES = _smap_time_list()
_GPCP_TIMES = _gpcp_time_list(limit=24)
_SOIL_DDCA_TIMES = _date8_time_list(_SOIL_DDCA_H_DIR, limit=60)
# Phase 2: VOD/SM/Omega 2025-12 时间序列（31 天，全量不采样）
_VOD_SM_TIMES = _date8_time_list(_SMAP_SOIL_VOD_SM_DIR, limit=None)


# ──────────────────────────────────────────────────────────────────────────────
# 注册表
# ──────────────────────────────────────────────────────────────────────────────

# P1-2：线程安全注册表 — 并发 register/get/list 可能导致竞态
_REGISTRY: dict[str, OverlaySpec] = {}
_REGISTRY_LOCK = threading.Lock()


def _try_load_imported_overlay(layer_id: str) -> OverlaySpec | None:
    """Lazy-load an imported-* overlay from disk into the in-memory registry.

    Import commits may run in a Celery worker / one-off process while the
    FastAPI process has a separate ``_REGISTRY``. Rehydrate from
    ``IMPORTS_DIR/<layer_id>`` so ``/overlay-preview`` works cross-process.
    """
    if not layer_id.startswith("imported-"):
        return None
    try:
        from app.data_io.services.paths import IMPORTS_DIR
    except Exception:
        return None

    dest_dir = IMPORTS_DIR / layer_id
    bounds_path = dest_dir / "bounds.json"
    if not bounds_path.is_file():
        return None

    try:
        bounds_data = json.loads(bounds_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    meta = bounds_data.get("meta") if isinstance(bounds_data, dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    # Prefer meta.json when present (timeseries upserts write richer meta)
    meta_path = dest_dir / "meta.json"
    if meta_path.is_file():
        try:
            disk_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(disk_meta, dict):
                meta = {**meta, **disk_meta}
        except (OSError, json.JSONDecodeError):
            pass

    time_list = meta.get("time_list") if isinstance(meta.get("time_list"), list) else []
    time_list = [str(t) for t in time_list]
    has_time_previews = any(dest_dir.glob("preview_*.png"))
    has_static_preview = (dest_dir / "preview.png").is_file()
    category = str(
        meta.get("category")
        or ("time-series" if (time_list or has_time_previews) else "static")
    )
    # 时序层通常只有 preview_{time}.png，无根目录 preview.png
    if category == "time-series":
        if not has_time_previews and not has_static_preview:
            return None
    elif not has_static_preview:
        return None

    source_filename = meta.get("source_filename")
    source_path = dest_dir / str(source_filename) if source_filename else None
    if source_path is not None and not source_path.is_file():
        source_path = None
    if source_path is None:
        # Fall back to any source_*.tif / source.tif
        candidates = sorted(dest_dir.glob("source*.tif")) + sorted(
            dest_dir.glob("source*.tiff")
        )
        if candidates:
            source_path = candidates[0]

    if not time_list and has_time_previews:
        time_list = sorted(
            p.stem.removeprefix("preview_")
            for p in dest_dir.glob("preview_*.png")
            if p.stem.startswith("preview_")
        )
    default_time_raw = meta.get("default_time")
    default_time = (
        str(default_time_raw)
        if default_time_raw
        else (time_list[-1] if time_list else None)
    )
    source_pattern = None
    if category == "time-series" and any(dest_dir.glob("source_*.tif")):
        source_pattern = str(dest_dir / "source_{time}.tif")

    # OMEGA_BLOCK 对外统一为 OMEGA（与工作流组标签一致）
    label = str(meta.get("label") or "")
    if label.upper().startswith("OMEGA_BLOCK") or label.upper() == "OMEGA_BLOCK":
        meta["label"] = "OMEGA"

    spec = OverlaySpec(
        layer_id=layer_id,
        overlay_dir=dest_dir,
        png_filename="preview.png" if has_static_preview else None,
        bounds_filename="bounds.json",
        category=category,
        time_list=time_list,
        default_time=default_time,
        time_pattern="preview_{time}.png" if category == "time-series" else None,
        bounds_pattern="bounds_{time}.json" if category == "time-series" else None,
        palette=str(meta.get("palette") or "wind-blue"),
        opacity=float(meta.get("opacity") or 0.7),
        crs=str(meta.get("crs") or "EPSG:4326"),
        source_path=source_path if category != "time-series" else None,
        source_pattern=source_pattern,
        source_reader="geotiff"
        if (source_path is not None or source_pattern is not None)
        else "auto",
    )
    with _REGISTRY_LOCK:
        _REGISTRY[layer_id] = spec
    return spec


def register_overlay(spec: OverlaySpec) -> None:
    with _REGISTRY_LOCK:
        _REGISTRY[spec.layer_id] = spec


def unregister_overlay(layer_id: str) -> OverlaySpec | None:
    """Remove a dynamically registered overlay; returns the removed spec if any."""
    with _REGISTRY_LOCK:
        return _REGISTRY.pop(layer_id, None)


def get_overlay_spec(layer_id: str) -> OverlaySpec | None:
    with _REGISTRY_LOCK:
        spec = _REGISTRY.get(layer_id)
    if spec is not None:
        return spec
    return _try_load_imported_overlay(layer_id)


def list_overlay_ids() -> list[str]:
    with _REGISTRY_LOCK:
        ids = set(_REGISTRY.keys())
    try:
        from app.data_io.services.paths import IMPORTS_DIR

        if IMPORTS_DIR.is_dir():
            for child in IMPORTS_DIR.iterdir():
                if not (
                    child.is_dir()
                    and child.name.startswith("imported-")
                    and (child / "bounds.json").is_file()
                ):
                    continue
                has_preview = (child / "preview.png").is_file() or any(
                    child.glob("preview_*.png")
                )
                if has_preview:
                    ids.add(child.name)
    except Exception:
        pass
    return sorted(ids)


# ─── 静态图层 ─────────────────────────────────────────────────────────────────

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


# ─── 时间序列图层 ────────────────────────────────────────────────────────────

# SMAP 土壤湿度时间序列（2023-01，13 天）
register_overlay(
    OverlaySpec(
        layer_id="ref-smap-sm-202512-l3",
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

# 源数据（相对 BACKEND_DATA_ROOT）
_GEBCO_NC = _data_join("Geological", "DEM", "GEBCO_2024.nc")
_CMFD_TIF = _data_join("Meteorological", "Precipitation", "pre_2002_01.tif")
_CLCD_TIF = _data_join("Ecological_Vegetation", "LandCover", "CLCD_v01_1997.tif")
_BIOMASS_NC = _data_join(
    "Ecological_Vegetation",
    "Biomass",
    "ESACCI-BIOMASS-L4-AGB-MERGED-100m-2020-fv6.0.nc",
)
_ERA5_DWAA_TIF = _data_join("Hazards", "DWAA_result", "DW_T7", "ERA5_2020_DW_SMCI.tif")
_ERA5_WDAA_TIF = _data_join("Hazards", "DWAA_result", "WD_T7", "ERA5_2020_WD_SMCI.tif")
_CO2_TIF = _data_join(
    "Atmospheric", "CO2", "MidLayerCO2Column", "TIF", "MeanCarbonDioxide.tif"
)
_SOIL_DDCA_MAT = _data_join("Soil_Moisture", "DDCA", "DDCA_DH", "H", "20150401.mat")
_OMEGA_FY_MAT = _data_join("Inversion_Results", "fy_avg", "doy_025.mat")
_FOREST_RATIO_MAT = _data_join("Inversion_Results", "Forest_Ratio_9KM_2020.mat")

# ── SMAP 辅助数据（Soil_Moisture/SMAP_Auxiliary_Data，静态参数场）──────────────
# Albedo/BD/SF/B/CF/H/IGBP 为 EASE-Grid 9km（v7.3 HDF5），shape (3856, 1624)；
# Koppen 为 0.083° 全球网格，shape (4320, 2160)；VI_v_qa 为 v5 格式，shape (1624, 3856)
_SMAP_AUX_ALBEDO_MAT = _data_join("Soil_Moisture", "SMAP_Auxiliary_Data", "Albedo.mat")
_SMAP_AUX_BD_MAT = _data_join("Soil_Moisture", "SMAP_Auxiliary_Data", "BD.mat")
_SMAP_AUX_SF_MAT = _data_join("Soil_Moisture", "SMAP_Auxiliary_Data", "SF.mat")
_SMAP_AUX_B_MAT = _data_join("Soil_Moisture", "SMAP_Auxiliary_Data", "B.mat")
_SMAP_AUX_CF_MAT = _data_join("Soil_Moisture", "SMAP_Auxiliary_Data", "CF.mat")
_SMAP_AUX_H_MAT = _data_join("Soil_Moisture", "SMAP_Auxiliary_Data", "H.mat")
_SMAP_AUX_IGBP_MAT = _data_join(
    "Soil_Moisture", "SMAP_Auxiliary_Data", "IGBP_9km_12.mat"
)
_SMAP_AUX_KOPPEN_MAT = _data_join(
    "Soil_Moisture", "SMAP_Auxiliary_Data", "Koppen_present_083.mat"
)
_SMAP_AUX_VI_V_QA_MAT = _data_join(
    "Soil_Moisture", "SMAP_Auxiliary_Data", "VI_v_qa.mat"
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
        layer_id="ref-ddca-sm-201504-202512",
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


# SMAP 辅助数据（Soil_Moisture/SMAP_Auxiliary_Data，静态参数场）
# 与 forest-ratio 同属静态图层；按变量分别暴露为独立 overlay，便于点查询与配色。
# 注意：VI_v_qa.mat 为 v5 格式（scipy 可读），其余为 v7.3 HDF5；reader 统一 "mat"，
# 由 source_reader 按实际格式自动适配（h5py/scipy）。

# Albedo — 地表反照率（EASE-Grid 9km）
register_overlay(
    OverlaySpec(
        layer_id="smap-aux-albedo",
        overlay_dir=_OVERLAY_PNG_ROOT / "smap_aux_albedo",
        png_filename="smap_aux_albedo_overlay.png",
        bounds_filename="smap_aux_albedo_overlay_bounds.json",
        category="static",
        palette="YlOrRd",
        vmin=0.0,
        vmax=0.0953,
        unit="",
        opacity=0.8,
        source_path=_SMAP_AUX_ALBEDO_MAT,
        source_variable="ALBEDO",
        source_reader="mat",
    )
)

# BD — 土壤容重（EASE-Grid 9km）
register_overlay(
    OverlaySpec(
        layer_id="smap-aux-bd",
        overlay_dir=_OVERLAY_PNG_ROOT / "smap_aux_bd",
        png_filename="smap_aux_bd_overlay.png",
        bounds_filename="smap_aux_bd_overlay_bounds.json",
        category="static",
        palette="YlOrBr",
        vmin=0.8843,
        vmax=1.5675,
        unit="g/cm³",
        opacity=0.8,
        source_path=_SMAP_AUX_BD_MAT,
        source_variable="BD",
        source_reader="mat",
    )
)

# SF — SMAP 辅助参数场（EASE-Grid 9km；中国区实测 p1~p99 = 0.29~19.1，非 0–1 分数，语义待课题组确认）
register_overlay(
    OverlaySpec(
        layer_id="smap-aux-sf",
        overlay_dir=_OVERLAY_PNG_ROOT / "smap_aux_sf",
        png_filename="smap_aux_sf_overlay.png",
        bounds_filename="smap_aux_sf_overlay_bounds.json",
        category="static",
        palette="YlGn",
        vmin=0.2904,
        vmax=19.1067,
        unit="",
        opacity=0.8,
        source_path=_SMAP_AUX_SF_MAT,
        source_variable="SF",
        source_reader="mat",
    )
)

# B — B 参数（EASE-Grid 9km）
register_overlay(
    OverlaySpec(
        layer_id="smap-aux-b",
        overlay_dir=_OVERLAY_PNG_ROOT / "smap_aux_b",
        png_filename="smap_aux_b_overlay.png",
        bounds_filename="smap_aux_b_overlay_bounds.json",
        category="static",
        palette="RdBu",
        vmin=0.0,
        vmax=0.1299,
        unit="",
        opacity=0.8,
        source_path=_SMAP_AUX_B_MAT,
        source_variable="B",
        source_reader="mat",
    )
)

# CF — 粘粒分数（EASE-Grid 9km）
register_overlay(
    OverlaySpec(
        layer_id="smap-aux-cf",
        overlay_dir=_OVERLAY_PNG_ROOT / "smap_aux_cf",
        png_filename="smap_aux_cf_overlay.png",
        bounds_filename="smap_aux_cf_overlay_bounds.json",
        category="static",
        palette="PuBu",
        vmin=0.0119,
        vmax=0.396,
        unit="fraction",
        opacity=0.8,
        source_path=_SMAP_AUX_CF_MAT,
        source_variable="CF",
        source_reader="mat",
    )
)

# H — H 参数（EASE-Grid 9km）
register_overlay(
    OverlaySpec(
        layer_id="smap-aux-h",
        overlay_dir=_OVERLAY_PNG_ROOT / "smap_aux_h",
        png_filename="smap_aux_h_overlay.png",
        bounds_filename="smap_aux_h_overlay_bounds.json",
        category="static",
        palette="Oranges",
        vmin=0.1833,
        vmax=2.2918,
        unit="",
        opacity=0.8,
        source_path=_SMAP_AUX_H_MAT,
        source_variable="H",
        source_reader="mat",
    )
)

# IGBP 土地覆盖分类（EASE-Grid 9km，1~17 类）
register_overlay(
    OverlaySpec(
        layer_id="smap-aux-igbp",
        overlay_dir=_OVERLAY_PNG_ROOT / "smap_aux_igbp",
        png_filename="smap_aux_igbp_overlay.png",
        bounds_filename="smap_aux_igbp_overlay_bounds.json",
        category="static",
        palette="igbp-landcover-ramp",
        vmin=1,
        vmax=17,
        unit="class",
        opacity=0.8,
        source_path=_SMAP_AUX_IGBP_MAT,
        source_variable="IGBP_9km_12",
        source_reader="mat",
    )
)

# Koppen 气候分类（0.083° 全球网格，1~30 类）
register_overlay(
    OverlaySpec(
        layer_id="smap-aux-koppen",
        overlay_dir=_OVERLAY_PNG_ROOT / "smap_aux_koppen",
        png_filename="smap_aux_koppen_overlay.png",
        bounds_filename="smap_aux_koppen_overlay_bounds.json",
        category="static",
        palette="Set3",
        vmin=1,
        vmax=30,
        unit="class",
        opacity=0.8,
        source_path=_SMAP_AUX_KOPPEN_MAT,
        source_variable="Koppen",
        source_reader="mat",
    )
)

# VI/NDVI 均值（v5 格式，shape (1624, 3856)，注意轴序与 EASE-Grid 9km 其余场相反）
register_overlay(
    OverlaySpec(
        layer_id="smap-aux-vi-qa",
        overlay_dir=_OVERLAY_PNG_ROOT / "smap_aux_vi_qa",
        png_filename="smap_aux_vi_qa_overlay.png",
        bounds_filename="smap_aux_vi_qa_overlay_bounds.json",
        category="static",
        palette="RdYlGn",
        vmin=0.0398,
        vmax=0.8535,
        unit="",
        opacity=0.8,
        source_path=_SMAP_AUX_VI_V_QA_MAT,
        source_variable="NDVI_v_mean",
        source_reader="mat",
    )
)


# ─── Phase 2: 课题组 VOD/SM/Omega 2025-12 产品族 ──────────────────────────────
# 数据源：I:\Geograph_DataSet\Soil_Moisture\SMAP_Soil_VOD_SM\YYYYMMDD.mat
# v7.3 HDF5，含 OMEGA / SM / VOD 三个变量，shape (1624, 3856) on EASE-Grid 9km
# 每个图层导出 31 天（2025-12-01 ~ 2025-12-31）的 PNG + bounds JSON

# 注：VOD/ω 独立展示图层已于 5cfba8e 有意移除（固化汇报图层下线，产物走
# 工作流 run 结果图层）；SmapSoil_VOD_SM 的 SM 展示层保留在下方。

# SMAP/FY/站点融合土壤水分产品（2025-12，31 天；本层展示 SM，VOD/ω 经工作流结果图层查看）
register_overlay(
    OverlaySpec(
        layer_id="prod-fy_smap_station-sm_vod_omega-202512-fusion",
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


def read_bounds(layer_id: str, time: str | None = None) -> dict[str, Any]:
    """读取 bounds JSON 并附加元数据。"""
    spec = get_overlay_spec(layer_id)
    if spec is None:
        raise OverlayNotFoundError(f"No overlay for layer: {layer_id}")
    bounds_path = spec.resolve_bounds(time)
    if not bounds_path.exists():
        raise OverlayNotFoundError(
            f"Overlay bounds file not found: {bounds_path.name}",
        )
    data = json.loads(bounds_path.read_text(encoding="utf-8"))
    # 合并元数据
    meta = spec.meta_dict()
    if time is not None:
        meta["current_time"] = time
    from app.services.overlay_tile_service import tile_meta_fields

    source_path = spec.resolve_source_path(time)
    supports_tiles = bool(
        source_path is not None
        and source_path.suffix.lower() in {".tif", ".tiff", ".geotiff", ".cog"}
    )
    meta.update(tile_meta_fields(layer_id))
    meta["supports_xyz_tiles"] = supports_tiles
    from app.services.overlay_recolor import overlay_supports_recolor

    meta["supports_recolor"] = overlay_supports_recolor(layer_id, time)
    data.setdefault("meta", {}).update(meta)
    # 确保 bounds 字段存在
    if "bounds" not in data:
        raise OverlayConfigError(
            f"Bounds JSON missing 'bounds' field: {bounds_path.name}",
        )
    # ── bounds 合理性校验 ──────────────────────────────────────────────────
    # 检测重投影失败回退到全球 bounds 的典型模式，以及坐标轴值超出
    # WGS84 范围（可能是投影坐标被误当作经纬度）。
    b = data["bounds"]
    if isinstance(b, list) and len(b) == 4:
        w, s, e, n = b
        _is_global = w == -180.0 and s == -90.0 and e == 180.0 and n == 90.0
        _out_of_wgs84 = (
            not all(isinstance(v, (int, float)) for v in b)
            or abs(w) > 180.1
            or abs(e) > 360.1
            or abs(s) > 90.1
            or abs(n) > 90.1
        )
        if _is_global or _out_of_wgs84:
            data.setdefault("meta", {})["bounds_warning"] = (
                "Bounds appear to be global or out of WGS84 range — "
                "possible reproject failure or CRS mismatch. "
                "Run Tools/export_overlay_assets.py to regenerate."
            )
    return data


def read_png_bytes(layer_id: str, time: str | None = None) -> bytes:
    """读取 PNG 字节。"""
    spec = get_overlay_spec(layer_id)
    if spec is None:
        raise OverlayNotFoundError(f"No overlay for layer: {layer_id}")
    png_path = spec.resolve_png(time)
    if not png_path.exists():
        raise OverlayNotFoundError(
            f"Overlay preview file not found: {png_path.name}",
        )
    return png_path.read_bytes()
