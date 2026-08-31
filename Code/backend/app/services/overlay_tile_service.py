"""Render Web Mercator XYZ PNG tiles from imported overlay GeoTIFF sources."""

from __future__ import annotations

import io
import logging
import math
import threading
from collections import OrderedDict
from functools import lru_cache
from typing import Any

import numpy as np

from app.services.raster_preview_service import (
    colorize_array_to_rgba,
    encode_rgba_png,
    normalize_nodata_mode,
    resolve_palette_id,
)

logger = logging.getLogger(__name__)

_WEB_MERCATOR_MAX_LAT = 85.0511287798066
_MIN_ZOOM = 0
# 与底图一致；过低时深缩放只能 overzoom 糊图，甚至看起来像「消失」
_MAX_ZOOM = 18
_TILE_SIZE = 256
# <0：有 GeoTIFF 时直接走 XYZ 瓦片，避免 1024px overview PNG 被放大后模糊/闪没
_OVERVIEW_MAX_ZOOM = -1.0
# 巨型源（任一边 > 该值）启用降采样金字塔：无 overview/未分块（stripped）
# 的源每行是一个 strip，任何窗口 warp 都要整行读盘——CLCD_v01（228579×
# 131361、821MB、stripped、无 overview）单个 z2 瓦片 warp 实测 >8 分钟，
# 前端低层级十几张瓦片只有个别在网关超时前完成 = 用户看到"只显示海南
# 广西一带条带"（2026-08-24 报障）。低层级瓦片改从一次性降采样网格渲染。
_PYRAMID_TRIGGER_EDGE = 4096
_PYRAMID_MAX_EDGE = 4096
# 金字塔构建串行锁 + 手动 LRU：并发瓦片请求 miss 时同时触发多次全图
# 降采样读（CLCD 821MB × N 线程同时扫盘）。全程持锁串行构建，首个请求
# 构建、其余等待后命中缓存（lru_cache 无法与锁组合——miss 调用本身即执行）。
_PYRAMID_BUILD_LOCK = threading.Lock()
_PYRAMID_CACHE: "OrderedDict[tuple[str, int, int], Any]" = OrderedDict()


def _source_pyramid(
    source_path: str,
    band: int,
    mtime_ns: int,
) -> tuple[np.ndarray, Any, str, float, float, float, float] | None:
    """巨型源的进程内降采样金字塔（CLCD 报障修复）。

    Returns:
        ``(values, transform, crs, left, bottom, right, top)``；源不大或读取
        失败返回 None（走直读路径）。按 (path, band, mtime) 缓存；首次构建
        需一次全图降采样读（CLCD ~2 分钟，后续瓦片/样式全部秒级命中）。
        categorical 数据用 nearest 保类别不被平均出假值。
    """
    key = (source_path, int(band), int(mtime_ns))
    with _PYRAMID_BUILD_LOCK:
        if key in _PYRAMID_CACHE:
            _PYRAMID_CACHE.move_to_end(key)
            return _PYRAMID_CACHE[key]
        result = _build_source_pyramid(source_path, band)
        _PYRAMID_CACHE[key] = result
        while len(_PYRAMID_CACHE) > 8:
            _PYRAMID_CACHE.popitem(last=False)
        return result


def _build_source_pyramid(
    source_path: str,
    band: int,
) -> tuple[np.ndarray, Any, str, float, float, float, float] | None:
    try:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.transform import Affine

        with rasterio.open(source_path) as src:
            h, w = src.height, src.width
            if max(h, w) <= _PYRAMID_TRIGGER_EDGE:
                return None
            scale = _PYRAMID_MAX_EDGE / max(h, w)
            oh = max(1, int(round(h * scale)))
            ow = max(1, int(round(w * scale)))
            data = src.read(
                min(int(band), src.count),
                out_shape=(oh, ow),
                resampling=Resampling.nearest,
                masked=True,
            )
            arr = np.ma.filled(np.ma.asarray(data).astype(np.float32), np.nan)
            # 多波段逐日事件源（ERA5 DWAA/WDAA）：255 是 nodata 哨兵。
            # 某些环境 rasterio 不暴露 nodata 元数据，必须显式转 NaN，
            # 否则金字塔低层级瓦片会把全图染成不透明数据。
            if src.count > 1:
                arr = np.where(arr == 255, np.nan, arr)
            transform = src.transform * Affine.scale(w / ow, h / oh)
            b = src.bounds
            return (
                arr,
                transform,
                str(src.crs or "EPSG:4326"),
                float(b.left),
                float(b.bottom),
                float(b.right),
                float(b.top),
            )
    except Exception:
        logger.warning("source pyramid build failed: %s", source_path, exc_info=True)
        return None


