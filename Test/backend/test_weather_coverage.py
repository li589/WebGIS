"""Phase D1: weather coverage probe — unreachable / empty / timeout / success."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError


class WeatherCoverageProbePhaseDTests(unittest.TestCase):
    def setUp(self) -> None:
        import importlib

        self.wr = importlib.import_module("app.api.routers.weather_router")
        self.wr._COVERAGE_CACHE.clear()
        # C2：coverage 结果落 Redis（TTL 300s），测试间残留会污染后续用例，
        # 故 setUp 一并清除 Redis 中的 coverage 键，保证用例隔离。
        client = self.wr.get_redis_client()
        if client is not None:
            try:
                for _model in ("ecmwf_ifs025", "gfs_global"):
                    client.delete(self.wr._COVERAGE_REDIS_PREFIX + _model)
            except Exception:
                pass

    def test_unreachable(self) -> None:
        with patch.object(self.wr, "urlopen", side_effect=OSError("down")):
            cov, code = self.wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
        self.assertIsNone(cov)
        self.assertEqual(code, "local_unreachable")

    def test_timeout_as_unreachable(self) -> None:
        with patch.object(self.wr, "urlopen", side_effect=URLError("timed out")):
            cov, code = self.wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
        self.assertIsNone(cov)
        self.assertEqual(code, "local_unreachable")

    def test_model_empty(self) -> None:
        payload = {"hourly": {"time": [], "temperature_2m": []}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        with patch.object(self.wr, "urlopen", return_value=mock_resp):
            cov, code = self.wr._probe_local_open_meteo_coverage("gfs_global")
        self.assertIsNone(cov)
        self.assertEqual(code, "model_empty")

    def test_all_null_temps_model_empty(self) -> None:
        times = [f"2026-07-21T{h:02d}:00" for h in range(3)]
        payload = {"hourly": {"time": times, "temperature_2m": [None, None, None]}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        with patch.object(self.wr, "urlopen", return_value=mock_resp):
            cov, code = self.wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
        self.assertIsNone(cov)
        self.assertEqual(code, "model_empty")

    def test_success(self) -> None:
        times = [f"2026-07-21T{h:02d}:00" for h in range(4)]
        payload = {"hourly": {"time": times, "temperature_2m": [1.0, 2.0, 3.0, 4.0]}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        with patch.object(self.wr, "urlopen", return_value=mock_resp):
            cov, code = self.wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
        self.assertIsNone(code)
        assert cov is not None
        self.assertEqual(cov["hour_count"], 4)
        self.assertEqual(cov["valid_hour_count"], 4)

    def test_route_returns_503_on_unreachable(self) -> None:
        from fastapi import HTTPException

        with patch.object(
            self.wr,
            "_probe_local_open_meteo_coverage",
            return_value=(None, "local_unreachable"),
        ):
            with patch(
                "app.services.weather_engine_settings.get_effective_weather_default_model",
                return_value="ecmwf_ifs025",
            ):
                with self.assertRaises(HTTPException) as ctx:
                    self.wr.get_weather_coverage(model=None)
        self.assertEqual(ctx.exception.status_code, 503)
        detail = ctx.exception.detail
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail.get("code"), "local_unreachable")

    # ── R-1：invalidate 必须同时清 Redis coverage 键（读端 Redis 优先）──────

    def test_invalidate_noarg_deletes_all_redis_coverage_keys(self) -> None:
        client = MagicMock()
        with (
            patch.object(self.wr, "get_redis_client", return_value=client),
            patch.object(
                self.wr,
                "scan_keys",
                return_value=[
                    "weather:coverage:ecmwf_ifs025",
                    "weather:coverage:gfs_global",
                ],
            ),
        ):
            self.wr.invalidate_weather_coverage_cache()
        client.delete.assert_called_once()
        self.assertEqual(
            sorted(client.delete.call_args[0]),
            ["weather:coverage:ecmwf_ifs025", "weather:coverage:gfs_global"],
        )

    def test_invalidate_model_deletes_single_redis_key(self) -> None:
        client = MagicMock()
        with patch.object(self.wr, "get_redis_client", return_value=client):
            self.wr.invalidate_weather_coverage_cache("ecmwf_ifs025")
        client.delete.assert_called_once_with("weather:coverage:ecmwf_ifs025")
        # 带 model 分支按 key 删，不触发 scan
        client.reset_mock()
        with patch.object(self.wr, "get_redis_client", return_value=client):
            self.wr.invalidate_weather_coverage_cache("gfs_global")
        client.delete.assert_called_once_with("weather:coverage:gfs_global")


if __name__ == "__main__":
    unittest.main()
