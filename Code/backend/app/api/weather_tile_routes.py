"""天气 GeoJSON 瓦片 REST 路由（已废弃，请使用 /unified-tiles/{layer_id}/{z}/{x}/{y}）。

标准 Web Mercator z/x/y 瓦片接口，供前端按瓦片请求天气数据。

已废弃：请使用统一瓦片端点 ``GET /unified-tiles/{layer_id}/{z}/{x}/{y}``。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.core.config import settings
from app.weatherengine.tile_service import get_weather_tile_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weather/tiles", tags=["weather"])


@router.get("/{layer_id}/{z}/{x}/{y}", deprecated=True)
async def get_weather_tile(
    request: Request,
    layer_id: str,
    z: int,
    x: int,
    y: int,
    hour: int | None = Query(default=0, ge=0, le=47),
    model: str | None = Query(default=None),
    t: int | None = Query(default=None),  # 客户端缓存 bust，不参与业务
) -> Response:
    """获取指定图层的标准 Web Mercator GeoJSON 瓦片。"""
    try:
        geojson, cache_status = await get_weather_tile_service().get_tile(
            layer_id=layer_id,
            z=z,
            x=x,
            y=y,
            hour=hour,
            model=model,
        )
    except ValueError as exc:
        logger.warning("[WeatherTileRoutes] invalid request: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # 上游断路器打开且无 stale cache 时，OpenMeteoClient 会抛出异常
        logger.exception("[WeatherTileRoutes] failed to generate tile")
        raise HTTPException(status_code=503, detail=f"Weather tile unavailable: {exc}") from exc

    headers = {
        "X-Weather-Tile-Key": f"{layer_id}:z{z}:x{x}:y{y}:h{hour}",
        "X-Weather-Tile-Cache": cache_status,
        "Cache-Control": f"public, max-age={settings.weather_cache_ttl_seconds}",
    }

    # 客户端传入 t 时，也把它回写便于调试
    if t is not None:
        headers["X-Weather-Tile-T"] = str(t)

    import json

    return Response(
        content=json.dumps(geojson, ensure_ascii=False),
        media_type="application/geo+json",
        headers=headers,
    )
