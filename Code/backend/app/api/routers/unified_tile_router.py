"""统一底图瓦片服务路由。

正式入口：``GET /unified-tiles/{layer_id}/{z}/{x}/{y}``（仅底图栅格）。
天气 GeoJSON 瓦片请使用 ``GET /weather/tiles/{layer_id}/{z}/{x}/{y}``。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Response

from app.services.tile_provider_registry import tile_provider_registry
from app.services.tile_proxy_service import TILE_URL_TEMPLATES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/unified-tiles", tags=["tiles"])


@router.get("/{layer_id}/{z}/{x}/{y}")
async def get_unified_tile(
    layer_id: str,
    z: int,
    x: int,
    y: int,
    use_cache: bool = True,
    t: int | None = Query(default=None, description="客户端缓存 bust，不参与业务"),
) -> Response:
    """获取底图栅格瓦片。"""
    if layer_id not in TILE_URL_TEMPLATES:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown basemap layer_id: {layer_id}. "
                "Weather layers use GET /weather/tiles/{layer_id}/{z}/{x}/{y}."
            ),
        )
    if z < 0 or z > 18:
        raise HTTPException(status_code=400, detail="Zoom level must be between 0 and 18")
    if x < 0 or y < 0:
        raise HTTPException(status_code=400, detail="Invalid tile coordinates")

    try:
        tile = await tile_provider_registry.get_tile(
            layer_id,
            z,
            x,
            y,
            use_cache=use_cache,
        )
    except ValueError as exc:
        message = str(exc).lower()
        status_code = 404 if "unknown" in message or "not found" in message else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[UnifiedTileRoutes] failed to generate tile for layer=%s", layer_id)
        raise HTTPException(status_code=503, detail=f"Tile unavailable: {exc}") from exc

    headers = dict(tile.extra_headers)
    if tile.cache_status:
        headers["X-Tile-Cache"] = tile.cache_status
    if t is not None:
        headers["X-Tile-T"] = str(t)

    return Response(
        content=tile.data,
        media_type=tile.content_type,
        headers=headers,
    )
