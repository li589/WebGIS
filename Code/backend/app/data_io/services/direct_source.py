"""COG/GeoTIFF direct 源接入（数据源管理子系统，图层平台 P2-4 归位版）。

职责边界（2026-08-25 架构归位）：
- **数据源管理子系统（本模块）**：COG/瓦片服务的数据接入——
  direct 源目录形态判定（单一真源）、源文件入库（imports 目录）、
  bounds/元数据生成、注册 overlay spec。
- **图层平台子系统（app.services.overlay_registry / overlay_tile_service
  + 前端 overlay-image-module）**：图层的显示、渲染、加载与瓦片服务。
  registry 的 lazy-load 委托本模块的形态判定，不自带接入知识。

direct 源图层 = 大数据 COG/GeoTIFF 免烘焙直通动态瓦片：
IMPORTS_DIR/<layer_id>/ 下仅需 ``source.tif``（或 .cog/.tiff）+
``bounds.json``，无 preview.png（has_overview=False，前端全程 XYZ 瓦片）。
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.data_io.services._meta_io import save_json_atomic
from app.data_io.services.paths import (
    assert_quota_available,
    dir_size_bytes,
    ensure_imports_root,
    safe_import_child,
)

logger = logging.getLogger(__name__)

#: direct 源支持的 GeoTIFF/COG 后缀（与 overlay_tile_service 的瓦片源白名单一致）
DIRECT_SOURCE_SUFFIXES = frozenset({".tif", ".tiff", ".geotiff", ".cog"})


def find_direct_source(
    dest_dir: Path, meta: dict[str, Any] | None = None
) -> Path | None:
    """判定 overlay 目录是否为 direct 源形态；返回源文件路径（非 direct 返回 None）。

    判定规则（单一真源，registry lazy-load 委托本函数）：
    1. meta.source_filename 显式指定的源文件存在且后缀合法；
    2. 否则目录下任意 ``source*.tif`` / ``source*.tiff`` / ``source*.cog``。

    注意：本函数只回答「源在哪」，不管 preview.png 是否存在——
    preview 缺失 + 源存在 = direct 源图层（全动态瓦片渲染）。
    """
    if meta:
        source_filename = meta.get("source_filename")
        if source_filename:
            candidate = dest_dir / str(source_filename)
            if (
                candidate.is_file()
                and candidate.suffix.lower() in DIRECT_SOURCE_SUFFIXES
            ):
                return candidate
    candidates: list[Path] = []
    for pattern in ("source*.tif", "source*.tiff", "source*.cog"):
        candidates.extend(dest_dir.glob(pattern))
    valid = [c for c in candidates if c.suffix.lower() in DIRECT_SOURCE_SUFFIXES]
    return sorted(valid)[0] if valid else None


def register_direct_geotiff(
    src_path: Path,
    *,
    layer_id: str | None = None,
    palette: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    unit: str = "",
    opacity: float = 0.7,
    bounds: list[float] | None = None,
    replace_existing: bool = False,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把外部 COG/GeoTIFF 注册为 direct 源图层（免烘焙，直通动态瓦片）。

    与 ``raster_register.register_geotiff_as_imported`` 的区别：
    后者走完整烘焙管道（生成 preview.png + CRS 确认流）；本函数面向
    大数据 COG——只入库源文件 + 生成 bounds.json，显示层全程由
    ``/overlay-tiles`` 动态渲染（无 overview PNG）。

    Args:
        src_path: 源 GeoTIFF/COG 文件路径（任意位置，将被拷贝入库）。
        layer_id: 图层 id（缺省 imported-<uuid>）。
        bounds: 可选显式 WGS84 bounds [west, south, east, north]；
            缺省从源文件 rasterio 读取（源 CRS 需为地理坐标系或
            已知投影——投影坐标系会经 transform_bounds 转 WGS84）。
    Returns:
        与 register_geotiff_as_imported 同构的结果 dict（layer_id/bounds/dir 等）。
    """
    from app.services.overlay_registry import (
        OverlaySpec,
        register_overlay,
        unregister_overlay,
    )

    ensure_imports_root()
    if not src_path.is_file() or src_path.suffix.lower() not in DIRECT_SOURCE_SUFFIXES:
        raise ValueError(f"非法 direct 源文件（需 GeoTIFF/COG）: {src_path}")

    layer_id = layer_id or f"imported-{uuid.uuid4().hex[:12]}"
    dest_dir = safe_import_child(layer_id)  # 防路径穿越（安审 2026-08-21 S-2）
    replace_bytes = 0
    if dest_dir.exists():
        if not replace_existing:
            raise ValueError(
                f"图层已存在: {layer_id}（可设 replace_existing=True 覆盖）"
            )
        replace_bytes = dir_size_bytes(dest_dir)
        with contextlib.suppress(Exception):
            unregister_overlay(layer_id)
        shutil.rmtree(dest_dir, ignore_errors=True)

    src_size = src_path.stat().st_size
    assert_quota_available(src_size, replace_bytes=replace_bytes)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored = dest_dir / f"source{src_path.suffix.lower()}"
    shutil.copy2(src_path, stored)

    # bounds：显式优先，否则 rasterio 读取 + 投影转换
    try:
        import rasterio
        from rasterio.warp import transform_bounds as _transform_bounds

        with rasterio.open(stored) as dataset:
            west, south, east, north = dataset.bounds
            source_crs = str(dataset.crs or "EPSG:4326")
            width, height, count = dataset.width, dataset.height, dataset.count
        if bounds is None:
            if source_crs.upper() not in {"EPSG:4326", "CRS84", ""}:
                west, south, east, north = _transform_bounds(
                    source_crs, "EPSG:4326", west, south, east, north, densify_pts=21
                )
            wgs84_bounds = [float(west), float(south), float(east), float(north)]
        else:
            wgs84_bounds = [float(v) for v in bounds]
    except Exception as exc:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise ValueError(f"无法读取栅格 bounds: {exc}") from exc

    if not (wgs84_bounds[0] < wgs84_bounds[2] and wgs84_bounds[1] < wgs84_bounds[3]):
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise ValueError(f"bounds 非法（需 west<east 且 south<north）: {wgs84_bounds}")

    meta = {
        "layer_id": layer_id,
        "category": "static",
        "palette": palette,
        "vmin": vmin,
        "vmax": vmax,
        "unit": unit,
        "opacity": opacity,
        "crs": "EPSG:4326",
        "source_filename": stored.name,
        "source_crs": source_crs,
        "source_width": width,
        "source_height": height,
        "source_bands": count,
        "source_reader": "geotiff",
        # P2-4 direct 源标志：前端据此全程走动态 XYZ 瓦片
        "has_overview": False,
        **(extra_meta or {}),
    }
    save_json_atomic(dest_dir / "bounds.json", {"bounds": wgs84_bounds, "meta": meta})

    register_overlay(
        OverlaySpec(
            layer_id=layer_id,
            overlay_dir=dest_dir,
            png_filename=None,  # direct 源：无烘焙 overview
            bounds_filename="bounds.json",
            category="static",
            palette=palette,
            opacity=opacity,
            crs="EPSG:4326",
            source_path=stored,
            source_reader="geotiff",
        )
    )
    logger.info(
        "direct source registered: %s (%s, bounds=%s)",
        layer_id,
        stored.name,
        wgs84_bounds,
    )
    return {
        "layer_id": layer_id,
        "bounds": wgs84_bounds,
        "dir": str(dest_dir),
        "source_filename": stored.name,
        "preview_generated": False,
        "has_overview": False,
    }
