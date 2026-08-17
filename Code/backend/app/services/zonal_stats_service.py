"""
同步分区统计服务 — 对面要素区域内栅格图层进行均值/最值/像元数等统计。

注意：
  - 同步 API 仅在小区域时使用；大区域应走异步 workflow
  - 几何始终以 GeoJSON dict 传递（rasterio.warp.transform_geom 接受 GeoJSON-like）
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom

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

    return None
