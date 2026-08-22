"""将本地 GeoTIFF 注册为 imported overlay（供 TIF/nc/hdf/mat 共用）。"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from rasterio.warp import transform_bounds as _transform_bounds

from app.data_io.services._meta_io import save_bytes_atomic, save_json_atomic
from app.services.crs import crs_detector
from app.data_io.services.paths import (
    assert_quota_available,
    dir_size_bytes,
    ensure_imports_root,
    safe_import_child,
)
from app.services.geo_math import overlay_safe_wgs84_bounds
from app.services.overlay_registry import (
    OverlaySpec,
    register_overlay,
    unregister_overlay,
)
from app.services.raster_preview_service import raster_preview_service
import contextlib


def _bounds_look_like_wgs84(
    west: float, south: float, east: float, north: float
) -> bool:
    """判断 bounds 是否像可直接上 MapLibre 的 WGS84 经纬度。"""
    try:
        w, s, e, n = overlay_safe_wgs84_bounds(west, south, east, north)
    except ValueError:
        return False
    return w < e and s < n and e - w <= 360.0 and abs(w) <= 180.0 and e <= 360.0


def register_geotiff_as_imported(
    src_path: Path,
    *,
    source_filename: str | None = None,
    layer_id: str | None = None,
    extra_meta: dict[str, Any] | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    ensure_imports_root()
    src_size = src_path.stat().st_size if src_path.exists() else 0

    layer_id = layer_id or f"imported-{uuid.uuid4().hex[:12]}"
    # 安审 2026-08-21 S-2：layer_id 可能透传自调用方，统一走防穿越收敛点
    dest_dir = safe_import_child(layer_id)
    replace_bytes = 0
    replaced = False
    if dest_dir.exists():
        if not replace_existing:
            raise ValueError(
                f"图层已存在: {layer_id}（可改用覆盖策略 conflict_policy=overwrite）"
            )
        replace_bytes = dir_size_bytes(dest_dir)
        with contextlib.suppress(Exception):
            unregister_overlay(layer_id)
        shutil.rmtree(dest_dir, ignore_errors=True)
        replaced = True

    assert_quota_available(src_size, replace_bytes=replace_bytes)
    dest_dir.mkdir(parents=True, exist_ok=True)

    filename = source_filename or src_path.name
    stored = dest_dir / Path(filename).name
    if src_path.resolve() != stored.resolve():
        shutil.copy2(src_path, stored)

    try:
        import rasterio
    except ImportError as exc:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise RuntimeError(f"rasterio 不可用: {exc}") from exc

    try:
        with rasterio.open(stored) as dataset:
            west, south, east, north = dataset.bounds
            width = dataset.width
            height = dataset.height
            count = dataset.count
    except Exception as exc:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise ValueError(f"无法读取栅格文件: {exc}") from exc

    detection = crs_detector.detect_from_raster(stored)
    source_crs = detection.source_crs
    suggested_crs = detection.suggested_crs
    needs_confirm = detection.needs_user_confirm
    detection_notes = detection.notes

    # 地理 CRS：检测 bounds 是否 XY 颠倒
    needs_xy_swap = False
    xy_swapped, xy_note = crs_detector.detect_xy_swap(
        (float(west), float(south), float(east), float(north)),
        source_crs=source_crs,
    )
    if xy_swapped:
        needs_xy_swap = True
        needs_confirm = True
        detection_notes = f"{detection_notes}；{xy_note}".strip("；")
    elif xy_note and "正常" not in xy_note:
        detection_notes = f"{detection_notes}；{xy_note}".strip("；")

    # 防御：即便检测器认为无需确认，若原始 bounds 不像 WGS84（投影米制 /
    # 无 CRS / 元数据与数据不符），也强制进入确认流，避免 overlay 挂到地图外。
    if not _bounds_look_like_wgs84(
        float(west), float(south), float(east), float(north)
    ):
        needs_confirm = True
        detection_notes = (
            f"{detection_notes}；bounds "
            f"({west:.2f},{south:.2f},{east:.2f},{north:.2f}) "
            "不像 WGS84 经纬度，需确认源坐标系后再显示"
        ).strip("；")

    png_path = dest_dir / "preview.png"
    try:
        png_bytes = raster_preview_service.render_cog_preview(
            cog_path=stored,
            palette="wind-blue",
            width=min(2048, width),
            height=min(2048, height),
        )
        save_bytes_atomic(png_path, png_bytes)
    except Exception as exc:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise RuntimeError(f"预览生成失败: {exc}") from exc

    bounds = [float(west), float(south), float(east), float(north)]
    extra = dict(extra_meta or {})
    time_list = extra.get("time_list")
    if not isinstance(time_list, list):
        time_list = []
    time_list = [str(t) for t in time_list]
    default_time = extra.get("default_time")
    if default_time is not None:
        default_time = str(default_time)
    elif time_list:
        default_time = time_list[-1]
    native_step = extra.get("native_step")
    native_step = str(native_step) if native_step else None
    follow_policy = extra.get("follow_policy")
    follow_policy = str(follow_policy) if follow_policy else None

    meta = {
        "layer_id": layer_id,
        "category": "static",
        "palette": "wind-blue",
        "vmin": None,
        "vmax": None,
        "unit": "",
        "opacity": 0.7,
        "crs": source_crs,
        "time_list": time_list,
        "default_time": default_time,
        "current_time": default_time,
        "native_step": native_step,
        "follow_policy": follow_policy,
        "source_filename": filename,
        "source_crs": source_crs,
        "source_crs_confidence": detection.confidence,
        "source_crs_method": detection.method,
        "source_crs_notes": detection_notes,
        "source_width": width,
        "source_height": height,
        "source_bands": count,
        **extra,
    }
    # 强制单文件布局为 static；时间语义靠 time_list 表达
    meta["category"] = "static"
    meta["time_list"] = time_list
    meta["default_time"] = default_time
    meta["current_time"] = default_time
    bounds_data = {"bounds": bounds, "meta": meta}
    save_json_atomic(dest_dir / "bounds.json", bounds_data)
    meta_payload = {
        "layer_id": layer_id,
        "kind": "raster",
        "source_filename": filename,
        "time_list": time_list,
        "default_time": default_time,
        "native_step": native_step,
        "follow_policy": follow_policy,
        "temporal_kind": meta.get("temporal_kind"),
        "temporal_source": meta.get("temporal_source"),
        **{
            k: v
            for k, v in extra.items()
            if k
            not in {
                "time_list",
                "default_time",
                "native_step",
                "follow_policy",
                "temporal_kind",
                "temporal_source",
                "category",
                "current_time",
            }
        },
    }
    save_json_atomic(dest_dir / "meta.json", meta_payload)

    register_overlay(
        OverlaySpec(
            layer_id=layer_id,
            overlay_dir=dest_dir,
            png_filename="preview.png",
            bounds_filename="bounds.json",
            category="static",
            time_list=time_list,
            default_time=default_time,
            palette="wind-blue",
            opacity=0.7,
            crs=source_crs,
            source_path=stored,
            source_reader="geotiff",
        )
    )

    return {
        "layer_id": layer_id,
        "bounds": bounds,
        "source_crs": source_crs,
        "suggested_crs": suggested_crs,
        "needs_confirm": needs_confirm,
        "needs_xy_swap": needs_xy_swap,
        "detection_notes": detection_notes,
        "replaced": replaced,
        "time_list": time_list,
        "default_time": default_time,
        "native_step": native_step,
        "follow_policy": follow_policy,
        "temporal_kind": meta.get("temporal_kind"),
        "temporal_source": meta.get("temporal_source"),
    }


def confirm_imported_raster_crs(
    layer_id: str,
    *,
    source_crs: str,
    lng_offset: float = 0.0,
    lat_offset: float = 0.0,
) -> dict[str, Any]:
    """将已注册 imported 栅格按源 CRS 重投影预览到 WGS84 并更新 bounds。"""
    if not layer_id.startswith("imported-"):
        raise ValueError("仅允许确认 imported-* 图层")

    # 安审 2026-08-21 S-2：layer_id 来自 body，须防路径穿越（写 preview/bounds）
    dest_dir = safe_import_child(layer_id)
    bounds_path = dest_dir / "bounds.json"
    if not bounds_path.exists():
        raise FileNotFoundError(f"导入图层不存在: {layer_id}")

    try:
        bounds_data = json.loads(bounds_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"读取 bounds.json 失败: {exc}") from exc

    meta = bounds_data.get("meta", {})
    source_filename = meta.get("source_filename")
    if not source_filename:
        raise RuntimeError("bounds.json 缺少 source_filename 元数据")

    # 安审 2026-08-21 S-3：source_filename 来自 meta（可被构造），归一为纯文件名
    src_path = dest_dir / Path(str(source_filename)).name
    if not src_path.exists():
        raise FileNotFoundError(f"源 TIF 文件不存在: {source_filename}")

    # MapLibre ImageSource：PNG 须为 Web Mercator 内容，bounds 仍报 WGS84 四角。
    # 全网格科学数据（EASE2 等）禁止 crop_to_data，否则稀疏全球场被裁成局部框导致比例失真。
    grid_preset = str(meta.get("grid_preset") or "")
    ease2_like = source_crs.strip().upper() in {
        "EPSG:6933",
        "6933",
    } or grid_preset.startswith("ease2")
    png_bytes, mercator_bounds = raster_preview_service.render_cog_preview_reprojected(
        cog_path=src_path,
        palette="wind-blue",
        width=2048,
        height=2048,
        source_crs=source_crs,
        target_crs="EPSG:3857",
        crop_to_data=not ease2_like,
    )
    west, south, east, north = _transform_bounds(
        "EPSG:3857",
        "EPSG:4326",
        float(mercator_bounds[0]),
        float(mercator_bounds[1]),
        float(mercator_bounds[2]),
        float(mercator_bounds[3]),
        densify_pts=21,
    )
    west += lng_offset
    east += lng_offset
    south += lat_offset
    north += lat_offset
    try:
        west, south, east, north = overlay_safe_wgs84_bounds(
            float(west), float(south), float(east), float(north)
        )
    except ValueError as exc:
        raise RuntimeError(
            f"确认后 bounds 无效: {[west, south, east, north]}（请检查源 CRS / 偏移）: {exc}"
        ) from exc
    new_bounds: list[float] = [float(west), float(south), float(east), float(north)]

    png_path = dest_dir / "preview.png"
    save_bytes_atomic(png_path, png_bytes)

    bounds_data["bounds"] = new_bounds
    meta["crs"] = "EPSG:4326"
    meta["confirmed_source_crs"] = source_crs
    meta["applied_lng_offset"] = lng_offset
    meta["applied_lat_offset"] = lat_offset
    bounds_data["meta"] = meta
    save_json_atomic(bounds_path, bounds_data)

    # 局部导入，避免进程热重载/旧模块缓存导致 NameError
    from app.services.overlay_registry import (
        OverlaySpec as _OverlaySpec,
        register_overlay as _register_overlay,
        unregister_overlay as _unregister_overlay,
    )

    time_list = meta.get("time_list") if isinstance(meta.get("time_list"), list) else []
    time_list = [str(t) for t in time_list]
    default_time = meta.get("default_time")
    default_time = (
        str(default_time) if default_time else (time_list[-1] if time_list else None)
    )

    _unregister_overlay(layer_id)
    _register_overlay(
        _OverlaySpec(
            layer_id=layer_id,
            overlay_dir=dest_dir,
            png_filename="preview.png",
            bounds_filename="bounds.json",
            category="static",
            time_list=time_list,
            default_time=default_time,
            palette="wind-blue",
            opacity=0.7,
            crs="EPSG:4326",
            source_path=src_path,
            source_reader="geotiff",
        )
    )

    return {
        "layer_id": layer_id,
        "bounds": new_bounds,
        "source_crs": source_crs,
        "suggested_crs": "EPSG:4326",
        "needs_confirm": False,
        "target_crs": "EPSG:4326",
        "applied_offset": [lng_offset, lat_offset],
        "detection_notes": f"已按 {source_crs} 重投影到 WGS84",
        "time_list": time_list,
        "default_time": default_time,
        "native_step": meta.get("native_step"),
        "follow_policy": meta.get("follow_policy"),
        "temporal_kind": meta.get("temporal_kind"),
        "temporal_source": meta.get("temporal_source"),
    }
