"""瓦片提供者注册表。

按注册顺序线性匹配 ``layer_id``，将请求路由到第一个匹配的提供者。
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.tile_provider_protocol import TileProvider, TileResponse

logger = logging.getLogger(__name__)


class TileProviderRegistry:
    """瓦片提供者注册表。"""

    def __init__(self) -> None:
        self._providers: list[TileProvider] = []

    def register(self, provider: TileProvider) -> None:
        self._providers.append(provider)

    def resolve(self, layer_id: str) -> TileProvider | None:
        for provider in self._providers:
            if provider.matches(layer_id):
                return provider
        return None

    async def get_tile(
        self,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        **params: Any,
    ) -> TileResponse:
        provider = self.resolve(layer_id)
        if provider is None:
            raise ValueError(f"No tile provider matches layer_id: {layer_id}")
        return await provider.get_tile(layer_id, z, x, y, **params)


# 全局单例
tile_provider_registry = TileProviderRegistry()
