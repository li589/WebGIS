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
        # Downsample large grids for preview
        h, w = values.shape
        scale = min(_MAX_PREVIEW_EDGE / max(h, 1), _MAX_PREVIEW_EDGE / max(w, 1), 1.0)
        if scale < 1.0:
            oh = max(1, int(round(h * scale)))
            ow = max(1, int(round(w * scale)))
            # simple stride sample
            rs = max(1, h // oh)
            cs = max(1, w // ow)
            values = values[::rs, ::cs][:oh, :ow]
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
