"""统一瓦片服务测试。

验证：
1. TileProviderRegistry 匹配顺序与路由
2. BaseMapTileProvider 匹配已知底图 ID
3. WeatherTileProvider 匹配天气图层 ID
4. Registry.resolve('unknown-id') == None
5. 统一端点返回正确 content_type 和 headers
"""

from __future__ import annotations

import pytest
import asyncio
from unittest.mock import AsyncMock, patch


def test_registry_resolves_basemap_provider_id() -> None:
    from app.services.providers.basemap_tile_provider import BaseMapTileProvider

    provider = BaseMapTileProvider()
    assert provider.matches("gaode-street"), 'provider.matches("gaode-street") is truthy'
    assert provider.matches("esri-street"), 'provider.matches("esri-street") is truthy'
    assert provider.matches("tianditu-img"), 'provider.matches("tianditu-img") is truthy'
    assert provider.matches("osm-standard"), 'provider.matches("osm-standard") is truthy'
    assert not provider.matches("wind-field"), 'provider.matches("wind-field") is falsy'


def test_registry_resolves_weather_layer_id() -> None:
    from app.services.providers.weather_tile_provider import WeatherTileProvider

    provider = WeatherTileProvider()
    # 天气图层 ID 来自 layer_catalog 中 source_type=weather 的条目
    assert provider.matches("wind-field"), 'provider.matches("wind-field") is truthy'
    assert provider.matches("temperature"), 'provider.matches("temperature") is truthy'
    assert provider.matches("precipitation"), 'provider.matches("precipitation") is truthy'
    assert not provider.matches("gaode-street"), 'provider.matches("gaode-street") is falsy'
    assert not provider.matches("unknown-layer"), 'provider.matches("unknown-layer") is falsy'


def test_registry_returns_none_for_unknown_id() -> None:
    from app.services.tile_provider_registry import TileProviderRegistry
    from app.services.providers.basemap_tile_provider import BaseMapTileProvider
    from app.services.providers.weather_tile_provider import WeatherTileProvider

    registry = TileProviderRegistry()
    registry.register(BaseMapTileProvider())
    registry.register(WeatherTileProvider())

    assert registry.resolve("totally-unknown-layer-id") is None, 'registry.resolve("totally-unknown-layer-id") is None'


def test_registry_basemap_takes_priority_over_weather() -> None:
    """底图 provider 先注册，应优先匹配。"""
    from app.services.tile_provider_registry import TileProviderRegistry
    from app.services.providers.basemap_tile_provider import BaseMapTileProvider
    from app.services.providers.weather_tile_provider import WeatherTileProvider

    registry = TileProviderRegistry()
    registry.register(BaseMapTileProvider())
    registry.register(WeatherTileProvider())

    resolved = registry.resolve("gaode-street")
    assert resolved is not None, 'resolved is not None'
    # 应该是 BaseMapTileProvider 实例
    assert resolved.matches("gaode-street"), 'resolved.matches("gaode-street") is truthy'
    assert not resolved.matches("wind-field"), 'resolved.matches("wind-field") is falsy'


def test_registry_get_tile_raises_value_error_for_unknown() -> None:
    from app.services.tile_provider_registry import TileProviderRegistry
    from app.services.providers.basemap_tile_provider import BaseMapTileProvider
    from app.services.providers.weather_tile_provider import WeatherTileProvider

    registry = TileProviderRegistry()
    registry.register(BaseMapTileProvider())
    registry.register(WeatherTileProvider())

    with pytest.raises(ValueError) as ctx:
        asyncio.new_event_loop().run_until_complete(
            registry.get_tile("unknown-id", z=5, x=25, y=12)
        )
    assert "No tile provider matches" in str(ctx.value), '"No tile provider matches" in str(ctx.exception)'


def test_unified_endpoint_returns_basemap_tile() -> None:
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    with patch(
        "app.services.tile_proxy_service.tile_proxy_service.fetch_tile",
        new_callable=AsyncMock,
        return_value=b"fake-png-data",
    ):
        response = client.get("/unified-tiles/esri-street/5/25/12")

    assert response.status_code == 200, 'response.status_code == 200'
    assert "image/" in response.headers.get("content-type", ""), '"image/" in response.headers.get("content-type", "")'
    assert response.headers.get("X-Tile-Provider") == "esri-street", 'response.headers.get("X-Tile-Provider") == "esri-street"'
    assert response.content == b"fake-png-data", 'response.content == b"fake-png-data"'


def test_weather_endpoint_returns_weather_tile() -> None:
    """天气瓦片通过 /weather/tiles/ 端点提供（非 /unified-tiles/）。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    from app.api.deps import get_request_user
    app.dependency_overrides[get_request_user] = lambda: type("MockUser", (), {"id": "test", "role": "admin"})()
    client = TestClient(app)

    mock_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [113.26, 23.13]},
                "properties": {"wind_speed_10m": 5.2},
            }
        ],
    }

    with patch(
        "app.api.weather_tile_routes.get_weather_tile_service",
        return_value=type(
            "MockSvc",
            (),
            {
                "get_tile": AsyncMock(
                    return_value=(mock_geojson, "miss"),
                ),
            },
        )(),
    ):
        response = client.get(
            "/weather/tiles/wind-field/5/25/12",
            params={"hour": 0},
        )

    assert response.status_code == 200, 'response.status_code == 200'
    assert response.headers.get("content-type") == "application/geo+json", 'response.headers.get("content-type") == "application/geo+json"'
    assert response.headers.get("X-Weather-Tile-Cache") == "miss", 'response.headers.get("X-Weather-Tile-Cache") == "miss"'
    assert b"FeatureCollection" in response.content, 'b"FeatureCollection" in response.content'


def test_unified_endpoint_returns_404_for_unknown_layer() -> None:
    """未知 layer_id 在 /unified-tiles/ 端点返回 404，提示使用 /weather/tiles/。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    response = client.get("/unified-tiles/totally-unknown-layer/5/25/12")

    assert response.status_code == 404, 'response.status_code == 404'
    detail = response.json()["detail"]
    # 架构变更后：unified-tiles 仅服务底图，非底图 layer_id 提示使用 /weather/tiles/
    assert "Unknown basemap layer_id" in detail, '"Unknown basemap layer_id" in detail'
