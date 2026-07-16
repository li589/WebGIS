"""瓦片提供者注册入口（底图专用）。

天气瓦片走 ``/weather/tiles``，不再注册 WeatherTileProvider。
"""

from app.services.providers.basemap_tile_provider import BaseMapTileProvider
from app.services.tile_provider_registry import tile_provider_registry

_registered = False


def register_default_providers() -> None:
    """注册默认底图瓦片提供者（幂等）。"""
    global _registered
    if _registered:
        return
    # 清空后重建，避免历史进程内重复叠加
    if hasattr(tile_provider_registry, "clear"):
        tile_provider_registry.clear()
    tile_provider_registry.register(BaseMapTileProvider())
    _registered = True
