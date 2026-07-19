"""Multi-weather-provider: field mapping, pin/fallback, tile cache key."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.weatherengine.field_mapping import (
    kph_to_ms,
    openweather_current_to_om,
    weatherapi_current_to_om,
)
from app.weatherengine.fetch_gateway import fetch_point_forecast, resolve_provider_for_layer
from app.weatherengine.tile_service import normalize_provider_id, tile_key


class TestFieldMapping:
    def test_weatherapi_current_maps_wind_to_ms(self):
        mapped = weatherapi_current_to_om(
            {
                "temp_c": 22.5,
                "humidity": 60,
                "precip_mm": 0.2,
                "wind_kph": 36.0,
                "wind_degree": 180,
                "gust_kph": 54.0,
                "vis_km": 10.0,
            }
        )
        assert mapped["temperature_2m"] == 22.5
        assert mapped["relative_humidity_2m"] == 60
        assert mapped["precipitation"] == 0.2
        assert mapped["wind_speed_10m"] == pytest.approx(kph_to_ms(36.0))
        assert mapped["wind_direction_10m"] == 180
        assert mapped["visibility"] == pytest.approx(10_000.0)

    def test_openweather_current_maps_metric_fields(self):
        mapped = openweather_current_to_om(
            {
                "dt": 1_700_000_000,
                "temp": 18.0,
                "feels_like": 17.0,
                "humidity": 55,
                "clouds": 40,
                "pressure": 1012,
                "wind_speed": 4.5,
                "wind_deg": 90,
                "visibility": 8000,
                "rain": {"1h": 0.4},
            }
        )
        assert mapped["temperature_2m"] == 18.0
        assert mapped["precipitation"] == 0.4
        assert mapped["wind_speed_10m"] == 4.5
        assert mapped["wind_direction_10m"] == 90
        assert mapped["visibility"] == 8000
        assert mapped["time"] is not None


class TestNormalizeProvider:
    def test_auto_aliases(self):
        assert normalize_provider_id(None) == "auto"
        assert normalize_provider_id("") == "auto"
        assert normalize_provider_id("auto") == "auto"
        assert normalize_provider_id("DEFAULT") == "auto"
        assert normalize_provider_id("weatherapi") == "weatherapi"


class TestTileKeyProvider:
    def test_provider_part_isolates_cache(self):
        a = tile_key("temperature", 4, 1, 1, 0, "best_match", None)
        b = tile_key("temperature", 4, 1, 1, 0, "best_match", "openweather")
        assert a.endswith(":pauto")
        assert b.endswith(":popenweather")
        assert a != b


class TestResolvePin:
    def test_pin_requires_enabled_provider(self):
        provider = MagicMock()
        provider.provider_id = "weatherapi"
        provider.supports_layer.return_value = True
        registry = MagicMock()
        registry.get_provider.return_value = provider
        registry.is_enabled.return_value = False

        with patch("app.weatherengine.fetch_gateway.get_registry", return_value=registry):
            with pytest.raises(ValueError, match="disabled"):
                resolve_provider_for_layer("wind-field", provider_id="weatherapi")

    def test_pin_requires_layer_support(self):
        provider = MagicMock()
        provider.provider_id = "weatherapi"
        provider.supports_layer.return_value = False
        registry = MagicMock()
        registry.get_provider.return_value = provider
        registry.is_enabled.return_value = True

        with patch("app.weatherengine.fetch_gateway.get_registry", return_value=registry):
            with pytest.raises(ValueError, match="does not support"):
                resolve_provider_for_layer("wind-field-80m", provider_id="weatherapi")


class TestFetchPointFallback:
    def test_auto_fallback_on_primary_failure(self):
        primary = MagicMock()
        primary.provider_id = "open-meteo-online"
        primary.fetch_point_forecast.side_effect = RuntimeError("upstream down")

        fallback = MagicMock()
        fallback.provider_id = "weatherapi"
        fallback.fetch_point_forecast.return_value = ({"current": {"temperature_2m": 1}}, "miss")

        spec = MagicMock()
        spec.pressure_levels = None

        with (
            patch(
                "app.weatherengine.fetch_gateway.resolve_provider_for_layer",
                side_effect=[primary, fallback],
            ),
            patch("app.weatherengine.fetch_gateway.resolve_layer_spec", return_value=spec),
            patch("app.weatherengine.fetch_gateway.get_weather_cache_ttl_seconds", return_value=60),
        ):
            payload, status, used = fetch_point_forecast(
                layer_id="temperature",
                latitude=23.1,
                longitude=113.2,
                forecast_hours=6,
                provider_id=None,
            )

        assert used == "weatherapi"
        assert status == "miss"
        assert payload["current"]["temperature_2m"] == 1
        primary.fetch_point_forecast.assert_called_once()
        fallback.fetch_point_forecast.assert_called_once()

    def test_auto_no_fallback_preserves_upstream_error(self):
        from app.weatherengine.fetch_gateway import WeatherProviderUnavailableError

        primary = MagicMock()
        primary.provider_id = "open-meteo-online"
        primary.fetch_point_forecast.side_effect = RuntimeError("upstream down")
        spec = MagicMock()
        spec.pressure_levels = None

        with (
            patch(
                "app.weatherengine.fetch_gateway.resolve_provider_for_layer",
                side_effect=[primary, WeatherProviderUnavailableError("no fallback")],
            ),
            patch("app.weatherengine.fetch_gateway.resolve_layer_spec", return_value=spec),
            patch("app.weatherengine.fetch_gateway.get_weather_cache_ttl_seconds", return_value=60),
        ):
            with pytest.raises(RuntimeError, match="upstream down"):
                fetch_point_forecast(
                    layer_id="temperature",
                    latitude=23.1,
                    longitude=113.2,
                    forecast_hours=6,
                    provider_id=None,
                )

    def test_pinned_provider_does_not_fallback(self):
        primary = MagicMock()
        primary.provider_id = "weatherapi"
        primary.fetch_point_forecast.side_effect = RuntimeError("quota")
        spec = MagicMock()
        spec.pressure_levels = None

        with (
            patch(
                "app.weatherengine.fetch_gateway.resolve_provider_for_layer",
                return_value=primary,
            ),
            patch("app.weatherengine.fetch_gateway.resolve_layer_spec", return_value=spec),
            patch("app.weatherengine.fetch_gateway.get_weather_cache_ttl_seconds", return_value=60),
        ):
            with pytest.raises(RuntimeError, match="quota"):
                fetch_point_forecast(
                    layer_id="temperature",
                    latitude=23.1,
                    longitude=113.2,
                    forecast_hours=6,
                    provider_id="weatherapi",
                )