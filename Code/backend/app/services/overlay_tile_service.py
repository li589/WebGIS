"""Render Web Mercator XYZ PNG tiles from imported overlay GeoTIFF sources."""

from __future__ import annotations

import io
import logging
import math
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
            source=rasterio.band(src, min(band, src.count)),
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

    valid = np.isfinite(dst)
    rgba = _apply_palette(dst, valid, **style_kw)
    return encode_rgba_png(rgba)


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
    _ = mtime_ns
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
