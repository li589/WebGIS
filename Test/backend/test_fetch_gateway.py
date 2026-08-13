"""fetch_gateway 统一取数路径单测。"""

from __future__ import annotations

import pytest
import types
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


@pytest.fixture
def _fetch_gateway_tests_env():
    ns = types.SimpleNamespace()
    ns.client = _CountingClient()
    registry = get_registry()
    registry.clear()
    registry.register(
        OpenMeteoProvider(client=ns.client), priority=0, enabled=True
    )
    yield ns
    get_registry().clear()


def test_point_and_grid_go_through_registry(_fetch_gateway_tests_env) -> None:
    self = _fetch_gateway_tests_env
    payload, status, provider_id = fetch_point_forecast(
        layer_id="temperature",
        latitude=23.1,
        longitude=113.2,
        forecast_hours=1,
    )
    assert status == "miss", 'status == "miss"'
    assert provider_id == "open-meteo-online", 'provider_id == "open-meteo-online"'
    assert "current" in payload, '"current" in payload'
    assert self.client.calls == ["point"], 'self.client.calls == ["point"]'

    grid, gstatus, gpid = fetch_grid_forecast(
        layer_id="temperature",
        bbox=BoundingBox(west=113.0, south=23.0, east=113.5, north=23.5),
        resolution=0.25,
    )
    assert gstatus == "miss", 'gstatus == "miss"'
    assert gpid == "open-meteo-online", 'gpid == "open-meteo-online"'
    assert "grid" in grid, '"grid" in grid'
    assert self.client.calls == ["point", "grid"], 'self.client.calls == ["point", "grid"]'


def test_disabled_provider_blocks_outbound(_fetch_gateway_tests_env) -> None:
    self = _fetch_gateway_tests_env
    get_registry().set_enabled("open-meteo-online", False)
    with pytest.raises(WeatherProviderUnavailableError):
        fetch_point_forecast(layer_id="wind-field", latitude=1.0, longitude=1.0)
    with pytest.raises(WeatherProviderUnavailableError):
        fetch_grid_forecast(
            layer_id="wind-field",
            bbox=BoundingBox(west=0, south=0, east=1, north=1),
            resolution=0.5,
        )
    assert self.client.calls == [], 'self.client.calls == []'


def test_uses_effective_ttl(_fetch_gateway_tests_env) -> None:
    self = _fetch_gateway_tests_env
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
        assert seen.get("ttl_seconds") == 12345, 'seen.get("ttl_seconds") == 12345'


def test_pinned_commercial_grid_not_swapped_to_dense(_fetch_gateway_tests_env) -> None:
    """Layer 选源 pin must reach grid/tiles (not silently fall back to OM)."""
    self = _fetch_gateway_tests_env
    from app.weatherengine.field_mapping import COMMERCIAL_LAYER_IDS
    from app.weatherengine.provider_base import ProviderType, WeatherProvider

    commercial_client = _CountingClient()

    class _FakeCommercial(WeatherProvider):
        @property
        def provider_id(self) -> str:
            return "weatherapi"

        @property
        def display_name(self) -> str:
            return "WeatherAPI.com"

        @property
        def provider_type(self) -> str:
            return ProviderType.COMMERCIAL_API

        @property
        def supported_capabilities(self) -> frozenset[str]:
            return frozenset(COMMERCIAL_LAYER_IDS)

        def fetch_point_forecast(self, **kwargs: Any) -> tuple[dict[str, Any], str]:
            return commercial_client.fetch_point_forecast(**kwargs)

        def fetch_grid_forecast(self, **kwargs: Any) -> tuple[dict[str, Any], str]:
            return commercial_client.fetch_grid_forecast(**kwargs)

    get_registry().register(_FakeCommercial(), priority=10, enabled=True)

    _grid, _status, pid = fetch_grid_forecast(
        layer_id="temperature",
        bbox=BoundingBox(west=113.0, south=23.0, east=113.5, north=23.5),
        resolution=0.25,
        provider_id="weatherapi",
    )
    assert pid == "weatherapi", 'pid == "weatherapi"'
    assert commercial_client.calls == ["grid"], 'commercial_client.calls == ["grid"]'
    assert self.client.calls == [], 'self.client.calls == []'
