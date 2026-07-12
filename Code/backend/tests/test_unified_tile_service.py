"""统一瓦片服务测试。

验证：
1. TileProviderRegistry 匹配顺序与路由
2. BaseMapTileProvider 匹配已知底图 ID
3. WeatherTileProvider 匹配天气图层 ID
4. Registry.resolve('unknown-id') == None
5. 统一端点返回正确 content_type 和 headers
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch


class TileProviderRegistryTests(unittest.TestCase):
    """测试 TileProviderRegistry 的匹配与路由。"""

    def test_registry_resolves_basemap_provider_id(self) -> None:
        from app.services.providers.basemap_tile_provider import BaseMapTileProvider
        provider = BaseMapTileProvider()
        self.assertTrue(provider.matches("gaode-street"))
        self.assertTrue(provider.matches("esri-street"))
        self.assertTrue(provider.matches("tianditu-img"))
        self.assertTrue(provider.matches("osm-standard"))
        self.assertFalse(provider.matches("wind-field"))

    def test_registry_resolves_weather_layer_id(self) -> None:
        from app.services.providers.weather_tile_provider import WeatherTileProvider
        provider = WeatherTileProvider()
        # 天气图层 ID 来自 layer_catalog 中 source_type=weather 的条目
        self.assertTrue(provider.matches("wind-field"))
        self.assertTrue(provider.matches("temperature"))
        self.assertTrue(provider.matches("precipitation"))
        self.assertFalse(provider.matches("gaode-street"))
        self.assertFalse(provider.matches("unknown-layer"))

    def test_registry_returns_none_for_unknown_id(self) -> None:
        from app.services.tile_provider_registry import TileProviderRegistry
        from app.services.providers.basemap_tile_provider import BaseMapTileProvider
        from app.services.providers.weather_tile_provider import WeatherTileProvider

        registry = TileProviderRegistry()
        registry.register(BaseMapTileProvider())
        registry.register(WeatherTileProvider())

        self.assertIsNone(registry.resolve("totally-unknown-layer-id"))

    def test_registry_basemap_takes_priority_over_weather(self) -> None:
        """底图 provider 先注册，应优先匹配。"""
        from app.services.tile_provider_registry import TileProviderRegistry
        from app.services.providers.basemap_tile_provider import BaseMapTileProvider
        from app.services.providers.weather_tile_provider import WeatherTileProvider

        registry = TileProviderRegistry()
        registry.register(BaseMapTileProvider())
        registry.register(WeatherTileProvider())

        resolved = registry.resolve("gaode-street")
        self.assertIsNotNone(resolved)
        # 应该是 BaseMapTileProvider 实例
        self.assertTrue(resolved.matches("gaode-street"))
        self.assertFalse(resolved.matches("wind-field"))

    def test_registry_get_tile_raises_value_error_for_unknown(self) -> None:
        from app.services.tile_provider_registry import TileProviderRegistry
        from app.services.providers.basemap_tile_provider import BaseMapTileProvider
        from app.services.providers.weather_tile_provider import WeatherTileProvider

        registry = TileProviderRegistry()
        registry.register(BaseMapTileProvider())
        registry.register(WeatherTileProvider())

        with self.assertRaises(ValueError) as ctx:
            asyncio.new_event_loop().run_until_complete(
                registry.get_tile("unknown-id", z=5, x=25, y=12)
            )
        self.assertIn("No tile provider matches", str(ctx.exception))


class UnifiedTileEndpointTests(unittest.TestCase):
    """测试统一瓦片端点的 HTTP 响应。"""

    def test_unified_endpoint_returns_basemap_tile(self) -> None:
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

        self.assertEqual(response.status_code, 200)
        self.assertIn("image/", response.headers.get("content-type", ""))
        self.assertEqual(response.headers.get("X-Tile-Provider"), "esri-street")
        self.assertEqual(response.content, b"fake-png-data")

    def test_unified_endpoint_returns_weather_tile(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import create_app

        app = create_app()
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
            "app.weatherengine.tile_service.get_weather_tile_service",
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
                "/unified-tiles/wind-field/5/25/12",
                params={"hour": 0},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("content-type"), "application/geo+json")
        self.assertEqual(response.headers.get("X-Weather-Tile-Cache"), "miss")
        self.assertIn(b"FeatureCollection", response.content)

    def test_unified_endpoint_returns_404_for_unknown_layer(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import create_app

        app = create_app()
        client = TestClient(app)

        response = client.get("/unified-tiles/totally-unknown-layer/5/25/12")

        self.assertEqual(response.status_code, 404)
        self.assertIn("No tile provider matches", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
