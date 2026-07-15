"""栅格数据导入路由。

接收用户上传的 TIF 文件，生成预览 PNG + bounds JSON，
动态注册到 overlay_registry，使前端可通过 /overlay-preview/{layer_id} 访问。
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import settings
from app.services.overlay_registry import OverlaySpec, register_overlay
from app.services.raster_preview_service import raster_preview_service

router = APIRouter(prefix="/import", tags=["import"])

# 导入文件存储根目录
_OUTPUT_ROOT = Path(settings.output_root) if settings.output_root else Path.cwd() / "imports_output"
_IMPORTS_DIR = _OUTPUT_ROOT / "imports"


@router.post("/raster")
async def import_raster(file: UploadFile = File(...)) -> dict[str, Any]:
    """上传栅格文件（TIF），转 COG 预览，动态注册为 overlay 图层。

    返回 ``{"layer_id": "imported-xxx", "bounds": [west, south, east, north]}``。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名缺失")

    filename = Path(file.filename).name
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in ("tif", "tiff"):
        raise HTTPException(status_code=400, detail=f"仅支持 TIF/TIFF 文件，收到 .{ext}")

    # 生成唯一 ID 和存储目录
    layer_id = f"imported-{uuid.uuid4().hex[:12]}"
    dest_dir = _IMPORTS_DIR / layer_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 保存上传文件
    src_path = dest_dir / filename
    try:
        with src_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
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
            crs = dataset.crs
            width = dataset.width
            height = dataset.height
            count = dataset.count
    except Exception as exc:
        _cleanup_on_failure()
        raise HTTPException(
            status_code=422,
            detail=f"无法读取栅格文件: {exc}",
        ) from exc

    # 生成预览 PNG
    png_path = dest_dir / "preview.png"
    try:
        preview_width = min(1024, width)
        preview_height = min(1024, height)
        png_bytes = raster_preview_service.render_cog_preview(
            cog_path=src_path,
            palette="wind-blue",
            width=preview_width,
            height=preview_height,
        )
        png_path.write_bytes(png_bytes)
    except Exception as exc:
        _cleanup_on_failure()
        raise HTTPException(
            status_code=500,
            detail=f"预览生成失败: {exc}",
        ) from exc

    # 生成 bounds JSON
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
            "time_list": [],
            "default_time": None,
            "current_time": None,
            "source_filename": filename,
            "source_crs": str(crs) if crs else "unknown",
            "source_width": width,
            "source_height": height,
            "source_bands": count,
        },
    }
    bounds_path = dest_dir / "bounds.json"
    bounds_path.write_text(json.dumps(bounds_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 动态注册到 overlay_registry
    register_overlay(
        OverlaySpec(
            layer_id=layer_id,
            overlay_dir=dest_dir,
            png_filename="preview.png",
            bounds_filename="bounds.json",
            category="static",
            palette="wind-blue",
            opacity=0.7,
            source_path=src_path,
            source_reader="geotiff",
        )
    )

    return {
        "layer_id": layer_id,
        "bounds": bounds,
    }
