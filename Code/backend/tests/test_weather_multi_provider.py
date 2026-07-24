"""Multi-weather-provider: field mapping, pin/fallback, tile cache key."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shared.contracts.api_contracts import BoundingBox

from app.weatherengine.constants import WEATHER_LAYER_SPECS
from app.weatherengine.field_mapping import (
    COMMERCIAL_LAYER_IDS,
    apply_commercial_height_extrapolation,
    build_empty_pressure_grid,
    commercial_data_quality,
    extrapolate_wind_speed_power_law,
    kph_to_ms,
    openweather_current_to_om,
    weatherapi_current_to_om,
)
from app.weatherengine.fetch_gateway import (
    fetch_point_forecast,
    resolve_provider_for_layer,
)
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
        assert mapped["cloud_cover"] == 40

    def test_commercial_layer_ids_cover_catalog(self):
        assert COMMERCIAL_LAYER_IDS == frozenset(WEATHER_LAYER_SPECS)
        assert commercial_data_quality("temperature") == "observed"
        assert commercial_data_quality("wind-field-120m") == "extrapolated"
        assert commercial_data_quality("wind-field-500hPa") == "sparse"

    def test_power_law_wind_extrapolation(self):
        assert extrapolate_wind_speed_power_law(
            10.0, target_height_m=80.0
        ) == pytest.approx(10.0 * (8.0**0.14))
        payload = {
            "current": {
                "wind_speed_10m": 10.0,
                "wind_direction_10m": 90,
                "temperature_2m": 20.0,
            },
            "hourly": {
                "time": ["2024-01-01T00:00"],
                "wind_speed_10m": [10.0],
                "wind_direction_10m": [90],
                "temperature_2m": [20.0],
            },
        }
        apply_commercial_height_extrapolation(payload, "wind-field-80m")
        assert payload["data_quality"] == "extrapolated"
        assert payload["current"]["wind_speed_80m"] == pytest.approx(10.0 * (8.0**0.14))
        assert payload["current"]["wind_direction_80m"] == 90

        apply_commercial_height_extrapolation(payload, "temperature-120m")
        # Lapse-rate extrapolation: 20.0 + (120 - 2) * (-6.5/1000) = 19.233
        assert payload["current"]["temperature_120m"] == pytest.approx(19.233, abs=0.01)

    def test_ensure_hub_height_wind_fills_null_grid_arrays(self):
        from app.weatherengine.field_mapping import (
            ensure_hub_height_wind_in_grid_arrays,
        )

        current = {
            "wind_speed_80m": [None, None, None, None],
            "wind_direction_80m": [None, None, None, None],
            "wind_speed_10m": [10.0, 12.0, 8.0, 9.0],
            "wind_direction_10m": [90, 100, 80, 85],
        }
        hourly: dict = {
            "wind_speed_10m": [[10.0, 11.0], [12.0, 13.0], [8.0, 9.0], [9.0, 10.0]],
            "wind_direction_10m": [[90, 91], [100, 101], [80, 81], [85, 86]],
            "wind_speed_80m": [[None, None], [None, None], [None, None], [None, None]],
        }
        assert (
            ensure_hub_height_wind_in_grid_arrays(current, hourly, "wind-field-80m")
            is True
        )
        assert current["wind_speed_80m"][0] == pytest.approx(10.0 * (8.0**0.14))
        assert current["wind_direction_80m"][1] == 100
        assert hourly["wind_speed_80m"][0][0] == pytest.approx(10.0 * (8.0**0.14))
        assert hourly["wind_direction_80m"][1][1] == 101

    def test_ensure_hub_height_skips_when_native_present(self):
        from app.weatherengine.field_mapping import (
            ensure_hub_height_wind_in_grid_arrays,
        )

        current = {
            "wind_speed_80m": [15.0, 16.0],
            "wind_speed_10m": [10.0, 11.0],
        }
        hourly: dict = {}
        assert (
            ensure_hub_height_wind_in_grid_arrays(current, hourly, "wind-field-80m")
            is False
        )
        assert current["wind_speed_80m"] == [15.0, 16.0]

    def test_ensure_hub_height_temperature_fills_null_grid_arrays(self):
        from app.weatherengine.field_mapping import (
            ensure_hub_height_temperature_in_grid_arrays,
        )

        current = {
            "temperature_80m": [None, None, None],
            "temperature_2m": [20.0, 25.0, 30.0],
        }
        hourly: dict = {
            "temperature_2m": [[20.0, 21.0], [25.0, 26.0], [30.0, 31.0]],
            "temperature_80m": [[None, None], [None, None], [None, None]],
        }
        assert (
            ensure_hub_height_temperature_in_grid_arrays(
                current, hourly, "temperature-80m"
            )
            is True
        )
        # Lapse rate: 20.0 + (80 - 2) * (-6.5/1000) = 20.0 - 0.507 = 19.493
        assert current["temperature_80m"][0] == pytest.approx(19.493, abs=0.01)
        assert current["temperature_80m"][1] == pytest.approx(24.493, abs=0.01)
        assert hourly["temperature_80m"][0][0] == pytest.approx(19.493, abs=0.01)
        assert hourly["temperature_80m"][2][1] == pytest.approx(30.493, abs=0.01)

    def test_ensure_hub_height_temperature_skips_when_native_present(self):
        from app.weatherengine.field_mapping import (
            ensure_hub_height_temperature_in_grid_arrays,
        )

        current = {
            "temperature_80m": [19.0, 20.0],
            "temperature_2m": [25.0, 26.0],
        }
        hourly: dict = {}
        assert (
            ensure_hub_height_temperature_in_grid_arrays(
                current, hourly, "temperature-80m"
            )
            is False
        )
        assert current["temperature_80m"] == [19.0, 20.0]

    def test_empty_pressure_grid_marks_sparse(self):
        grid = build_empty_pressure_grid(
            bbox=BoundingBox(west=110.0, south=20.0, east=112.0, north=22.0),
            resolution=0.5,
            layer_spec=WEATHER_LAYER_SPECS["wind-field-850hPa"],
        )
        assert grid["data_quality"] == "sparse"
        assert grid["coverage"] == "sparse_unavailable"
        assert grid["grid"]["rows"] * grid["grid"]["cols"] >= 1


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

        with patch(
            "app.weatherengine.fetch_gateway.get_registry", return_value=registry
        ):
            with pytest.raises(ValueError, match="disabled"):
                resolve_provider_for_layer("wind-field", provider_id="weatherapi")

    def test_pin_requires_layer_support(self):
        provider = MagicMock()
        provider.provider_id = "weatherapi"
        provider.supports_layer.return_value = False
        registry = MagicMock()
        registry.get_provider.return_value = provider
        registry.is_enabled.return_value = True

        with patch(
            "app.weatherengine.fetch_gateway.get_registry", return_value=registry
        ):
            with pytest.raises(ValueError, match="does not support"):
                resolve_provider_for_layer("wind-field-80m", provider_id="weatherapi")


class TestFetchPointFallback:
    def test_auto_fallback_on_primary_failure(self):
        primary = MagicMock()
        primary.provider_id = "open-meteo-online"
        primary.fetch_point_forecast.side_effect = RuntimeError("upstream down")

        fallback = MagicMock()
        fallback.provider_id = "weatherapi"
        fallback.fetch_point_forecast.return_value = (
            {"current": {"temperature_2m": 1}},
            "miss",
        )

        spec = MagicMock()
        spec.pressure_levels = None

        with (
            patch(
                "app.weatherengine.fetch_gateway.resolve_provider_for_layer",
                side_effect=[primary, fallback],
            ),
            patch(
                "app.weatherengine.fetch_gateway.resolve_layer_spec", return_value=spec
            ),
            patch(
                "app.weatherengine.fetch_gateway.get_weather_cache_ttl_seconds",
                return_value=60,
            ),
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
            patch(
                "app.weatherengine.fetch_gateway.resolve_layer_spec", return_value=spec
            ),
            patch(
                "app.weatherengine.fetch_gateway.get_weather_cache_ttl_seconds",
                return_value=60,
            ),
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
            patch(
                "app.weatherengine.fetch_gateway.resolve_layer_spec", return_value=spec
            ),
            patch(
                "app.weatherengine.fetch_gateway.get_weather_cache_ttl_seconds",
                return_value=60,
            ),
        ):
            with pytest.raises(RuntimeError, match="quota"):
                fetch_point_forecast(
                    layer_id="temperature",
                    latitude=23.1,
                    longitude=113.2,
                    forecast_hours=6,
                    provider_id="weatherapi",
                )
