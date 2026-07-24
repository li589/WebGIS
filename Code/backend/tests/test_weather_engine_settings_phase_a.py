"""Phase A: weather default_model DB + coverage probe + sync overview."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.weather_engine_settings_repository import (
    KEY_DEFAULT_MODEL,
    WeatherEngineSettingsRepository,
)
from app.weatherengine.supported_models import is_supported_weather_model


class WeatherEngineSettingsRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "weather_engine.sqlite3"
        self.repo = WeatherEngineSettingsRepository(self.db_path)

    def tearDown(self) -> None:
        self.repo.close()
        self._tmpdir.cleanup()

    def test_set_get_default_model(self) -> None:
        self.assertIsNone(self.repo.get(KEY_DEFAULT_MODEL))
        self.repo.set(KEY_DEFAULT_MODEL, "gfs_global")
        self.assertEqual(self.repo.get(KEY_DEFAULT_MODEL), "gfs_global")

    def test_set_get_json(self) -> None:
        self.repo.set_json("last_sync", {"ok": True, "domains": ["ecmwf_ifs025"]})
        data = self.repo.get_json("last_sync")
        self.assertIsNotNone(data)
        assert data is not None
        self.assertTrue(data["ok"])
        self.assertEqual(data["domains"], ["ecmwf_ifs025"])


class WeatherEngineSettingsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "weather_engine.sqlite3"
        self.repo = WeatherEngineSettingsRepository(self.db_path)
        import app.services.weather_engine_settings as wes

        wes._effective_model_cache = None
        self._repo_patch = patch.object(wes, "_get_repo", return_value=self.repo)
        self._repo_patch.start()

    def tearDown(self) -> None:
        self._repo_patch.stop()
        import app.services.weather_engine_settings as wes

        wes._effective_model_cache = None
        self.repo.close()
        self._tmpdir.cleanup()

    def test_set_and_get_effective_model(self) -> None:
        from app.services import weather_engine_settings as wes

        wes._effective_model_cache = None
        result = wes.set_weather_default_model("icon_global")
        self.assertEqual(result["default_model"], "icon_global")
        wes._effective_model_cache = None
        self.assertEqual(wes.get_effective_weather_default_model(), "icon_global")

    def test_reject_unknown_model(self) -> None:
        from app.services import weather_engine_settings as wes

        with self.assertRaises(ValueError):
            wes.set_weather_default_model("not_a_real_model")

    def test_warning_when_not_in_sync_domains(self) -> None:
        from app.services import weather_engine_settings as wes

        with patch.object(wes, "parse_sync_domains", return_value=["ecmwf_ifs025"]):
            result = wes.set_weather_default_model("gfs_global")
            self.assertEqual(result.get("warning"), "not_in_sync_domains")

    def test_supported_model_helper(self) -> None:
        self.assertTrue(is_supported_weather_model("ecmwf_ifs025"))
        self.assertFalse(is_supported_weather_model("nope"))


class WeatherCoverageProbeTests(unittest.TestCase):
    def test_unreachable(self) -> None:
        import importlib

        wr = importlib.import_module("app.api.routers.weather_router")
        wr._COVERAGE_CACHE.clear()
        with patch.object(wr, "urlopen", side_effect=OSError("down")):
            cov, code = wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
        self.assertIsNone(cov)
        self.assertEqual(code, "local_unreachable")

    def test_model_empty_no_times(self) -> None:
        import importlib

        wr = importlib.import_module("app.api.routers.weather_router")
        wr._COVERAGE_CACHE.clear()
        payload = {"hourly": {"time": [], "temperature_2m": []}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        with patch.object(wr, "urlopen", return_value=mock_resp):
            cov, code = wr._probe_local_open_meteo_coverage("gfs_global")
        self.assertIsNone(cov)
        self.assertEqual(code, "model_empty")

    def test_success_cached(self) -> None:
        import importlib

        wr = importlib.import_module("app.api.routers.weather_router")
        wr._COVERAGE_CACHE.clear()
        times = [f"2026-07-21T{h:02d}:00" for h in range(6)]
        payload = {"hourly": {"time": times, "temperature_2m": [20.0] * 6}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        with patch.object(wr, "urlopen", return_value=mock_resp) as mocked:
            cov1, code1 = wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
            cov2, code2 = wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
        self.assertIsNone(code1)
        self.assertIsNone(code2)
        self.assertEqual(cov1["hour_count"], 6)
        self.assertEqual(cov1["valid_hour_count"], 6)
        self.assertEqual(cov1["valid_times"], times)
        self.assertEqual(cov2["model"], "ecmwf_ifs025")
        self.assertEqual(mocked.call_count, 1)

    def test_valid_times_skips_null_temps(self) -> None:
        import importlib

        wr = importlib.import_module("app.api.routers.weather_router")
        wr._COVERAGE_CACHE.clear()
        times = [f"2026-07-21T{h:02d}:00" for h in range(4)]
        payload = {
            "hourly": {
                "time": times,
                "temperature_2m": [20.0, None, 21.0, None],
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        with patch.object(wr, "urlopen", return_value=mock_resp):
            cov, code = wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
        self.assertIsNone(code)
        assert cov is not None
        self.assertEqual(cov["valid_times"], [times[0], times[2]])
        self.assertEqual(cov["valid_hour_count"], 2)
        self.assertEqual(cov["data_end_iso"], times[2])


class WeatherSyncOverviewTests(unittest.TestCase):
    def test_overview_shape(self) -> None:
        from app.services import weather_engine_settings as wes

        tmp = tempfile.TemporaryDirectory()
        repo = WeatherEngineSettingsRepository(Path(tmp.name) / "t.sqlite3")
        try:
            with patch.object(wes, "_get_repo", return_value=repo):
                with patch.object(
                    wes, "probe_local_open_meteo_reachable", return_value=False
                ):
                    overview = wes.get_weather_sync_overview()
            self.assertIn("domains", overview)
            self.assertIn("local_reachable", overview)
            self.assertIn("enabled", overview)
            self.assertIn("cron", overview)
            self.assertIn("variables", overview)
            self.assertIn("data_mode", overview)
            self.assertEqual(overview["data_mode"], "forecast")
            self.assertIn("spatial", overview)
            self.assertIn("temporal", overview)
            self.assertIn("models_meta", overview)
            self.assertFalse(overview["local_reachable"])
        finally:
            repo.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
