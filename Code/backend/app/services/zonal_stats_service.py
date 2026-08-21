"""
同步分区统计服务 — 对面要素区域内栅格图层进行均值/最值/像元数等统计。

注意：
  - 同步 API 仅在小区域时使用；大区域应走异步 workflow
  - 几何始终以 GeoJSON dict 传递（rasterio.warp.transform_geom 接受 GeoJSON-like）
  - 除 GeoTIFF 外，支持 overlay_registry 图层的 mat/netcdf 源数据
    （如 aridity-cn / clcd-cn / gpcp-precip-ts）：经 UniversalDataReader
    读数组后按 WGS84 网格构造 transform 执行 geometry_mask 统计
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import Affine, from_bounds
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
    """对单个栅格文件执行分区统计（按几何 bbox 窗口化读取，避免大栅格全图 mask）。"""
    from rasterio.windows import from_bounds

    with rasterio.open(raster_path) as src:
        geom_transformed = geojson_geom
        if src.crs is not None and src.crs.to_string().upper() != "EPSG:4326":
            try:
                geom_transformed = transform_geom("EPSG:4326", src.crs, geojson_geom)
            except Exception:
                geom_transformed = geojson_geom

        # 计算几何 bbox（数据坐标系）
        try:
            xs, ys = _geom_bounds(geom_transformed)
            win = from_bounds(xs[0], ys[0], xs[1], ys[1], transform=src.transform)
            # 整型化窗口：保证 read 实际读取范围与 window_transform 网格严格对齐
            win = win.round_offsets().round_lengths()
            # 相交裁剪：窗口不能超出栅格范围
            win = win.intersection(
                from_bounds(
                    src.bounds.left,
                    src.bounds.bottom,
                    src.bounds.right,
                    src.bounds.top,
                    transform=src.transform,
                ).round_offsets().round_lengths()
            )
            if win.width <= 0 or win.height <= 0:
                return dict(EMPTY_STATS)  # 几何与栅格无交集
            window_transform = src.window_transform(win)
            data = src.read(band, window=win, masked=True)
            # read 实际返回尺寸（浮点窗口取整后可能与 int(win.height) 不一致）
            out_shape = data.shape
        except Exception:
            window_transform = src.transform
            out_shape = (src.height, src.width)
            data = src.read(band, masked=True)

        try:
            mask = geometry_mask(
                [geom_transformed],
                out_shape=out_shape,
                transform=window_transform,
                invert=True,
            )
        except Exception:
            return dict(EMPTY_STATS)

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


def _geom_bounds(geom: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    """提取几何的 (minx, maxx), (miny, maxy)。"""
    xs: list[float] = []
    ys: list[float] = []

    def _walk(coords) -> None:
        for c in coords:
            if isinstance(c[0], (list, tuple)):
                _walk(c)
            else:
                xs.append(float(c[0]))
                ys.append(float(c[1]))

    _walk(geom.get("coordinates", []))
    if not xs:
        raise ValueError("geometry has no coordinates")
    return (min(xs), max(xs)), (min(ys), max(ys))


def _masked_stats(values: np.ndarray, mask: np.ndarray) -> dict:
    """对已构造 mask 的二维数组执行统计（与 _read_raster_stats 输出结构一致）。"""
    masked = np.ma.masked_array(values, mask=~mask)
    masked = np.ma.masked_invalid(masked)
    count = int(masked.count())
    if count == 0:
        return dict(EMPTY_STATS)
    return {
        "mean": float(masked.mean()),
        "max": float(masked.max()),
        "min": float(masked.min()),
        "sum": float(masked.sum()),
        "count": count,
        "std": float(masked.std()) if count > 1 else None,
    }


def _read_overlay_source_stats(spec, geojson_geom: dict) -> dict:
    """overlay_registry 图层源数据（mat/netcdf/GeoTIFF）的分区统计。

    经 UniversalDataReader 读数组 + WGS84 网格 transform 执行 geometry_mask：
    - GeoTIFF 源直接走 rasterio；
    - 自带一维 lat/lon 坐标（等间距）→ 坐标构造 transform（升序纬度自动翻转）；
    - 无坐标（如 0.25° mat）→ bounds JSON 线性网格（与 overlay 点查询
      ``_sample_from_bounds_json`` 同语义：origin upper-left / north-up）；
    - 二维投影坐标（EASE-Grid）→ 暂不支持，返回带说明的空统计。
    """
    src_path = spec.resolve_source_path(
        spec.default_time if spec.category == "time-series" else None
    )
    if src_path is None:
        return dict(EMPTY_STATS)

    if src_path.suffix.lower() in {".tif", ".tiff"}:
        return _read_raster_stats(src_path, geojson_geom)

    from data_access.universal_reader import UniversalDataReader

    reader = UniversalDataReader(src_path)
    data_array = reader.read_variable(variable=spec.source_variable or None)
    values = np.asarray(data_array.values)
    # 单时间维 (1, lat, lon) → squeeze（如 GPCP 月降水 nc4）
    if values.ndim == 3 and values.shape[0] == 1:
        values = values[0]
    if values.ndim != 2:
        return dict(EMPTY_STATS)

    n_lat, n_lon = values.shape
    lat_arr = getattr(data_array, "lat", None)
    lon_arr = getattr(data_array, "lon", None)

    transform: Affine | None = None

    # 路径 1：一维等间距坐标轴
    if (
        lat_arr is not None
        and lon_arr is not None
        and np.ndim(lat_arr) == 1
        and np.ndim(lon_arr) == 1
        and lat_arr.size == n_lat
        and lon_arr.size == n_lon
    ):
        lat_1d = np.asarray(lat_arr, dtype=float)
        lon_1d = np.asarray(lon_arr, dtype=float)
        dlat = float(np.median(np.diff(lat_1d))) if n_lat > 1 else 0.0
        dlon = float(np.median(np.diff(lon_1d))) if n_lon > 1 else 0.0
        if (
            abs(dlat) > 1e-9
            and abs(dlon) > 1e-9
            and np.allclose(np.diff(lat_1d), dlat, rtol=1e-3, atol=1e-6)
            and np.allclose(np.diff(lon_1d), dlon, rtol=1e-3, atol=1e-6)
        ):
            if dlat > 0:
                # 升序纬度（south-up，CF 惯例）→ 翻转为 north-up
                values = values[::-1, :]
                lat_1d = lat_1d[::-1]
                dlat = -dlat
            west = float(lon_1d[0]) - abs(dlon) / 2.0
            north = float(lat_1d[0]) + abs(dlat) / 2.0
            transform = Affine(abs(dlon), 0.0, west, 0.0, -abs(dlat), north)

    # 路径 2：bounds JSON 线性网格（origin upper-left / north-up）
    if transform is None:
        try:
            bounds_path = spec.resolve_bounds(
                spec.default_time if spec.category == "time-series" else None
            )
            if bounds_path is not None and bounds_path.exists():
                bdata = json.loads(bounds_path.read_text(encoding="utf-8"))
                bounds = bdata.get("bounds")
                if bounds and len(bounds) == 4:
                    west, south, east, north = (float(x) for x in bounds)
                    transform = from_bounds(west, south, east, north, n_lon, n_lat)
        except (OSError, json.JSONDecodeError, ValueError):
            transform = None

    if transform is None:
        logger.info(
            "zonal stats unsupported grid for overlay layer=%s "
            "(2D projected coords or missing bounds)",
            spec.layer_id,
        )
        return dict(EMPTY_STATS)

    try:
        mask = geometry_mask(
            [geojson_geom],
            out_shape=(n_lat, n_lon),
            transform=transform,
            invert=True,
        )
    except Exception:
        return dict(EMPTY_STATS)

    return _masked_stats(values, mask)


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

        if raster_path is not None:
            try:
                stats = _read_raster_stats(raster_path, geom)
            except Exception as e:
                logger.warning(
                    "zonal stats raster read failed: layer=%s path=%s err=%s",
                    layer_id,
                    raster_path,
                    e,
                )
                stats = dict(EMPTY_STATS)
                stats["error"] = str(e)
            results.append(
                {
                    "layer_id": layer_id,
                    "layer_name": layer_name,
                    "unit": unit,
                    **stats,
                }
            )
            continue

        # 分支 2：overlay_registry 图层（mat/netcdf 源，如 aridity-cn / gpcp-precip-ts）
        overlay_stats, overlay_unit = _try_overlay_source_stats(layer_id, geom)
        if overlay_unit and not unit:
            unit = overlay_unit
        if overlay_stats is not None:
            results.append(
                {
                    "layer_id": layer_id,
                    "layer_name": layer_name,
                    "unit": unit,
                    **overlay_stats,
                }
            )
            continue

        results.append(
            {
                "layer_id": layer_id,
                "layer_name": layer_name,
                "unit": unit,
                **EMPTY_STATS,
            }
        )

    return results


def _try_overlay_source_stats(layer_id: str, geom: dict) -> tuple[Optional[dict], Optional[str]]:
    """尝试用 overlay_registry 的源数据做分区统计；图层不存在时返回 (None, None)。"""
    try:
        from app.services.overlay_registry import get_overlay_spec
    except Exception:
        return None, None

    spec = get_overlay_spec(layer_id)
    if spec is None:
        return None, None

    try:
        stats = _read_overlay_source_stats(spec, geom)
    except Exception as e:
        logger.warning(
            "zonal stats overlay source read failed: layer=%s err=%s",
            layer_id,
            e,
        )
        stats = dict(EMPTY_STATS)
        stats["error"] = str(e)
    return stats, spec.unit


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
