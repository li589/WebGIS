from __future__ import annotations

from datetime import datetime, timezone
import unittest

from app.weatherengine.constants import WEATHER_LAYER_SPECS
from app.weatherengine.service import WeatherEngineService
from app.weatherengine.provider_registry import get_registry
from app.weatherengine.providers.open_meteo_provider import OpenMeteoProvider
from shared.contracts.api_contracts import ResultKind, RuntimeMapContext, WorkflowCommandType, WorkflowSubmitRequest


class _FakeOpenMeteoClient:
    def __init__(self) -> None:
        self.grid_calls: list[str] = []

    def fetch_point_forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        layer_spec,
        model: str,
        forecast_hours: int,
        ttl_seconds: int,
        pressure_levels: tuple[int, ...] | None = None,
    ):
        return (
            {
                "timezone": "Asia/Shanghai",
                "current": {
                    "time": "2026-07-05T10:00",
                    "temperature_2m": 30.5,
                    "apparent_temperature": 34.2,
                    "precipitation": 1.4,
                    "relative_humidity_2m": 81.0,
                    "visibility": 12000.0,
                    "wind_speed_10m": 8.2,
                    "wind_speed_80m": 10.6,
                    "wind_direction_10m": 155,
                    "wind_gusts_10m": 12.6,
                    "cloud_cover": 72,
                },
                "hourly": {
                    "time": [
                        "2026-07-05T10:00",
                        "2026-07-05T11:00",
                        "2026-07-05T12:00",
                    ],
                    "temperature_2m": [30.5, 31.0, 31.6],
                    "precipitation": [1.4, 0.8, 0.1],
                    "relative_humidity_2m": [81.0, 79.0, 76.0],
                    "visibility": [12000.0, 11800.0, 11600.0],
                    "wind_speed_10m": [8.2, 7.9, 7.3],
                    "wind_speed_80m": [10.6, 10.2, 9.8],
                },
            },
            "hit",
        )

    def fetch_grid_forecast(
        self,
        *,
        bbox,
        resolution: float,
        layer_spec,
        model: str,
        ttl_seconds: int,
        pressure_levels: tuple[int, ...] | None = None,
    ):
        self.grid_calls.append(layer_spec.layer_id)
        return (
            {
                "grid": {
                    "bbox": {
                        "west": bbox.west,
                        "south": bbox.south,
                        "east": bbox.east,
                        "north": bbox.north,
                    },
                    "rows": 2,
                    "cols": 2,
                    "resolution": resolution,
                    "lats": [bbox.south + 0.25, bbox.south + 0.75],
                    "lons": [bbox.west + 0.25, bbox.west + 0.75],
                },
                "data": {
                    "current": {
                        "temperature_2m": [26.1, 27.4, 28.2, 29.0],
                        "precipitation": [0.3, 1.1, 2.4, 0.8],
                        "relative_humidity_2m": [65.0, 72.0, 78.0, 81.0],
                        "pressure_msl": [1008.5, 1009.1, 1010.2, 1011.4],
                        "visibility": [9000.0, 8500.0, 7800.0, 7200.0],
                    }
                },
            },
            "hit",
        )


class WeatherEngineServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        # 注册带 fake client 的 OpenMeteoProvider，供 get_point_weather 通过 registry 路由
        # （get_point_weather 不再使用 self._client，而是通过 provider registry 获取 provider）
        registry = get_registry()
        registry.register(
            OpenMeteoProvider(client=_FakeOpenMeteoClient()),
            priority=0,
            enabled=True,
        )

    def tearDown(self) -> None:
        get_registry().clear()

    def test_get_point_weather_builds_contract(self) -> None:
        service = WeatherEngineService()

        weather = service.get_point_weather(
            layer_id="wind-field",
            latitude=23.1291,
            longitude=113.2644,
            model="best_match",
            forecast_hours=3,
            place_name="Guangzhou",
        )

        self.assertEqual(weather.provider, "open-meteo-online")
        self.assertEqual(weather.layer_id, "wind-field")
        self.assertEqual(weather.place_name, "Guangzhou")
        self.assertEqual(weather.cache_status, "hit")
        self.assertEqual(weather.render_hint.primary_metric, WEATHER_LAYER_SPECS["wind-field"].primary_metric)
        self.assertEqual(weather.render_hint.paint_mode, WEATHER_LAYER_SPECS["wind-field"].paint_mode)
        self.assertAlmostEqual(weather.render_hint.opacity, WEATHER_LAYER_SPECS["wind-field"].default_opacity)
        self.assertEqual(len(weather.hourly), 3)
        self.assertAlmostEqual(weather.current.wind_speed_10m or 0.0, 8.2)
        self.assertEqual(weather.hourly[0].primary_metric, "wind_speed_10m")
        self.assertAlmostEqual(weather.hourly[0].primary_value or 0.0, 8.2)

    def test_get_point_weather_exposes_layer_primary_metric_in_hourly_rows(self) -> None:
        service = WeatherEngineService()

        weather = service.get_point_weather(
            layer_id="humidity",
            latitude=23.1291,
            longitude=113.2644,
            model="best_match",
            forecast_hours=3,
            place_name="Guangzhou",
        )

        self.assertEqual(weather.render_hint.primary_metric, "relative_humidity_2m")
        self.assertEqual(weather.hourly[0].primary_metric, "relative_humidity_2m")
        self.assertAlmostEqual(weather.hourly[0].primary_value or 0.0, 81.0)

    def test_execute_returns_workflow_outputs(self) -> None:
        service = WeatherEngineService()
        payload = WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            layer_id="temperature",
            requested_outputs=[ResultKind.json, ResultKind.text, ResultKind.table, ResultKind.map_layer],
            parameters={
                "latitude": 23.1291,
                "longitude": 113.2644,
                "place_name": "Guangzhou",
                "forecast_hours": 3,
            },
            map_context=RuntimeMapContext(active_layer_id="temperature"),
        )

        execution = service.execute(
            run_id="run-weather-1",
            payload=payload,
            requested_at=datetime.now(timezone.utc),
            event_factory=lambda **kwargs: kwargs,
        )

        self.assertIn("Open-Meteo", execution.message)
        self.assertEqual(execution.result_dto["workflow_entry_name"], "weatherengine.open_meteo_point")
        self.assertEqual(execution.result_dto["layer_id"], "temperature")
        self.assertGreaterEqual(len(execution.result_refs), 5)
        result_kinds = [result.result_kind for result in execution.result_refs]
        self.assertEqual(result_kinds[0], ResultKind.json)
        self.assertIn(ResultKind.file, result_kinds)
        self.assertEqual(result_kinds[-1], ResultKind.map_layer)
        map_layer_ref = execution.result_refs[-1]
        self.assertIn("layer_assets", map_layer_ref.inline_data or {})
        self.assertIn("render_hint", map_layer_ref.inline_data or {})

    def test_execute_precipitation_returns_geojson_asset(self) -> None:
        client = _FakeOpenMeteoClient()
        get_registry().register(OpenMeteoProvider(client=client), priority=0, enabled=True)
        service = WeatherEngineService()
        payload = WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            layer_id="precipitation",
            requested_outputs=[ResultKind.json, ResultKind.map_layer],
            parameters={
                "latitude": 23.1291,
                "longitude": 113.2644,
                "place_name": "Guangzhou",
                "forecast_hours": 3,
            },
            map_context=RuntimeMapContext(active_layer_id="precipitation"),
        )

        execution = service.execute(
            run_id="run-weather-precip-1",
            payload=payload,
            requested_at=datetime.now(timezone.utc),
            event_factory=lambda **kwargs: kwargs,
        )

        self.assertEqual(execution.result_dto["layer_id"], "precipitation")
        map_layer_ref = execution.result_refs[-1]
        inline_data = map_layer_ref.inline_data or {}
        layer_assets = inline_data.get("layer_assets") or {}
        self.assertTrue(layer_assets.get("geojson_url"))
        self.assertTrue(layer_assets.get("cog_url"))
        self.assertGreaterEqual(client.grid_calls.count("precipitation"), 2)

    def test_execute_wind_returns_point_symbol_geojson_asset(self) -> None:
        service = WeatherEngineService()
        payload = WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            layer_id="wind-field",
            requested_outputs=[ResultKind.json, ResultKind.map_layer],
            parameters={
                "latitude": 23.1291,
                "longitude": 113.2644,
                "place_name": "Guangzhou",
                "forecast_hours": 3,
            },
            map_context=RuntimeMapContext(active_layer_id="wind-field"),
        )

        execution = service.execute(
            run_id="run-weather-wind-1",
            payload=payload,
            requested_at=datetime.now(timezone.utc),
            event_factory=lambda **kwargs: kwargs,
        )

        self.assertEqual(execution.result_dto["layer_id"], "wind-field")
        map_layer_ref = execution.result_refs[-1]
        inline_data = map_layer_ref.inline_data or {}
        render_hint = inline_data.get("render_hint") or {}
        layer_assets = inline_data.get("layer_assets") or {}
        self.assertEqual(render_hint.get("paint_mode"), "particle_flow")
        self.assertTrue(layer_assets.get("geojson_url"))

    def test_execute_scalar_layers_use_grid_fetch_in_fallback(self) -> None:
        for layer_id in ("temperature", "humidity", "pressure", "visibility"):
            client = _FakeOpenMeteoClient()
            get_registry().register(OpenMeteoProvider(client=client), priority=0, enabled=True)
            service = WeatherEngineService()
            payload = WorkflowSubmitRequest(
                command_type=WorkflowCommandType.analysis,
                layer_id=layer_id,
                requested_outputs=[ResultKind.json, ResultKind.map_layer],
                parameters={
                    "latitude": 23.1291,
                    "longitude": 113.2644,
                    "place_name": "Guangzhou",
                    "forecast_hours": 3,
                },
                map_context=RuntimeMapContext(active_layer_id=layer_id),
            )

            execution = service.execute(
                run_id=f"run-weather-{layer_id}",
                payload=payload,
                requested_at=datetime.now(timezone.utc),
                event_factory=lambda **kwargs: kwargs,
            )

            self.assertEqual(execution.result_dto["layer_id"], layer_id)
            self.assertIn(layer_id, client.grid_calls)

    def test_execute_temperature_uses_grid_for_geojson_and_cog(self) -> None:
        client = _FakeOpenMeteoClient()
        get_registry().register(OpenMeteoProvider(client=client), priority=0, enabled=True)
        service = WeatherEngineService()
        payload = WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            layer_id="temperature",
            requested_outputs=[ResultKind.json, ResultKind.map_layer],
            parameters={
                "latitude": 23.1291,
                "longitude": 113.2644,
                "place_name": "Guangzhou",
                "forecast_hours": 3,
            },
            map_context=RuntimeMapContext(active_layer_id="temperature"),
        )

        execution = service.execute(
            run_id="run-weather-temperature-grid",
            payload=payload,
            requested_at=datetime.now(timezone.utc),
            event_factory=lambda **kwargs: kwargs,
        )

        map_layer_ref = execution.result_refs[-1]
        layer_assets = (map_layer_ref.inline_data or {}).get("layer_assets") or {}
        self.assertTrue(layer_assets.get("geojson_url"))
        self.assertTrue(layer_assets.get("cog_url"))
        self.assertGreaterEqual(client.grid_calls.count("temperature"), 2)


if __name__ == "__main__":
    unittest.main()
