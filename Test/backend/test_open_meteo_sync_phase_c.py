"""Phase C: Open-Meteo sync observability — last_sync, trigger domains, sync_unavailable."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.weather_engine_settings_repository import WeatherEngineSettingsRepository


class RecordOpenMeteoSyncResultTests(unittest.TestCase):
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

    def test_record_success_and_failure_preserve_counterpart(self) -> None:
        from app.services import weather_engine_settings as wes

        wes.record_open_meteo_sync_result(
            ok=True,
            domains="ecmwf_ifs025",
            message="ok",
            exit_code=0,
            stderr_tail="",
        )
        last = wes.get_last_sync_record()
        assert last is not None
        self.assertTrue(last["ok"])
        self.assertEqual(last["domains"], ["ecmwf_ifs025"])
        self.assertIsNotNone(last.get("last_success_at"))

        wes.record_open_meteo_sync_result(
            ok=False,
            domains=["gfs_global"],
            message="exit code 1",
            exit_code=1,
            stderr_tail="boom" * 1000,
        )
        last2 = wes.get_last_sync_record()
        assert last2 is not None
        self.assertFalse(last2["ok"])
        self.assertEqual(last2["domains"], ["gfs_global"])
        self.assertEqual(last2.get("last_success_at"), last.get("last_success_at"))
        self.assertLessEqual(len(last2.get("stderr_tail") or ""), 2000)

    def test_overview_exposes_sync_service_available(self) -> None:
        from app.services import weather_engine_settings as wes

        with (
            patch.object(wes, "probe_local_open_meteo_reachable", return_value=True),
            patch.object(wes.shutil, "which", return_value="/usr/bin/docker"),
            patch.object(Path, "is_file", return_value=True),
        ):
            overview = wes.get_weather_sync_overview()
        self.assertIn("sync_service_available", overview)
        self.assertTrue(overview["sync_service_available"])
        self.assertIn("last_success_at", overview)
        self.assertIn("last_failure_at", overview)


class OpenMeteoSyncTriggerApiTests(unittest.TestCase):
    def test_rejects_unsupported_domains(self) -> None:
        import importlib

        from fastapi import HTTPException

        wr = importlib.import_module("app.api.routers.weather_router")
        body = wr.OpenMeteoSyncTriggerRequest(domains="not_a_real_model")
        with self.assertRaises(HTTPException) as ctx:
            wr.trigger_open_meteo_sync(body)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_sync_unavailable_without_docker(self) -> None:
        import importlib

        from fastapi import HTTPException

        wr = importlib.import_module("app.api.routers.weather_router")
        body = wr.OpenMeteoSyncTriggerRequest()
        # shutil is imported inside the handler; patch the stdlib symbol.
        # 同时隔离互斥锁：真实环境可能有 Open-Meteo 同步正在运行（Redis 锁被持有），
        # 否则 C1 互斥检查会先返回 409，无法确定性验证 docker 缺失的 503 路径。
        with (
            patch("shutil.which", return_value=None),
            patch(
                "app.tasks.open_meteo_sync_tasks.is_open_meteo_sync_locked",
                return_value=False,
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                wr.trigger_open_meteo_sync(body)
        self.assertEqual(ctx.exception.status_code, 503)
        detail = ctx.exception.detail
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail.get("code"), "sync_unavailable")

    def test_execute_accepts_domains_override(self) -> None:
        from app.tasks import open_meteo_sync_tasks as tasks

        fake = MagicMock()
        fake.returncode = 0
        fake.stdout = "ok"
        fake.stderr = ""
        with (
            patch.object(tasks, "_ensure_sync_volume"),
            patch.object(tasks.subprocess, "run", return_value=fake) as run,
            patch(
                "app.services.weather_engine_settings.record_open_meteo_sync_result"
            ) as record,
        ):
            result = tasks.execute_open_meteo_sync(domains="gfs_global")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["domains"], "gfs_global")
        cmd = run.call_args.args[0]
        self.assertIn("gfs_global", cmd)
        record.assert_called()
        kwargs = record.call_args.kwargs
        self.assertTrue(kwargs.get("ok"))
        self.assertEqual(kwargs.get("domains"), "gfs_global")


if __name__ == "__main__":
    unittest.main()
