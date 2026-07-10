from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from app.core.redis_client import get_redis_client
from app.weatherengine.client import OpenMeteoClient
from app.weatherengine.constants import WEATHER_LAYER_SPECS


def _flush_weather_redis_cache() -> None:
    """Clear weather-related keys from Redis to isolate tests from cache state."""
    client = get_redis_client()
    if client is None:
        return
    for key in client.scan_iter("weather:*"):
        client.delete(key)


class _FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class OpenMeteoClientTests(unittest.TestCase):
    def setUp(self) -> None:
        _flush_weather_redis_cache()

    def test_fetch_point_forecast_recreates_missing_cache_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = OpenMeteoClient(cache_root=tmpdir)
            cache_root = Path(tmpdir) / "weatherengine"
            self.assertTrue(cache_root.exists())

            # 模拟运行期间缓存目录被外部清理。
            cache_root.rmdir()
            self.assertFalse(cache_root.exists())

            payload = {
                "timezone": "Asia/Shanghai",
                "current": {
                    "time": "2026-07-05T10:00",
                    "wind_speed_10m": 8.2,
                    "wind_direction_10m": 155,
                },
                "hourly": {
                    "time": ["2026-07-05T10:00"],
                    "wind_speed_10m": [8.2],
                },
            }

            with patch("app.weatherengine.client.urlopen", return_value=_FakeHttpResponse(payload)):
                result, cache_status = client.fetch_point_forecast(
                    latitude=23.1291,
                    longitude=113.2644,
                    layer_spec=WEATHER_LAYER_SPECS["wind-field"],
                    model="best_match",
                    forecast_hours=6,
                    ttl_seconds=3600,
                )

            self.assertEqual(cache_status, "miss")
            self.assertEqual(result["current"]["wind_speed_10m"], 8.2)
            self.assertTrue(cache_root.exists())
            self.assertTrue(any(cache_root.glob("wind-field-*.json")))

    def test_fetch_point_forecast_uses_stale_cache_on_429(self) -> None:
        _flush_weather_redis_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            client = OpenMeteoClient(cache_root=tmpdir)
            cache_root = Path(tmpdir) / "weatherengine"
            cache_file = next(cache_root.glob("wind-field-*.json"), None)
            self.assertIsNone(cache_file)

            payload = {
                "timezone": "Asia/Shanghai",
                "current": {
                    "time": "2026-07-05T10:00",
                    "wind_speed_10m": 8.2,
                    "wind_direction_10m": 155,
                },
                "hourly": {
                    "time": ["2026-07-05T10:00"],
                    "wind_speed_10m": [8.2],
                },
            }

            with patch("app.weatherengine.client.urlopen", return_value=_FakeHttpResponse(payload)):
                client.fetch_point_forecast(
                    latitude=23.1291,
                    longitude=113.2644,
                    layer_spec=WEATHER_LAYER_SPECS["wind-field"],
                    model="best_match",
                    forecast_hours=6,
                    ttl_seconds=1,
                )

            cache_file = next(cache_root.glob("wind-field-*.json"))
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            cached["expires_at"] = "2000-01-01T00:00:00+00:00"
            cache_file.write_text(json.dumps(cached), encoding="utf-8")
            # Flush Redis so the 429 test falls back to stale file cache
            _flush_weather_redis_cache()

            http_error = HTTPError(
                url="https://api.open-meteo.com/v1/forecast",
                code=429,
                msg="Too Many Requests",
                hdrs=None,
                fp=None,
            )
            with patch("app.weatherengine.client.urlopen", side_effect=http_error):
                result, cache_status = client.fetch_point_forecast(
                    latitude=23.1291,
                    longitude=113.2644,
                    layer_spec=WEATHER_LAYER_SPECS["wind-field"],
                    model="best_match",
                    forecast_hours=6,
                    ttl_seconds=3600,
                )

            self.assertEqual(cache_status, "stale-hit")
            self.assertEqual(result["current"]["wind_speed_10m"], 8.2)


if __name__ == "__main__":
    unittest.main()
