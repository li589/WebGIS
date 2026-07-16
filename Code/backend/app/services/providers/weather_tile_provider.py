"""DEPRECATED — 天气瓦片提供者（历史遗留）。

天气瓦片正式入口已迁移至 ``GET /weather/tiles/{layer_id}/{z}/{x}/{y}``，
不再注册到 ``tile_provider_registry``（见 ``app.services.providers``）。

保留本模块仅供单元测试引用；新代码请直接使用 ``app.weatherengine.tile_service``。
"""

from __future__ import annotations

import json
from typing import Any

from app.services.tile_provider_protocol import TileResponse


class WeatherTileProvider:
    """天气瓦片提供者，匹配天气图层 ID。"""

    def __init__(self) -> None:
        self._weather_layer_ids: set[str] | None = None

    def _ensure_layer_ids(self) -> set[str]:
        if self._weather_layer_ids is None:
            from app.services.layer_catalog import get_layer_catalog
            from shared.contracts.api_contracts import LayerSourceType

            catalog = get_layer_catalog()
            self._weather_layer_ids = {
                item.layer_id
                for item in catalog.items
                if item.source_type == LayerSourceType.weather
            }
        return self._weather_layer_ids

    def matches(self, layer_id: str) -> bool:
        return layer_id in self._ensure_layer_ids()

    async def get_tile(
        self,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        **params: Any,
    ) -> TileResponse:
        from app.core.config import settings
        from app.weatherengine.tile_service import get_weather_tile_service

        hour = params.get("hour", 0)
        model = params.get("model")

        geojson, cache_status = await get_weather_tile_service().get_tile(
            layer_id=layer_id,
            z=z,
            x=x,
            y=y,
            hour=hour,
            model=model,
        )

        return TileResponse(
            data=json.dumps(geojson, ensure_ascii=False).encode(),
            content_type="application/geo+json",
            cache_status=cache_status,
            extra_headers={
                "Cache-Control": f"public, max-age={settings.weather_cache_ttl_seconds}",
                "X-Weather-Tile-Cache": cache_status,
                "X-Weather-Tile-Key": f"{layer_id}:z{z}:x{x}:y{y}:h{hour}",
            },
        )
