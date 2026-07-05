from __future__ import annotations

from datetime import datetime, timezone
import unittest

from app.weatherengine.constants import WEATHER_LAYER_SPECS
from app.weatherengine.service import WeatherEngineService
from shared.contracts.api_contracts import ResultKind, RuntimeMapContext, WorkflowCommandType, WorkflowSubmitRequest


class _FakeOpenMeteoClient:
    def fetch_point_forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        layer_spec,
        model: str,
        forecast_hours: int,
        ttl_seconds: int,
    ):
        return (
            {
                "timezone": "Asia/Shanghai",
                "current": {
                    "time": "2026-07-05T10:00",
                    "temperature_2m": 30.5,
                    "apparent_temperature": 34.2,
                    "precipitation": 1.4,
                    "wind_speed_10m": 8.2,
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
                    "wind_speed_10m": [8.2, 7.9, 7.3],
                },
            },
            "hit",
        )


class WeatherEngineServiceTests(unittest.TestCase):
    def test_get_point_weather_builds_contract(self) -> None:
        service = WeatherEngineService(client=_FakeOpenMeteoClient())

        weather = service.get_point_weather(
            layer_id="wind-field",
            latitude=23.1291,
            longitude=113.2644,
            model="best_match",
            forecast_hours=3,
            place_name="Guangzhou",
        )

        self.assertEqual(weather.provider, "open-meteo")
        self.assertEqual(weather.layer_id, "wind-field")
        self.assertEqual(weather.place_name, "Guangzhou")
        self.assertEqual(weather.cache_status, "hit")
        self.assertEqual(weather.render_hint.primary_metric, WEATHER_LAYER_SPECS["wind-field"].primary_metric)
        self.assertEqual(weather.render_hint.paint_mode, WEATHER_LAYER_SPECS["wind-field"].paint_mode)
        self.assertAlmostEqual(weather.render_hint.opacity, WEATHER_LAYER_SPECS["wind-field"].default_opacity)
        self.assertEqual(len(weather.hourly), 3)
        self.assertAlmostEqual(weather.current.wind_speed_10m or 0.0, 8.2)

    def test_execute_returns_workflow_outputs(self) -> None:
        service = WeatherEngineService(client=_FakeOpenMeteoClient())
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
        service = WeatherEngineService(client=_FakeOpenMeteoClient())
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

    def test_execute_wind_returns_point_symbol_geojson_asset(self) -> None:
        service = WeatherEngineService(client=_FakeOpenMeteoClient())
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
        self.assertEqual(render_hint.get("paint_mode"), "point_symbol")
        self.assertTrue(layer_assets.get("geojson_url"))


if __name__ == "__main__":
    unittest.main()
