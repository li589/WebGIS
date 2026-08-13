"""Phase C: Open-Meteo sync observability — last_sync, trigger domains, sync_unavailable."""

from __future__ import annotations

import pytest
import types
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.weather_engine_settings_repository import WeatherEngineSettingsRepository


@pytest.fixture
def _record_open_meteo_sync_result_tests_env():
    ns = types.SimpleNamespace()
    ns._tmpdir = tempfile.TemporaryDirectory()
    ns.db_path = Path(ns._tmpdir.name) / "weather_engine.sqlite3"
    ns.repo = WeatherEngineSettingsRepository(ns.db_path)
    import app.services.weather_engine_settings as wes

    wes._effective_model_cache = None
    ns._repo_patch = patch.object(wes, "_get_repo", return_value=ns.repo)
    ns._repo_patch.start()
    yield ns
    ns._repo_patch.stop()
    import app.services.weather_engine_settings as wes

    wes._effective_model_cache = None
    ns.repo.close()
    ns._tmpdir.cleanup()


def test_record_success_and_failure_preserve_counterpart(_record_open_meteo_sync_result_tests_env) -> None:
    self = _record_open_meteo_sync_result_tests_env
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
    assert last["ok"], 'last["ok"] is truthy'
    assert last["domains"] == ["ecmwf_ifs025"], 'last["domains"] == ["ecmwf_ifs025"]'
    assert last.get("last_success_at") is not None, 'last.get("last_success_at") is not None'

    wes.record_open_meteo_sync_result(
        ok=False,
        domains=["gfs_global"],
        message="exit code 1",
        exit_code=1,
        stderr_tail="boom" * 1000,
    )
    last2 = wes.get_last_sync_record()
    assert last2 is not None
    assert not last2["ok"], 'last2["ok"] is falsy'
    assert last2["domains"] == ["gfs_global"], 'last2["domains"] == ["gfs_global"]'
    assert last2.get("last_success_at") == last.get("last_success_at"), 'last2.get("last_success_at") == last.get("last_success_at")'
    assert len(last2.get("stderr_tail") or "") <= 2000, 'len(last2.get("stderr_tail") or "") <= 2000'


def test_overview_exposes_sync_service_available(_record_open_meteo_sync_result_tests_env) -> None:
    self = _record_open_meteo_sync_result_tests_env
    from app.services import weather_engine_settings as wes

    with (
        patch.object(wes, "probe_local_open_meteo_reachable", return_value=True),
        patch.object(wes.shutil, "which", return_value="/usr/bin/docker"),
        patch.object(Path, "is_file", return_value=True),
    ):
        overview = wes.get_weather_sync_overview()
    assert "sync_service_available" in overview, '"sync_service_available" in overview'
    assert overview["sync_service_available"], 'overview["sync_service_available"] is truthy'
    assert "last_success_at" in overview, '"last_success_at" in overview'
    assert "last_failure_at" in overview, '"last_failure_at" in overview'


def test_rejects_unsupported_domains() -> None:
    import importlib

    from fastapi import HTTPException

    wr = importlib.import_module("app.api.routers.weather_router")
    body = wr.OpenMeteoSyncTriggerRequest(domains="not_a_real_model")
    with pytest.raises(HTTPException) as ctx:
        wr.trigger_open_meteo_sync(body)
    assert ctx.value.status_code == 400, 'ctx.exception.status_code == 400'


def test_sync_unavailable_without_docker() -> None:
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
        with pytest.raises(HTTPException) as ctx:
            wr.trigger_open_meteo_sync(body)
    assert ctx.value.status_code == 503, 'ctx.exception.status_code == 503'
    detail = ctx.value.detail
    assert isinstance(detail, dict), 'isinstance(detail, dict)'
    assert detail.get("code") == "sync_unavailable", 'detail.get("code") == "sync_unavailable"'


def test_execute_accepts_domains_override() -> None:
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
    assert result["status"] == "succeeded", 'result["status"] == "succeeded"'
    assert result["domains"] == "gfs_global", 'result["domains"] == "gfs_global"'
    cmd = run.call_args.args[0]
    assert "gfs_global" in cmd, '"gfs_global" in cmd'
    record.assert_called()
    kwargs = record.call_args.kwargs
    assert kwargs.get("ok"), 'kwargs.get("ok") is truthy'
    assert kwargs.get("domains") == "gfs_global", 'kwargs.get("domains") == "gfs_global"'
