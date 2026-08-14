"""Phase D2: Open-Meteo sync API — overview, trigger domains, model PUT."""

from __future__ import annotations

import pytest
import types
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.services.weather_engine_settings_repository import WeatherEngineSettingsRepository


@pytest.fixture
def _open_meteo_sync_api_phase_d_tests_env():
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


def test_overview_has_last_and_service_flags(_open_meteo_sync_api_phase_d_tests_env) -> None:
    self = _open_meteo_sync_api_phase_d_tests_env
    from app.services import weather_engine_settings as wes

    wes.record_open_meteo_sync_result(
        ok=True, domains="ecmwf_ifs025", message="ok", exit_code=0
    )
    with (
        patch.object(wes, "probe_local_open_meteo_reachable", return_value=True),
        patch("shutil.which", return_value="docker"),
    ):
        overview = wes.get_weather_sync_overview()
    assert overview.get("last_ok"), 'overview.get("last_ok") is truthy'
    assert overview.get("last_success_at") is not None, 'overview.get("last_success_at") is not None'
    assert "sync_service_available" in overview, '"sync_service_available" in overview'
    assert "docker_cli_available" in overview, '"docker_cli_available" in overview'
    assert "compose_file_exists" in overview, '"compose_file_exists" in overview'


def test_model_put_warning_not_in_sync_domains(_open_meteo_sync_api_phase_d_tests_env) -> None:
    self = _open_meteo_sync_api_phase_d_tests_env
    from app.services import weather_engine_settings as wes

    with patch.object(wes, "parse_sync_domains", return_value=["ecmwf_ifs025"]):
        result = wes.set_weather_default_model("gfs_global")
    assert result["default_model"] == "gfs_global", 'result["default_model"] == "gfs_global"'
    assert result.get("warning") == "not_in_sync_domains", 'result.get("warning") == "not_in_sync_domains"'


def test_trigger_rejects_bad_domains(_open_meteo_sync_api_phase_d_tests_env) -> None:
    self = _open_meteo_sync_api_phase_d_tests_env
    import importlib

    from fastapi import HTTPException

    wr = importlib.import_module("app.api.routers.weather_router")
    body = wr.OpenMeteoSyncTriggerRequest(domains="nope_model")
    with pytest.raises(HTTPException) as ctx:
        wr.trigger_open_meteo_sync(body)
    assert ctx.value.status_code == 400, 'ctx.exception.status_code == 400'


def test_trigger_503_when_docker_missing(_open_meteo_sync_api_phase_d_tests_env) -> None:
    self = _open_meteo_sync_api_phase_d_tests_env
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
        with pytest.raises(HTTPException) as ctx:
            wr.trigger_open_meteo_sync(wr.OpenMeteoSyncTriggerRequest())
    assert ctx.value.status_code == 503, 'ctx.exception.status_code == 503'
    assert ctx.value.detail.get("code") == "sync_unavailable", 'ctx.exception.detail.get("code") == "sync_unavailable"'
