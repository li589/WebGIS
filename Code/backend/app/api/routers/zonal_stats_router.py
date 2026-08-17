"""
同步分区统计 API — POST /analysis/zonal-stats/sync
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.zonal_stats_service import compute_zonal_stats

router = APIRouter(tags=["analysis"])

CATALOG_SEEDS_DIR = Path(__file__).resolve().parents[2] / "catalog_seeds"


class ZonalStatsSyncRequest(BaseModel):
    geojson: dict = Field(..., description="面要素 GeoJSON（Feature 或 Geometry）")
    overlay_layer_ids: list[str] = Field(..., description="要统计的栅格图层 ID 列表")


class LayerZonalStats(BaseModel):
    layer_id: str
    layer_name: str
    mean: Optional[float] = None
    max: Optional[float] = None
    min: Optional[float] = None
    sum: Optional[float] = None
    count: int = 0
    std: Optional[float] = None
    unit: Optional[str] = None


class ZonalStatsSyncResponse(BaseModel):
    results: list[LayerZonalStats]


@router.post(
    "/analysis/zonal-stats/sync",
    response_model=ZonalStatsSyncResponse,
    summary="同步分区统计",
)
async def sync_zonal_stats(body: ZonalStatsSyncRequest) -> ZonalStatsSyncResponse:
    """对指定面要素区域内的栅格图层进行同步统计（均值/最值/像元数/标准差）。"""
    data_root_str = (settings.data_root or "").strip()
    if not data_root_str:
        raise HTTPException(status_code=500, detail="数据根目录未配置")
    data_root = Path(data_root_str)

    try:
        layer_descriptors = _load_layer_descriptors()
        results = compute_zonal_stats(
            geojson=body.geojson,
            overlay_layer_ids=body.overlay_layer_ids,
            data_root=data_root,
            layer_descriptors=layer_descriptors,
        )
        return ZonalStatsSyncResponse(results=[LayerZonalStats(**r) for r in results])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分区统计失败: {e}") from e


def _load_layer_descriptors() -> dict:
    """从 catalog_seeds/layer_descriptors.json 加载图层描述符"""
    descriptors: dict = {}
    seed_file = CATALOG_SEEDS_DIR / "layer_descriptors.json"
    if not seed_file.exists():
        return descriptors

    try:
        with open(seed_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    lid = item.get("id") or item.get("catalog_id")
                    if lid:
                        descriptors[lid] = item
        elif isinstance(data, dict):
            descriptors.update({k: v for k, v in data.items() if isinstance(v, dict)})
    except Exception:
        pass

    return descriptors
