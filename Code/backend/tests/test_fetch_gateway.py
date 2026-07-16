"""fetch_gateway 统一取数路径单测。"""
from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from app.weatherengine.fetch_gateway import (
    WeatherProviderUnavailableError,
    fetch_grid_forecast,
    fetch_point_forecast,
)
from app.weatherengine.provider_registry import get_registry
from app.weatherengine.providers.open_meteo_provider import OpenMeteoProvider
from shared.contracts.api_contracts import BoundingBox


class _CountingClient:
    calls: list[str]

    def __init__(self) -> None:
        self.calls = []

    def fetch_point_forecast(self, **kwargs: Any) -> tuple[dict[str, Any], str]:
        self.calls.append("point")
        return ({"current": {"temperature_2m": 1.0}, "hourly": {}}, "miss")

    def fetch_grid_forecast(self, **kwargs: Any) -> tuple[dict[str, Any], str]:
        self.calls.append("grid")
        return (
            {
                "grid": {
                    "bbox": {"west": 0, "south": 0, "east": 1, "north": 1},
                    "rows": 1,
                    "cols": 1,
                    "resolution": 1.0,
                    "lats": [0.5],
                    "lons": [0.5],
                },
                "data": {"current": {"temperature_2m": [1.0]}},
            },
            "miss",
        )


class FetchGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = _CountingClient()
        registry = get_registry()
        registry.clear()
        registry.register(OpenMeteoProvider(client=self.client), priority=0, enabled=True)

    def tearDown(self) -> None:
        get_registry().clear()

    def test_point_and_grid_go_through_registry(self) -> None:
        payload, status, provider_id = fetch_point_forecast(
            layer_id="temperature",
            latitude=23.1,
            longitude=113.2,
            forecast_hours=1,
        )
        self.assertEqual(status, "miss")
        self.assertEqual(provider_id, "open-meteo")
        self.assertIn("current", payload)
        self.assertEqual(self.client.calls, ["point"])

        grid, gstatus, gpid = fetch_grid_forecast(
            layer_id="temperature",
            bbox=BoundingBox(west=113.0, south=23.0, east=113.5, north=23.5),
            resolution=0.25,
        )
        self.assertEqual(gstatus, "miss")
        self.assertEqual(gpid, "open-meteo")
        self.assertIn("grid", grid)
        self.assertEqual(self.client.calls, ["point", "grid"])

    def test_disabled_provider_blocks_outbound(self) -> None:
        get_registry().set_enabled("open-meteo", False)
        with self.assertRaises(WeatherProviderUnavailableError):
            fetch_point_forecast(layer_id="wind-field", latitude=1.0, longitude=1.0)
        with self.assertRaises(WeatherProviderUnavailableError):
            fetch_grid_forecast(
                layer_id="wind-field",
                bbox=BoundingBox(west=0, south=0, east=1, north=1),
                resolution=0.5,
            )
        self.assertEqual(self.client.calls, [])

    def test_uses_effective_ttl(self) -> None:
        with patch(
            "app.weatherengine.fetch_gateway.get_weather_cache_ttl_seconds",
            return_value=12345,
        ):
            seen: dict[str, Any] = {}

            def _capture(**kwargs: Any):
                seen.update(kwargs)
                return ({"current": {}, "hourly": {}}, "miss")

            self.client.fetch_point_forecast = _capture  # type: ignore[method-assign]
            fetch_point_forecast(layer_id="wind-field", latitude=1.0, longitude=2.0)
            self.assertEqual(seen.get("ttl_seconds"), 12345)
