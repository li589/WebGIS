"""Dynamic overlay PNG recolor from source rasters (MAT/NC/GeoTIFF)."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from app.data_io.services.grid_presets import GRID_PRESETS, ease_grid_from_shape
from app.data_io.services.grid_reproject import reproject_to_mercator_linear
from app.services.overlay_registry import get_overlay_spec, read_png_bytes
from app.services.raster_preview_service import (
    colorize_array_to_rgba,
    encode_rgba_png,
    normalize_nodata_mode,
    resolve_palette_id,
)

logger = logging.getLogger(__name__)

_MAX_PREVIEW_EDGE = 2048

# ── EASE 源重投影（2026-08-24 P2 收敛）────────────────────────────────────
# EASE 几何（CRS/角点/分辨率）唯一真源：app/data_io/services/grid_presets.py
# （EASE_UL_BY_CRS + GRID_PRESETS）；重投影实现唯一真源：
# app/data_io/services/grid_reproject.py（与 Tools 导出脚本共享）。
# 本模块不再自带任何 EASE 常数，且按 shape 自动匹配**任意** EASE 网格
# （9/25/36/3km 全球、南北半球 LAEA、EASE1），不再硬编码 9km。
#
# 背景：SMAP 辅助数据 / 景观多样性等 .mat 源为 EASE-Grid 2.0 等积圆柱投影
# （EPSG:6933）。其行并非纬度均匀，直接按行列当作等经纬贴图会在中高纬产生
# 巨大几何偏差——必须先把 EASE 源重采样为 Web Mercator 线性网格
# （行/列在 EPSG:3857 平面均匀），与烘焙资产一致，MapLibre ImageSource
# 四角线性插值才地理精确。
# 烘焙 smap-aux / landscape-metrics 资产默认 0.25°（赤道）全球全幅 → 1440×1440
_EASE_GLOBAL_TARGET_DEG = 0.25
# 兼容别名（Test/backend/test_overlay_recolor_grid_downsample.py 引用）：
# EASE-Grid 2.0 全球 9km 形状 (rows, cols)。
_EASE_GLOBAL_9K_SHAPE: tuple[int, int] = (
    int(GRID_PRESETS["ease2-global-9km"]["rows"]),
    int(GRID_PRESETS["ease2-global-9km"]["cols"]),
)


def _reproject_ease_to_mercator_linear(
    data: np.ndarray,
    *,
    target_resolution: float = _EASE_GLOBAL_TARGET_DEG,
) -> np.ndarray:
    """把 EASE 网格源（按 shape 匹配任意 preset）重投影到 Mercator 线性网格。

    算法见 :func:`app.data_io.services.grid_reproject.reproject_to_mercator_linear`
    （与 Tools/export_overlay_assets.py 共享同一实现）。行/列在 EPSG:3857
    平面均匀，四角反算的 bounds 为 Mercator 全幅 (-180, -85.0511, 180, 85.0511)。
    nearest 采样（预览用途）。

    Args:
        data: (nrow, ncol) 2D EASE-Grid 数组（任一 EASE preset 形状）。
        target_resolution: 赤道处输出分辨率（度）；默认与烘焙资产一致的 0.25°。

    Returns:
        重投影后的 (H, W) 数组。非 EASE 形状（不匹配 preset）或重投影失败时
        返回原数组（由调用方按通用路径继续，保证 recolor 不崩、仍可出图）。
    """
    matched = ease_grid_from_shape(tuple(data.shape))
    if matched is None:
        return data
    _preset_id, crs, src_transform = matched
    try:
        out, _bounds = reproject_to_mercator_linear(
            data,
            src_transform,
            crs,
            target_resolution=target_resolution,
        )
        return out
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


def _layer_wgs84_window(spec: Any, time: str | None) -> tuple[float, float, float, float] | None:
    """读图层 bounds.json 的 WGS84 窗口（recolor Mercator 线性对齐的裁剪窗）。

    烘焙 preview.png（导入链 render_cog_preview_reprojected target=3857 /
    Tools _reproject_to_mercator_linear）均为 Web Mercator 内容、bounds.json
    报其 WGS84 四角。recolor 输出必须贴同一窗口做 Mercator 线性重采样，
    否则四角线性插值下中高纬错位（"动态重着色后图层变形/不清晰"根因）。
    """
    try:
        from app.services.overlay_registry import read_bounds

        data = read_bounds(spec.layer_id, time)
        raw = data.get("bounds") if isinstance(data, dict) else None
        if (
            isinstance(raw, (list, tuple))
            and len(raw) == 4
            and all(isinstance(v, (int, float)) and np.isfinite(v) for v in raw)
        ):
            w, s, e, n = (float(v) for v in raw)
            if w < e and s < n:
                return (w, s, e, n)
    except Exception:
        logger.debug("layer bounds read failed for %s", getattr(spec, "layer_id", "?"))
    return None


def _reproject_geographic_to_mercator_linear(
    values: np.ndarray,
    src_transform: Any,
    src_crs: str,
    clip_bounds: tuple[float, float, float, float] | None,
) -> np.ndarray:
    """地理/任意 CRS 栅格 → 窗口 Mercator 线性网格（失败原样返回）。"""
    try:
        out, _bounds = reproject_to_mercator_linear(
            values,
            src_transform,
            src_crs,
            clip_bounds=clip_bounds,
        )
        return out
    except Exception:
        logger.warning(
            "overlay geographic->Mercator reproject failed (keep native grid)",
            exc_info=True,
        )
        return values


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
                values = np.ma.filled(np.ma.array(band), np.nan).astype(np.float32)
                # 2026-08-24 三联报障 D：重着色输出必须与烘焙 preview 同为
                # 窗口 Mercator 线性网格（导入链烘焙走 3857 重投影）；否则
                # 换源后中高纬四角插值错位（"变不清晰"）。out_shape 读取时
                # transform 需按比例缩放。
                if ds.crs is not None:
                    from rasterio.transform import Affine

                    src_transform = ds.transform * Affine.scale(
                        ds.width / ow, ds.height / oh
                    )
                    clip = _layer_wgs84_window(spec, time)
                    if clip is not None:
                        values = _reproject_geographic_to_mercator_linear(
                            values, src_transform, str(ds.crs), clip
                        )
                return values
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
        # EASE 网格源（9/25/36/3km 全球、半球 LAEA、EASE1——按 shape 匹配
        # preset；行非纬度均匀）先重投影为 Mercator 线性网格，与烘焙资产
        # 几何一致（bounds ±85.0511 全幅）。非 EASE 形状原样返回，重投影
        # 失败时回退通用路径。
        shape_before = values.shape
        values = _reproject_ease_to_mercator_linear(values)
        # 2026-08-24 三联报障 D（续）：非 EASE 的等经纬 .mat/.nc 源（如
        # aridity/hfp/landcover 中国区 0.25°）同样要对齐烘焙几何——行重采样
        # 为窗口 Mercator y 均匀。仅当 1D 均匀 lat/lon 与地理 CRS 时执行
        # （EASE 已对齐的网格不再二次重投影）。
        if values.shape == shape_before:
            values = _reproject_mat_grid_to_mercator_linear(
                values, data_array, spec, time
            )
        values = _reproject_mat_grid_to_mercator_linear(
            values, data_array, spec, time
        )
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


def _reproject_mat_grid_to_mercator_linear(
    values: np.ndarray,
    data_array: Any,
    spec: Any,
    time: str | None,
) -> np.ndarray:
    """带 1D lat/lon 的等经纬网格 → 窗口 Mercator 线性网格（不对齐时原样返回）。

    中心坐标（Point）源按半步长外扩为边缘（PixelIsArea）后建仿射；
    curvilinear（2D lat/lon）或投影 CRS 非 4326/4490 时跳过（保持旧行为）。
    """
    try:
        lat = getattr(data_array, "lat", None)
        lon = getattr(data_array, "lon", None)
        if lat is None or lon is None:
            return values
        lat_arr = np.atleast_1d(np.asarray(lat, dtype=np.float64))
        lon_arr = np.atleast_1d(np.asarray(lon, dtype=np.float64))
        if lat_arr.ndim != 1 or lon_arr.ndim != 1:
            return values  # 2D curvilinear 网格不处理
        n_lat, n_lon = values.shape
        if lat_arr.size < 2 or lon_arr.size < 2:
            return values
        crs_raw = str(getattr(data_array, "crs", "") or "").strip().upper()
        if crs_raw not in {"", "EPSG:4326", "4326", "EPSG:4490", "4490"}:
            return values
        clip = _layer_wgs84_window(spec, time)
        if clip is None:
            return values  # 无窗口无法对齐烘焙几何，保持旧行为
        from app.data_io.services.cell_registration import coords_to_area_bounds

        normalized = coords_to_area_bounds(lat_arr, lon_arr, (n_lat, n_lon))
        if normalized is None:
            return values
        (west, south, east, north), _reg = normalized
        from rasterio.transform import from_origin

        src_transform = from_origin(
            west,
            north,
            (east - west) / n_lon,
            (north - south) / n_lat,
        )
        # 源坐标覆盖必须包含目标窗口（含容差），否则重投影输出空白
        tol = max((east - west) * 0.01, (north - south) * 0.01)
        if (
            west > clip[0] + tol
            or east < clip[2] - tol
            or south > clip[1] + tol
            or north < clip[3] - tol
        ):
            return values
        return _reproject_geographic_to_mercator_linear(
            values, src_transform, "EPSG:4326", clip
        )
    except Exception:
        logger.warning("overlay mat grid align failed", exc_info=True)
        return values


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
