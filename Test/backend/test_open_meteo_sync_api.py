"""Phase D2: Open-Meteo sync API — overview, trigger domains, model PUT."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.weather_engine_settings_repository import WeatherEngineSettingsRepository


class OpenMeteoSyncApiPhaseDTests(unittest.TestCase):
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

    def test_overview_has_last_and_service_flags(self) -> None:
        from app.services import weather_engine_settings as wes

        wes.record_open_meteo_sync_result(
            ok=True, domains="ecmwf_ifs025", message="ok", exit_code=0
        )
        with (
            patch.object(wes, "probe_local_open_meteo_reachable", return_value=True),
            patch("shutil.which", return_value="docker"),
        ):
            overview = wes.get_weather_sync_overview()
        self.assertTrue(overview.get("last_ok"))
        self.assertIsNotNone(overview.get("last_success_at"))
        self.assertIn("sync_service_available", overview)
        self.assertIn("docker_cli_available", overview)
        self.assertIn("compose_file_exists", overview)

    def test_model_put_warning_not_in_sync_domains(self) -> None:
        from app.services import weather_engine_settings as wes

        with patch.object(wes, "parse_sync_domains", return_value=["ecmwf_ifs025"]):
            result = wes.set_weather_default_model("gfs_global")
        self.assertEqual(result["default_model"], "gfs_global")
        self.assertEqual(result.get("warning"), "not_in_sync_domains")

    def test_trigger_rejects_bad_domains(self) -> None:
        import importlib

        from fastapi import HTTPException

        wr = importlib.import_module("app.api.routers.weather_router")
        body = wr.OpenMeteoSyncTriggerRequest(domains="nope_model")
        with self.assertRaises(HTTPException) as ctx:
            wr.trigger_open_meteo_sync(body)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_trigger_503_when_docker_missing(self) -> None:
        import importlib

        from fastapi import HTTPException

        wr = importlib.import_module("app.api.routers.weather_router")
        with (
            patch("shutil.which", return_value=None),
            patch(
                "app.tasks.open_meteo_sync_tasks.is_open_meteo_sync_locked",
                return_value=False,
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                wr.trigger_open_meteo_sync(wr.OpenMeteoSyncTriggerRequest())
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail.get("code"), "sync_unavailable")


if __name__ == "__main__":
    unittest.main()
