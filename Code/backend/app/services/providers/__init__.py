"""瓦片提供者注册入口。

导入此包即自动注册默认提供者（BaseMap + Weather）。
"""

from app.services.providers.basemap_tile_provider import BaseMapTileProvider
from app.services.providers.weather_tile_provider import WeatherTileProvider
from app.services.tile_provider_registry import tile_provider_registry


def register_default_providers() -> None:
    """注册默认瓦片提供者。"""
    tile_provider_registry.register(BaseMapTileProvider())
    tile_provider_registry.register(WeatherTileProvider())


# 模块加载时自动注册
register_default_providers()
