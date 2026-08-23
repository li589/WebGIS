"""Dynamic overlay PNG recolor from source rasters (MAT/NC/GeoTIFF)."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from app.services.overlay_registry import get_overlay_spec, read_png_bytes
from app.services.raster_preview_service import (
    colorize_array_to_rgba,
    encode_rgba_png,
    normalize_nodata_mode,
    resolve_palette_id,
)

logger = logging.getLogger(__name__)

_MAX_PREVIEW_EDGE = 2048

# ── EASE-Grid 2.0 全球 9km 几何（与 Tools/export_overlay_assets.py 一致）────────
# 实际 SMAP 辅助数据 / 景观多样性等 .mat 源为 EASE-Grid 2.0 等积圆柱投影
# （EPSG:6933）。其行并非纬度均匀，直接按行列当作等经纬贴图会在中高纬产生
# 巨大几何偏差——必须先把 EASE 源重采样为 Web Mercator 线性网格
# （行/列在 EPSG:3857 平面均匀），与烘焙资产一致，MapLibre ImageSource
# 四角线性插值才地理精确。
_EASE_GRID_9K_CRS = "EPSG:6933"
_EASE_GRID_9K_PIXEL_SIZE = 9008.0552  # 米（= 18 × 500.4475，NSIDC 标准）
# EASE-Grid 2.0 全球 9km 上左角（米，固定）与网格形状（row=lat≈, col=lon≈）
_EASE_EASE_UL = (-17367530.45, 7314540.83)
_EASE_GLOBAL_9K_SHAPE: tuple[int, int] = (1624, 3856)
# Web Mercator（EPSG:3857）纬度极限：MapLibre ImageSource 四角无法表示 ±90°，
# 超出即渲染失败 —— 因此重投影目标用 ±85.0511° 全幅。
_MERCATOR_MAX_LAT = 85.0511287798066
_MERCATOR_MAX_Y = 20037508.342789244
_METERS_PER_DEGREE_EQUATOR = 111319.49079327358
# 烘焙 smap-aux / landscape-metrics 资产默认 0.25°（赤道）全球全幅 → 1440×1440
_EASE_GLOBAL_TARGET_DEG = 0.25


def _is_ease_global_9k(shape: tuple[int, int]) -> bool:
    """判断二维数组是否为 EASE-Grid 2.0 全球 9km 网格（按固定形状识别）。

    这些 .mat 源（SMAP 辅助数据、SHDI 景观多样性等）只有数据变量，不携带
    lat/lon 坐标，因此只能靠网格形状识别。其余 mat/nc 源走通用均匀重采样。
    """
    return tuple(shape) == _EASE_GLOBAL_9K_SHAPE


def _reproject_ease_to_mercator_linear(
    data: np.ndarray,
    *,
    target_resolution: float = _EASE_GLOBAL_TARGET_DEG,
) -> np.ndarray:
    """把 EASE-Grid 2.0 全球 9km 源重投影到 Web Mercator 线性网格（1440×1440）。

    算法与 Tools/export_overlay_assets.py::_reproject_to_mercator_linear 一致
    （避免 import 整个 Tools 模块——其顶层会拉入 matplotlib 并解析 data_root）：
    行/列在 EPSG:3857 平面均匀，四角反算的 bounds 为 Mercator 全幅
    (-180, -85.0511, 180, 85.0511)。nearest 采样（预览用途）。

    Args:
        data: (nrow, ncol) 2D EASE-Grid 数组（EPSG:6933）。
        target_resolution: 赤道处输出分辨率（度）；默认与烘焙资产一致的 0.25°。

    Returns:
        重投影后的 (H, W) 数组。失败时返回原数组（由调用方按通用路径继续，
        保证 recolor 不崩、仍可出图）。
    """
    try:
        from rasterio.enums import Resampling
        from rasterio.transform import from_origin
        from rasterio.warp import reproject

        res_m = target_resolution * _METERS_PER_DEGREE_EQUATOR
        west_m = south_m = -_MERCATOR_MAX_Y
        east_m = north_m = _MERCATOR_MAX_Y
        width = max(1, int(round((east_m - west_m) / res_m)))
        height = max(1, int(round((north_m - south_m) / res_m)))
        dst_transform = from_origin(west_m, north_m, res_m, res_m)

        # EASE 源仿射：上左角固定、像素 9008.0552m 向下（列北增）、不旋转
        ul_x, ul_y = _EASE_EASE_UL
        src_transform = from_origin(
            ul_x, ul_y, _EASE_GRID_9K_PIXEL_SIZE, _EASE_GRID_9K_PIXEL_SIZE
        )

        dst = np.full((height, width), np.nan, dtype=np.float64)
        reproject(
            source=data.astype(np.float64),
            destination=dst,
            src_transform=src_transform,
            src_crs=_EASE_GRID_9K_CRS,
            dst_transform=dst_transform,
            dst_crs="EPSG:3857",
            resampling=Resampling.nearest,
            src_nodata=np.nan,
            dst_nodata=np.nan,
        )
        return dst
    except Exception:
        logger.warning(
            "overlay EASE->Mercator reproject failed (fall back to even downsample)",
            exc_info=True,
        )
        return data


def overlay_supports_recolor(layer_id: str, time: str | None = None) -> bool:
    spec = get_overlay_spec(layer_id)
    if spec is None:
        return False
    path = spec.resolve_source_path(time)
    return path is not None and path.is_file()


def _style_requested(
    *,
    palette: str | None,
    min_value: float | None,
    max_value: float | None,
    nodata_mode: str | None,
    nodata_color: str | None,
) -> bool:
    if palette and str(palette).strip():
        return True
    if min_value is not None or max_value is not None:
        return True
    if nodata_mode and normalize_nodata_mode(nodata_mode) != "transparent":
        return True
    if nodata_color and str(nodata_color).strip():
        return True
    return False


def _load_source_grid(spec: Any, time: str | None) -> np.ndarray | None:
    src_path = spec.resolve_source_path(time)
    if src_path is None or not src_path.is_file():
        return None
    suffix = src_path.suffix.lower()
    if suffix in {".tif", ".tiff", ".geotiff", ".cog"}:
        try:
            import rasterio
            from rasterio.enums import Resampling

            with rasterio.open(src_path) as ds:
                h = min(int(ds.height), _MAX_PREVIEW_EDGE)
                w = min(int(ds.width), _MAX_PREVIEW_EDGE)
                # keep aspect
                scale = min(
                    _MAX_PREVIEW_EDGE / max(ds.height, 1),
                    _MAX_PREVIEW_EDGE / max(ds.width, 1),
                    1.0,
                )
                oh = max(1, int(round(ds.height * scale)))
                ow = max(1, int(round(ds.width * scale)))
                band = ds.read(
                    1,
                    out_shape=(oh, ow),
                    resampling=Resampling.bilinear,
                    masked=True,
                )
                return np.ma.filled(np.ma.array(band), np.nan).astype(np.float32)
        except Exception:
            logger.warning("overlay geotiff load failed %s", src_path, exc_info=True)
            return None

    try:
        from data_access.universal_reader import UniversalDataReader

        reader = UniversalDataReader(src_path)
        variable = spec.source_variable if spec.source_reader != "geotiff" else None
        data_array = reader.read_variable(variable=variable)
        values = np.asarray(data_array.values, dtype=np.float32)
        if values.ndim == 3:
            values = values[0]
        if values.ndim != 2:
            return None
        # EASE-Grid 2.0 全球 9km 源（行非纬度均匀）先重投影为 Mercator 线性网格，
        # 与烘焙资产几何一致（bounds ±85.0511 全幅）。重投影失败时回退通用路径。
        if _is_ease_global_9k(values.shape):
            values = _reproject_ease_to_mercator_linear(values)
        # Downsample large grids for preview —— 全覆盖均匀重采样（nearest）。
        # 旧实现 ``values[::rs, ::cs][:oh, :ow]`` 在 scale≈0.53 时 rs=cs=1，
        # 退化为左上角纯裁剪（全球 EASE 网格只显示 53%×53% 再拉伸全屏的根因）。
        h, w = values.shape
        scale = min(_MAX_PREVIEW_EDGE / max(h, 1), _MAX_PREVIEW_EDGE / max(w, 1), 1.0)
        if scale < 1.0:
            oh = max(1, int(round(h * scale)))
            ow = max(1, int(round(w * scale)))
            rows = np.linspace(0, h - 1, oh).astype(int)
            cols = np.linspace(0, w - 1, ow).astype(int)
            values = values[np.ix_(rows, cols)]
        return values
    except Exception:
        logger.warning("overlay source load failed %s", src_path, exc_info=True)
        return None


def render_overlay_preview_styled(
    layer_id: str,
    *,
    time: str | None = None,
    palette: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    nodata_mode: str | None = None,
    nodata_color: str | None = None,
) -> bytes:
    """Return styled PNG when source exists and style query present; else baked PNG."""
    spec = get_overlay_spec(layer_id)
    if spec is None:
        return read_png_bytes(layer_id, time)

    wants_style = _style_requested(
        palette=palette,
        min_value=min_value,
        max_value=max_value,
        nodata_mode=nodata_mode,
        nodata_color=nodata_color,
    )
    if not wants_style or not overlay_supports_recolor(layer_id, time):
        return read_png_bytes(layer_id, time)

    grid = _load_source_grid(spec, time)
    if grid is None:
        return read_png_bytes(layer_id, time)

    pal = resolve_palette_id(palette or spec.palette)
    vmin = min_value if min_value is not None else spec.vmin
    vmax = max_value if max_value is not None else spec.vmax
    rgba = colorize_array_to_rgba(
        grid,
        palette=pal,
        min_value=vmin,
        max_value=vmax,
        nodata_mode=nodata_mode,
        nodata_color=nodata_color,
    )
    return encode_rgba_png(rgba)
