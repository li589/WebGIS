"""栅格数据导入路由。

接收用户上传的 TIF 文件，生成预览 PNG + bounds JSON，
动态注册到 overlay_registry，使前端可通过 /overlay-preview/{layer_id} 访问。

CRS 支持端点（Phase 1）：
- ``GET  /import/crs-options``       — 列出已注册 CRS（前端下拉用）
- ``POST /import/raster``            — 上传 TIF（返回检测到的 CRS + needs_confirm 标志）
- ``POST /import/raster/confirm``    — 用户确认源 CRS 后重投影到 WGS84 + 重写 bounds
- ``POST /import/transform-point``   — 批量点转换（CSV/POI 提交时用）
- ``POST /import/transform-bounds``  — bounds 转换（前端预览用）
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, model_validator

from app.api.deps import require_data_transfer_access
from app.services.crs import crs_detector, crs_transformer
from app.services.crs.crs_registry import to_api_payload, to_api_payload_expanded
from app.data_io.services.paths import (
    MAX_UPLOAD_BYTES as _MAX_UPLOAD_BYTES,
)
from app.data_io.services.paths import IMPORTS_DIR as _IMPORTS_DIR
from app.data_io.services.paths import safe_import_child as _safe_import_child
from app.data_io.services.paths import assert_quota_available as _assert_quota_available
from app.data_io.services.paths import QuotaExceededError as _QuotaExceededError
from app.services.overlay_registry import (
    OverlaySpec,
    register_overlay,
    unregister_overlay,
)
from app.data_io.services.raster_register import confirm_imported_raster_crs
from app.services.raster_preview_service import raster_preview_service

router = APIRouter(prefix="/import", tags=["import"])
logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = frozenset({"tif", "tiff"})
_PREVIEW_MAX_DIMENSION = 1024


# ── Pydantic 请求模型 ───────────────────────────────────────────────────


class ConfirmRequest(BaseModel):
    """``POST /import/raster/confirm`` 请求体。

    用户在前端确认对话框中选定源 CRS（可覆盖检测结果）并设置偏移后提交。
    """

    layer_id: str
    source_crs: str
    """源栅格 CRS code（如 'EPSG:32650'）。用户可覆盖自动检测值。"""

    lng_offset: float = 0.0
    """经度方向偏移（度），在 CRS 转换**后**应用到 bounds。"""

    lat_offset: float = 0.0
    """纬度方向偏移（度），同上。"""


class TransformPointRequest(BaseModel):
    """``POST /import/transform-point`` 请求体。"""

    points: list[tuple[float, float]] = Field(max_length=10000)
    """待转换的 (lng, lat) 点列表（源 CRS 下），上限 10000 点防滥用。"""

    source_crs: str = Field(min_length=1, max_length=64)
    target_crs: str = Field(default="EPSG:4326", min_length=1, max_length=64)
    lng_offset: float = 0.0
    lat_offset: float = 0.0

    @model_validator(mode="after")
    def _validate_non_empty(self) -> TransformPointRequest:
        if not self.points:
            raise ValueError("points must not be empty")
        return self


class TransformBoundsRequest(BaseModel):
    """``POST /import/transform-bounds`` 请求体。"""

    bounds: list[float] = Field(min_length=4, max_length=4)
    """[west, south, east, north]，源 CRS 下，必须恰好 4 个元素。"""

    source_crs: str = Field(min_length=1, max_length=64)
    target_crs: str = Field(default="EPSG:4326", min_length=1, max_length=64)


# ── CRS 选项端点 ───────────────────────────────────────────────────────


@router.get("/crs-options", dependencies=[Depends(require_data_transfer_access)])
async def list_crs_options() -> dict[str, Any]:
    """返回前端下拉用 CRS 列表（按 category 分组前的平铺列表）。

    委托 ``crs_registry.to_api_payload()``，返回 13 项 Phase 1 扩展版 CRS。
    """
    return {
        "items": to_api_payload(),
        "count": len(to_api_payload()),
    }


@router.get(
    "/crs-options/expanded", dependencies=[Depends(require_data_transfer_access)]
)
async def list_crs_options_expanded() -> dict[str, Any]:
    """返回完整 CRS 列表（含动态 UTM/GK 带，供高级选择）。

    featured 项为精简集，非 featured 项为动态生成的投影带。
    """
    items = to_api_payload_expanded()
    return {
        "items": items,
        "count": len(items),
        "featured_count": sum(1 for i in items if i.get("featured")),
    }


# ── 上传端点 ───────────────────────────────────────────────────────────


@router.post("/raster", dependencies=[Depends(require_data_transfer_access)])
async def import_raster(file: UploadFile = File(...)) -> dict[str, Any]:
    """上传栅格文件（TIF），生成预览 PNG + bounds，动态注册为 overlay 图层。

    返回 ``{layer_id, bounds, source_crs, suggested_crs, needs_confirm}``。
    bounds 保持源 CRS 不转换；前端若收到 ``needs_confirm=True`` 应弹确认框，
    用户确认后调 ``POST /import/raster/confirm`` 重投影到 WGS84。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名缺失")

    filename = Path(file.filename).name
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, detail=f"仅支持 TIF/TIFF 文件，收到 .{ext}"
        )

    try:
        _assert_quota_available(0)
    except _QuotaExceededError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc

    # 生成唯一 ID 和存储目录
    layer_id = f"imported-{uuid.uuid4().hex[:12]}"
    dest_dir = _IMPORTS_DIR / layer_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 保存上传文件（带大小上限）
    src_path = dest_dir / filename
    try:
        written = 0
        with src_path.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > _MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过上限 {_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB",
                    )
                f.write(chunk)
    except HTTPException:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise
    finally:
        await file.close()

    def _cleanup_on_failure() -> None:
        """处理失败时清理已创建的目录和文件，避免磁盘空间泄漏。"""
        shutil.rmtree(dest_dir, ignore_errors=True)

    # 用 rasterio 读取 bounds 和元数据
    try:
        import rasterio
    except ImportError as exc:
        _cleanup_on_failure()
        raise HTTPException(
            status_code=500,
            detail=f"rasterio 不可用: {exc}",
        ) from exc

    try:
        with rasterio.open(src_path) as dataset:
            west, south, east, north = dataset.bounds
            width = dataset.width
            height = dataset.height
            count = dataset.count
    except rasterio.errors.RasterioIOError as exc:
        _cleanup_on_failure()
        logger.exception("rasterio open failed: %s", src_path)
        raise HTTPException(
            status_code=422,
            detail="无法读取栅格文件：文件不存在或格式不支持。",
        ) from exc
    except rasterio.errors.RasterioError as exc:
        _cleanup_on_failure()
        logger.exception("rasterio read failed: %s", src_path)
        raise HTTPException(
            status_code=422,
            detail="栅格文件读取失败：数据损坏或 CRS 缺失。",
        ) from exc

    # 用 crs_detector 自动检测 CRS（比 str(crs) 更友好：归一化为 EPSG:xxxx）
    detection = crs_detector.detect_from_raster(src_path)
    source_crs = detection.source_crs
    suggested_crs = detection.suggested_crs
    needs_confirm = detection.needs_user_confirm

    # 生成预览 PNG（保持源 CRS，未重投影；confirm 阶段才会重投影）
    png_path = dest_dir / "preview.png"
    try:
        preview_width = min(_PREVIEW_MAX_DIMENSION, width)
        preview_height = min(_PREVIEW_MAX_DIMENSION, height)
        png_bytes = raster_preview_service.render_cog_preview(
            cog_path=src_path,
            palette="wind-blue",
            width=preview_width,
            height=preview_height,
        )
        png_path.write_bytes(png_bytes)
    except (ValueError, rasterio.errors.RasterioError) as exc:
        _cleanup_on_failure()
        logger.exception("preview generation failed: %s", src_path)
        raise HTTPException(
            status_code=500,
            detail="预览生成失败，请检查栅格数据是否有效。",
        ) from exc
    except (OSError, RuntimeError) as exc:  # noqa: BLE001 — 渲染层文件 I/O 或处理异常
        _cleanup_on_failure()
        logger.exception("unexpected preview error: %s", src_path)
        raise HTTPException(
            status_code=500,
            detail="预览生成时发生意外错误。",
        ) from exc

    # 生成 bounds JSON（保留源 CRS 的 bounds，confirm 阶段才转 WGS84）
    bounds: list[float] = [float(west), float(south), float(east), float(north)]
    bounds_data = {
        "bounds": bounds,
        "meta": {
            "layer_id": layer_id,
            "category": "static",
            "palette": "wind-blue",
            "vmin": None,
            "vmax": None,
            "unit": "",
            "opacity": 0.7,
            "crs": source_crs,  # 源 CRS；confirm 后会被覆盖为 'EPSG:4326'
            "time_list": [],
            "default_time": None,
            "current_time": None,
            "source_filename": filename,
            "source_crs": source_crs,
            "source_crs_confidence": detection.confidence,
            "source_crs_method": detection.method,
            "source_crs_notes": detection.notes,
            "source_width": width,
            "source_height": height,
            "source_bands": count,
        },
    }
    bounds_path = dest_dir / "bounds.json"
    bounds_path.write_text(
        json.dumps(bounds_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 动态注册到 overlay_registry（crs 字段保留源 CRS；confirm 后会重新注册为 WGS84）
    register_overlay(
        OverlaySpec(
            layer_id=layer_id,
            overlay_dir=dest_dir,
            png_filename="preview.png",
            bounds_filename="bounds.json",
            category="static",
            palette="wind-blue",
            opacity=0.7,
            crs=source_crs,
            source_path=src_path,
            source_reader="geotiff",
        )
    )

    return {
        "layer_id": layer_id,
        "bounds": bounds,
        "source_crs": source_crs,
        "suggested_crs": suggested_crs,
        "needs_confirm": needs_confirm,
        "detection_notes": detection.notes,
    }


@router.delete(
    "/raster/{layer_id}", dependencies=[Depends(require_data_transfer_access)]
)
async def delete_imported_raster(layer_id: str) -> dict[str, Any]:
    """删除动态导入的栅格 overlay，并清理磁盘目录。"""
    if not layer_id.startswith("imported-"):
        raise HTTPException(status_code=400, detail="仅允许删除 imported-* 图层")

    # 安审 2026-08-21 S-1：layer_id 来自 URL（Windows 下 %5C 解码为 \ 可穿越），
    # rmtree 前必须校验（对齐 data_io router delete_imported_layer 的既有校验）。
    try:
        dest_dir = _safe_import_child(layer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    spec = unregister_overlay(layer_id)
    if spec is None and not dest_dir.exists():
        raise HTTPException(status_code=404, detail=f"导入图层不存在: {layer_id}")

    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)

    return {"ok": True, "layer_id": layer_id}


# ── CRS 确认端点 ───────────────────────────────────────────────────────


@router.post("/raster/confirm", dependencies=[Depends(require_data_transfer_access)])
async def confirm_imported_raster(body: ConfirmRequest) -> dict[str, Any]:
    """用户确认 CRS 后：重投影 PNG、重算 bounds、更新 overlay。"""
    try:
        return confirm_imported_raster_crs(
            body.layer_id,
            source_crs=body.source_crs,
            lng_offset=body.lng_offset,
            lat_offset=body.lat_offset,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:  # noqa: BLE001 — rasterio/pyproj 运行时异常
        logger.exception("raster confirm failed: layer_id=%s", body.layer_id)
        raise HTTPException(
            status_code=500,
            detail="重投影失败，请检查源 CRS 是否正确。",
        ) from exc


# ── 转换端点 ───────────────────────────────────────────────────────────


@router.post("/transform-point", dependencies=[Depends(require_data_transfer_access)])
async def transform_point_endpoint(body: TransformPointRequest) -> dict[str, Any]:
    """批量点转换（前端 CSV/POI 提交时用）。

    委托 ``crs_transformer.transform_points_batch``。返回转换后的点列表。
    """
    try:
        results = crs_transformer.transform_points_batch(
            body.points,
            body.source_crs,
            body.target_crs,
            lng_offset=body.lng_offset,
            lat_offset=body.lat_offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"点转换失败: {exc}",
        ) from exc
    except (OSError, RuntimeError) as exc:  # noqa: BLE001 — pyproj 运行时异常
        logger.exception(
            "transform-point failed: %s→%s", body.source_crs, body.target_crs
        )
        raise HTTPException(
            status_code=400,
            detail="点转换失败，请检查 CRS 标识符是否正确。",
        ) from exc

    return {
        "points": [[r.lng, r.lat] for r in results],
        "source_crs": body.source_crs,
        "target_crs": body.target_crs,
        "applied_offset": [body.lng_offset, body.lat_offset],
        "count": len(results),
    }


@router.post("/transform-bounds", dependencies=[Depends(require_data_transfer_access)])
async def transform_bounds_endpoint(body: TransformBoundsRequest) -> dict[str, Any]:
    """bounds 转换（前端栅格预览用）。

    委托 ``crs_transformer.transform_bounds``。返回目标 CRS 下的 bounds。
    """
    if len(body.bounds) != 4:
        raise HTTPException(
            status_code=400,
            detail="bounds 必须为 [west, south, east, north] 4 元素",
        )

    west, south, east, north = body.bounds
    try:
        target_w, target_s, target_e, target_n = crs_transformer.transform_bounds(
            west,
            south,
            east,
            north,
            body.source_crs,
            body.target_crs,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"bounds 转换失败: {exc}",
        ) from exc
    except (OSError, RuntimeError) as exc:  # noqa: BLE001 — pyproj 运行时异常
        logger.exception(
            "transform-bounds failed: %s→%s", body.source_crs, body.target_crs
        )
        raise HTTPException(
            status_code=400,
            detail="bounds 转换失败，请检查 CRS 标识符是否正确。",
        ) from exc

    return {
        "bounds": [float(target_w), float(target_s), float(target_e), float(target_n)],
        "source_crs": body.source_crs,
        "target_crs": body.target_crs,
    }
