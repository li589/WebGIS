"""
同步分区统计服务 — 对面要素区域内栅格图层进行均值/最值/像元数等统计。

注意：
  - 同步 API 仅在小区域时使用；大区域应走异步 workflow
  - 几何始终以 GeoJSON dict 传递（rasterio.warp.transform_geom 接受 GeoJSON-like）
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom

logger = logging.getLogger(__name__)

EMPTY_STATS = {
    "mean": None,
    "max": None,
    "min": None,
    "sum": None,
    "count": 0,
    "std": None,
}


def _read_raster_stats(raster_path: Path, geojson_geom: dict, band: int = 1) -> dict:
    """对单个栅格文件执行分区统计"""
    with rasterio.open(raster_path) as src:
        geom_transformed = geojson_geom
        if src.crs is not None and src.crs.to_string().upper() != "EPSG:4326":
            try:
                geom_transformed = transform_geom("EPSG:4326", src.crs, geojson_geom)
            except Exception:
                geom_transformed = geojson_geom

        try:
            mask = geometry_mask(
                [geom_transformed],
                out_shape=(src.height, src.width),
                transform=src.transform,
                invert=True,
            )
        except Exception:
            return dict(EMPTY_STATS)

        data = src.read(band, masked=True)
        masked_data = np.ma.masked_array(data, mask=~mask)

        count = int(masked_data.count())
        if count == 0:
            return dict(EMPTY_STATS)

        return {
            "mean": float(masked_data.mean()),
            "max": float(masked_data.max()),
            "min": float(masked_data.min()),
            "sum": float(masked_data.sum()),
            "count": count,
            "std": float(masked_data.std()) if count > 1 else None,
        }


def compute_zonal_stats(
    geojson: dict,
    overlay_layer_ids: list[str],
    data_root: Path,
    layer_descriptors: dict,
) -> list[dict]:
    """
    对面要素区域内的栅格图层进行分区统计。

    Args:
        geojson: 面要素 GeoJSON（Feature 或 Geometry）
        overlay_layer_ids: 要统计的栅格图层 ID 列表
        data_root: 数据根目录
        layer_descriptors: 图层描述符字典（layerId → descriptor）

    Returns:
        list[dict]: 每个图层的统计结果
    """
    geom = geojson_geom_dict(geojson)

    results = []
    for layer_id in overlay_layer_ids:
        desc = layer_descriptors.get(layer_id, {})
        layer_name = desc.get("name", desc.get("display_name", layer_id))
        unit = desc.get("unit", desc.get("units"))

        raster_path = _find_raster_path(layer_id, data_root, desc)

        if raster_path is None:
            results.append(
                {
                    "layer_id": layer_id,
                    "layer_name": layer_name,
                    "unit": unit,
                    **EMPTY_STATS,
                }
            )
            continue

        try:
            stats = _read_raster_stats(raster_path, geom)
            results.append(
                {
                    "layer_id": layer_id,
                    "layer_name": layer_name,
                    "unit": unit,
                    **stats,
                }
            )
        except Exception as e:
            logger.warning(
                "zonal stats raster read failed: layer=%s path=%s err=%s",
                layer_id,
                raster_path,
                e,
            )
            results.append(
                {
                    "layer_id": layer_id,
                    "layer_name": layer_name,
                    "unit": unit,
                    "error": str(e),
                    **EMPTY_STATS,
                }
            )

    return results


def geojson_geom_dict(geojson: dict) -> dict:
    """从 Feature 或裸 Geometry 中提取 geometry dict"""
    if geojson.get("type") == "Feature":
        return geojson.get("geometry", {})
    return geojson


def _find_raster_path(layer_id: str, data_root: Path, desc: dict) -> Optional[Path]:
    """根据图层描述符查找栅格文件路径"""
    resolved = _resolve_raster_path(layer_id, data_root, desc)
    logger.info(
        "zonal stats path resolve: layer=%s data_root=%s -> %s",
        layer_id,
        data_root,
        resolved,
    )
    return resolved


def _resolve_raster_path(layer_id: str, data_root: Path, desc: dict) -> Optional[Path]:
    paths = desc.get("paths", [])
    if isinstance(paths, list):
        for p in paths:
            full = data_root / p if not Path(p).is_absolute() else Path(p)
            if full.exists():
                return full

    for candidate in (
        data_root / "overlay" / f"{layer_id}.tif",
        data_root / "catalog" / layer_id / "data.tif",
    ):
        if candidate.exists():
            return candidate

    return _find_imported_raster_path(layer_id)


def _find_imported_raster_path(layer_id: str) -> Optional[Path]:
    """导入栅格（imported-*）位于 OUTPUT_ROOT/imports/<layer_id>/，不在 data_root 下。

    优先读 bounds.json 的 meta.source_filename，回退到目录内任意 tif。
    """
    if not layer_id.startswith("imported-"):
        return None
    try:
        from app.data_io.services.paths import IMPORTS_DIR
    except Exception:
        return None

    dest_dir = IMPORTS_DIR / layer_id
    if not dest_dir.is_dir():
        return None

    bounds_path = dest_dir / "bounds.json"
    if bounds_path.is_file():
        try:
            meta = json.loads(bounds_path.read_text(encoding="utf-8")).get("meta") or {}
            name = meta.get("source_filename")
            if name:
                candidate = dest_dir / Path(str(name)).name
                if candidate.is_file():
                    return candidate
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    tifs = sorted(dest_dir.glob("*.tif")) + sorted(dest_dir.glob("*.tiff"))
    return tifs[0] if tifs else None