def overview_max_zoom() -> float:
    return _OVERVIEW_MAX_ZOOM


def tile_url_template(layer_id: str) -> str:
    return f"/overlay-tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png"


def tile_meta_fields(layer_id: str) -> dict[str, Any]:
    return {
        "tile_url_template": tile_url_template(layer_id),
        "minzoom": _MIN_ZOOM,
        "maxzoom": _MAX_ZOOM,
        "overview_max_zoom": _OVERVIEW_MAX_ZOOM,
        "tile_size": _TILE_SIZE,
    }


def tile_bbox_wgs84(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return (west, south, east, north) in EPSG:4326 for a Web Mercator tile."""
    n = 2**z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0

    def _y_to_lat(ty: int) -> float:
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ty / n)))
        return max(
            -_WEB_MERCATOR_MAX_LAT,
            min(_WEB_MERCATOR_MAX_LAT, lat_rad * 180.0 / math.pi),
        )

    north = _y_to_lat(y)
    south = _y_to_lat(y + 1)
    return west, south, east, north


def _apply_palette(
    data: np.ndarray,
    valid: np.ndarray,
    *,
    palette: str | None = "viridis",
    min_value: float | None = None,
    max_value: float | None = None,
    nodata_mode: str | None = "transparent",
    nodata_color: str | None = None,
) -> np.ndarray:
    """Map finite values to RGBA uint8 using shared colorize."""
    safe = np.where(valid, data, np.nan).astype(np.float32)
    vmin = min_value
    vmax = max_value
    if vmin is None or vmax is None:
        vals = np.asarray(data[valid], dtype=np.float64)
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            return np.zeros((_TILE_SIZE, _TILE_SIZE, 4), dtype=np.uint8)
        if vmin is None:
            vmin = float(np.nanpercentile(vals, 2))
        if vmax is None:
            vmax = float(np.nanpercentile(vals, 98))
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
            vmin = float(np.nanmin(vals))
            vmax = float(np.nanmax(vals))
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
            vmax = float(vmin) + 1.0
    rgba = colorize_array_to_rgba(
        safe,
        palette=resolve_palette_id(palette),
        min_value=vmin,
        max_value=vmax,
        nodata_mode=nodata_mode,
        nodata_color=nodata_color,
    )
    # Preserve historical ~200 alpha for transparent mode (slightly see-through tiles)
    if normalize_nodata_mode(nodata_mode) == "transparent":
        alpha = rgba[..., 3]
        rgba[..., 3] = np.where(alpha > 0, 200, 0).astype(np.uint8)
    return rgba


def render_geotiff_tile_png(
    source_path: str,
    z: int,
    x: int,
    y: int,
    *,
    band: int = 1,
    palette: str | None = "viridis",
    min_value: float | None = None,
    max_value: float | None = None,
    nodata_mode: str | None = "transparent",
    nodata_color: str | None = None,
    source_mtime_ns: int | None = None,
) -> bytes:
    """Warp a GeoTIFF window into a 256×256 Web Mercator PNG tile."""
    import rasterio
    from PIL import Image
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject, transform_bounds

    if z < _MIN_ZOOM or z > _MAX_ZOOM:
        raise ValueError(f"zoom out of range: {z}")
    n = 2**z
    if x < 0 or y < 0 or x >= n or y >= n:
        raise ValueError(f"tile x/y out of range for z={z}: {x}/{y}")

    west, south, east, north = tile_bbox_wgs84(z, x, y)
    dst = np.full((_TILE_SIZE, _TILE_SIZE), np.nan, dtype=np.float32)
    style_kw = dict(
        palette=palette,
        min_value=min_value,
        max_value=max_value,
        nodata_mode=nodata_mode,
        nodata_color=nodata_color,
    )

    # ── 巨型源低层级路径：从一次性降采样金字塔 warp（CLCD 报障修复）──
    # 仅当瓦片所需分辨率粗于金字塔分辨率（不放大）时使用；深缩放窗口小，
    # 直读源更快也更清晰。
    pyramid = None
    if source_mtime_ns is not None:
        pyramid = _source_pyramid(source_path, int(band), int(source_mtime_ns))
    if pyramid is not None:
        p_arr, p_transform, p_crs, p_left, p_bottom, p_right, p_top = pyramid
        try:
            pw, pb, pr, pt = transform_bounds(
                "EPSG:4326", p_crs, west, south, east, north, densify_pts=21
            )
        except Exception:
            pw, pb, pr, pt = west, south, east, north
        if pr < p_left or pw > p_right or pt < p_bottom or pb > p_top:
            img = Image.fromarray(
                _apply_palette(dst, np.zeros_like(dst, dtype=bool), **style_kw),
                mode="RGBA",
            )
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue()
        # 金字塔单像素跨度（源 CRS 单位）
        p_res_x = (p_right - p_left) / p_arr.shape[1]
        p_res_y = (p_top - p_bottom) / p_arr.shape[0]
        tile_span_x = pr - pw
        tile_span_y = pt - pb
        if tile_span_x > 0 and tile_span_y > 0:
            need_res_x = tile_span_x / _TILE_SIZE
            need_res_y = tile_span_y / _TILE_SIZE
            if need_res_x >= p_res_x and need_res_y >= p_res_y:
                try:
                    m_left, m_bottom, m_right, m_top = transform_bounds(
                        "EPSG:4326", "EPSG:3857", west, south, east, north,
                        densify_pts=21,
                    )
                except Exception:
                    m_left, m_bottom, m_right, m_top = west, south, east, north
                dst_transform = from_bounds(
                    m_left, m_bottom, m_right, m_top, _TILE_SIZE, _TILE_SIZE
                )
                reproject(
                    source=p_arr,
                    destination=dst,
                    src_transform=p_transform,
                    src_crs=p_crs,
                    dst_transform=dst_transform,
                    dst_crs="EPSG:3857",
                    resampling=Resampling.bilinear,
                    src_nodata=np.nan,
                    dst_nodata=np.nan,
                )
                # 金字塔路径在 _build_source_pyramid 已过滤多波段 nodata 哨兵；直接渲染。
                valid = np.isfinite(dst)
                rgba = _apply_palette(dst, valid, **style_kw)
                return encode_rgba_png(rgba)
        # 分辨率不够（深缩放）：落到下方直读源路径

    with rasterio.open(source_path) as src:
        src_crs = src.crs or "EPSG:4326"
        src_nodata = src.nodata
        try:
            left, bottom, right, top = transform_bounds(
                "EPSG:4326", src_crs, west, south, east, north, densify_pts=21
            )
        except Exception:
            left, bottom, right, top = west, south, east, north

        sb = src.bounds
        if right < sb.left or left > sb.right or top < sb.bottom or bottom > sb.top:
            img = Image.fromarray(
                _apply_palette(dst, np.zeros_like(dst, dtype=bool), **style_kw),
                mode="RGBA",
            )
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue()

        try:
            m_left, m_bottom, m_right, m_top = transform_bounds(
                "EPSG:4326", "EPSG:3857", west, south, east, north, densify_pts=21
            )
        except Exception:
            m_left, m_bottom, m_right, m_top = west, south, east, north

        dst_transform = from_bounds(
            m_left, m_bottom, m_right, m_top, _TILE_SIZE, _TILE_SIZE
        )
        reproject(
            source=rasterio.band(src, min(int(band), src.count)),
            destination=dst,
            src_transform=src.transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:3857",
            resampling=Resampling.bilinear,
            src_nodata=src_nodata,
            dst_nodata=np.nan,
        )
        if src_nodata is not None:
            dst = np.where(dst == src_nodata, np.nan, dst)
        # 多波段逐日事件源即使源 nodata 元数据缺失，仍把填充哨兵 255 识别为空值；
        # 否则 band 1 全 255 会被调色为不透明数据（ERA5 图空白/全盖）。
        if src.count > 1:
            dst = np.where(dst == 255, np.nan, dst)

    valid = np.isfinite(dst)
    rgba = _apply_palette(dst, valid, **style_kw)
    return encode_rgba_png(rgba)


@lru_cache(maxsize=128)
def _source_value_range(
    source_path: str,
    band: int,
    mtime_ns: int,
) -> tuple[float | None, float | None]:
    """Compute the source-wide 2/98 percentile value range (cached by mtime).

    2026-08-24 修复：_apply_palette 此前在 vmin/vmax=None 时按**单个瓦片自身**
    数据范围归一化——每个瓦片各自拉伸不同色阶，拼接处数值不连续、接缝可见
    （用户报障"瓦片之间拼接可见，细看是数据不连续"）。现改为缺省时回退到
    **全源统一范围**：读源全图一次（降采样以控内存），2/98 百分位，按
    (path, band, mtime) 缓存，所有瓦片共享同一归一化基准。
    """
    _ = mtime_ns
    try:
        import rasterio
        from rasterio.enums import Resampling

        with rasterio.open(source_path) as src:
            h = max(1, min(src.height, 1024))
            w = max(1, min(src.width, 1024))
            data = src.read(
                min(band, src.count),
                out_shape=(h, w),
                resampling=Resampling.bilinear,
                masked=True,
            )
        vals = np.asarray(data, dtype=np.float64)
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            return None, None
        vmin = float(np.nanpercentile(vals, 2))
        vmax = float(np.nanpercentile(vals, 98))
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
            vmin = float(np.nanmin(vals))
            vmax = float(np.nanmax(vals))
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
            return None, None
        return vmin, vmax
    except Exception:
        logger.warning("source value range failed: %s", source_path, exc_info=True)
        return None, None


@lru_cache(maxsize=512)
def _cached_tile(
    source_path: str,
    z: int,
    x: int,
    y: int,
    band: int,
    mtime_ns: int,
    palette: str,
    min_value: float | None,
    max_value: float | None,
    nodata_mode: str,
    nodata_color: str,
) -> bytes:
    if min_value is None or max_value is None:
        # 缺省范围回退全源统一范围（防逐瓦片归一化拼接不连续）
        gmin, gmax = _source_value_range(source_path, band, mtime_ns)
        if min_value is None:
            min_value = gmin
        if max_value is None:
            max_value = gmax
    return render_geotiff_tile_png(
        source_path,
        z,
        x,
        y,
        band=band,
        palette=palette,
        min_value=min_value,
        max_value=max_value,
        nodata_mode=nodata_mode,
        nodata_color=nodata_color or None,
        source_mtime_ns=mtime_ns,
    )


def render_overlay_tile(
    source_path: str,
    z: int,
    x: int,
    y: int,
    *,
    band: int = 1,
    palette: str | None = "viridis",
    min_value: float | None = None,
    max_value: float | None = None,
    nodata_mode: str | None = "transparent",
    nodata_color: str | None = None,
) -> bytes:
    from pathlib import Path

    path = Path(source_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    mtime_ns = path.stat().st_mtime_ns
    return _cached_tile(
        str(path.resolve()),
        int(z),
        int(x),
        int(y),
        int(band),
        int(mtime_ns),
        resolve_palette_id(palette),
        float(min_value) if min_value is not None else None,
        float(max_value) if max_value is not None else None,
        normalize_nodata_mode(nodata_mode),
        (nodata_color or "").strip(),
    )
