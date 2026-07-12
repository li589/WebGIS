"""统一瓦片服务路由。

提供单一端点 ``GET /unified-tiles/{layer_id}/{z}/{x}/{y}``，
通过 :class:`TileProviderRegistry` 路由到底图代理服务或天气瓦片服务。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Response

from app.services.tile_provider_registry import tile_provider_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/unified-tiles", tags=["tiles"])


@router.get("/{layer_id}/{z}/{x}/{y}")
async def get_unified_tile(
    layer_id: str,
    z: int,
    x: int,
    y: int,
    hour: int | None = Query(default=0, ge=0, le=47),
    model: str | None = Query(default=None),
    use_cache: bool = True,
    t: int | None = Query(default=None, description="客户端缓存 bust，不参与业务"),
) -> Response:
    """获取指定图层的瓦片数据（底图栅格或天气 GeoJSON）。"""
    try:
        tile = await tile_provider_registry.get_tile(
            layer_id,
            z,
            x,
            y,
            hour=hour,
            model=model,
            use_cache=use_cache,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
