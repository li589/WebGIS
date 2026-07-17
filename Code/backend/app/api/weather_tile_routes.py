"""天气 GeoJSON 瓦片 REST 路由。

正式入口：``GET /weather/tiles/{layer_id}/{z}/{x}/{y}``
（底图栅格请使用 ``GET /unified-tiles/{layer_id}/{z}/{x}/{y}``）
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query, Response

from app.services.effective_config import get_weather_cache_ttl_seconds
from app.weatherengine.tile_service import get_weather_tile_service, normalize_provider_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weather/tiles", tags=["weather"])


def _classify_weather_tile_error(exc: ValueError) -> int:
    """未知/不支持图层 → 404；无可用 Provider → 503；非法坐标或参数 → 400。"""
    message = str(exc).lower()
    if any(
        token in message
        for token in (
            "no enabled weather provider",
            "is disabled",
            "is not registered",
            "does not support layer",
        )
    ):
        return 503
    if any(
        token in message
        for token in (
            "unknown",
            "unsupported",
            "not found",
            "not supported",
            "no weather",
            "not a weather",
        )
    ):
        return 404
    return 400


@router.get("/{layer_id}/{z}/{x}/{y}")
async def get_weather_tile(
    layer_id: str,
    z: int,
    x: int,
    y: int,
    hour: int | None = Query(default=0, ge=0, le=47),
    model: str | None = Query(default=None),
    provider: str | None = Query(default=None, description="Weather provider id, or omit/auto for registry priority"),
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
            provider_id=provider,
        )
    except ValueError as exc:
        status_code = _classify_weather_tile_error(exc)
        logger.warning("[WeatherTileRoutes] invalid request (%s): %s", status_code, exc)
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[WeatherTileRoutes] failed to generate tile")
        raise HTTPException(status_code=503, detail=f"Weather tile unavailable: {exc}") from exc

    meta = geojson.get("_tile_meta") if isinstance(geojson, dict) else None
    resolved_provider = None
    if isinstance(meta, dict):
        resolved_provider = meta.get("provider_id")
    if not resolved_provider:
        resolved_provider = normalize_provider_id(provider)

    headers = {
        "X-Weather-Tile-Key": f"{layer_id}:z{z}:x{x}:y{y}:h{hour}:p{normalize_provider_id(provider)}",
        "X-Weather-Tile-Cache": cache_status,
        "X-Weather-Provider": str(resolved_provider),
        "Cache-Control": f"public, max-age={get_weather_cache_ttl_seconds()}",
    }
    if t is not None:
        headers["X-Weather-Tile-T"] = str(t)

    return Response(
        content=json.dumps(geojson, ensure_ascii=False),
        media_type="application/geo+json",
        headers=headers,
    )
