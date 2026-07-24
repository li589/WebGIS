"""底图瓦片提供者。

包装 :mod:`app.services.tile_proxy_service`，匹配 ``TILE_URL_TEMPLATES`` 中已注册的底图 provider ID。
"""

from __future__ import annotations

from typing import Any

from app.services.tile_provider_protocol import TileResponse


class BaseMapTileProvider:
    """底图瓦片提供者，匹配 ``TILE_URL_TEMPLATES`` 中的已知 provider ID。"""

    def matches(self, layer_id: str) -> bool:
        from app.services.tile_proxy_service import TILE_URL_TEMPLATES

        return layer_id in TILE_URL_TEMPLATES

    async def get_tile(
        self,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        **params: Any,
    ) -> TileResponse:
        from app.services.tile_proxy_service import tile_proxy_service

        use_cache = params.get("use_cache", True)
        data = await tile_proxy_service.fetch_tile(
            tile_id=layer_id,
            x=x,
            y=y,
            z=z,
            use_cache=use_cache,
        )

        # 推断 content_type（与 tile_routes.py 保持一致）
        if "baidu" in layer_id or "gaode" in layer_id:
            content_type = "image/png"
        elif "satellite" in layer_id or "img" in layer_id:
            content_type = "image/jpeg"
        else:
            content_type = "image/png"

        return TileResponse(
            data=data,
            content_type=content_type,
            extra_headers={
                "Cache-Control": "public, max-age=86400",
                "X-Tile-Provider": layer_id,
            },
        )
