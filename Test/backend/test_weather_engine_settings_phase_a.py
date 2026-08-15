"""Phase A: weather default_model DB + coverage probe + sync overview."""

from __future__ import annotations

import pytest
import types
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.weather_engine_settings_repository import (
    KEY_DEFAULT_MODEL,
    WeatherEngineSettingsRepository,
)
from app.weatherengine.supported_models import is_supported_weather_model


@pytest.fixture
def _weather_engine_settings_repository_tests_env():
    ns = types.SimpleNamespace()
    ns._tmpdir = tempfile.TemporaryDirectory()
    ns.db_path = Path(ns._tmpdir.name) / "weather_engine.sqlite3"
    ns.repo = WeatherEngineSettingsRepository(ns.db_path)
    yield ns
    ns.repo.close()
    ns._tmpdir.cleanup()


def test_set_get_default_model(_weather_engine_settings_repository_tests_env) -> None:
    self = _weather_engine_settings_repository_tests_env
    assert self.repo.get(KEY_DEFAULT_MODEL) is None, 'self.repo.get(KEY_DEFAULT_MODEL) is None'
    self.repo.set(KEY_DEFAULT_MODEL, "gfs_global")
    assert self.repo.get(KEY_DEFAULT_MODEL) == "gfs_global", 'self.repo.get(KEY_DEFAULT_MODEL) == "gfs_global"'


def test_set_get_json(_weather_engine_settings_repository_tests_env) -> None:
    self = _weather_engine_settings_repository_tests_env
    self.repo.set_json("last_sync", {"ok": True, "domains": ["ecmwf_ifs025"]})
    data = self.repo.get_json("last_sync")
    assert data is not None, 'data is not None'
    assert data is not None
    assert data["ok"], 'data["ok"] is truthy'
    assert data["domains"] == ["ecmwf_ifs025"], 'data["domains"] == ["ecmwf_ifs025"]'


@pytest.fixture
def _weather_engine_settings_service_tests_env():
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


def test_set_and_get_effective_model(_weather_engine_settings_service_tests_env) -> None:
    self = _weather_engine_settings_service_tests_env
    from app.services import weather_engine_settings as wes

    wes._effective_model_cache = None
    result = wes.set_weather_default_model("icon_global")
    assert result["default_model"] == "icon_global", 'result["default_model"] == "icon_global"'
    wes._effective_model_cache = None
    assert wes.get_effective_weather_default_model() == "icon_global", 'wes.get_effective_weather_default_model() == "icon_global"'


def test_reject_unknown_model(_weather_engine_settings_service_tests_env) -> None:
    self = _weather_engine_settings_service_tests_env
    from app.services import weather_engine_settings as wes

    with pytest.raises(ValueError):
        wes.set_weather_default_model("not_a_real_model")


def test_warning_when_not_in_sync_domains(_weather_engine_settings_service_tests_env) -> None:
    self = _weather_engine_settings_service_tests_env
    from app.services import weather_engine_settings as wes

    with patch.object(wes, "parse_sync_domains", return_value=["ecmwf_ifs025"]):
        result = wes.set_weather_default_model("gfs_global")
        assert result.get("warning") == "not_in_sync_domains", 'result.get("warning") == "not_in_sync_domains"'


def test_supported_model_helper(_weather_engine_settings_service_tests_env) -> None:
    self = _weather_engine_settings_service_tests_env
    assert is_supported_weather_model("ecmwf_ifs025"), 'is_supported_weather_model("ecmwf_ifs025") is truthy'
    assert not is_supported_weather_model("nope"), 'is_supported_weather_model("nope") is falsy'


@pytest.fixture
def _weather_coverage_probe_tests_env():
    ns = types.SimpleNamespace()
    import importlib

    from app.services import weather_coverage_cache

    wr = importlib.import_module("app.api.routers.weather_router")
    wr._COVERAGE_CACHE.clear()
    # C2：coverage 结果落 Redis（TTL 300s），测试间残留会污染后续用例，
    # 故 setUp 一并清除 Redis 中的 coverage 键，保证用例隔离。
    # P0-2 后 get_redis_client/_COVERAGE_REDIS_PREFIX 已迁至 weather_coverage_cache 模块。
    client = weather_coverage_cache.get_redis_client()
    if client is not None:
        try:
            for _model in ("ecmwf_ifs025", "gfs_global"):
                client.delete(weather_coverage_cache.COVERAGE_REDIS_PREFIX + _model)
        except Exception:
            pass
    yield ns


def test_unreachable(_weather_coverage_probe_tests_env) -> None:
    self = _weather_coverage_probe_tests_env
    import importlib

    wr = importlib.import_module("app.api.routers.weather_router")
    wr._COVERAGE_CACHE.clear()
    with patch.object(wr, "urlopen", side_effect=OSError("down")):
        cov, code = wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
    assert cov is None, 'cov is None'
    assert code == "local_unreachable", 'code == "local_unreachable"'


def test_model_empty_no_times(_weather_coverage_probe_tests_env) -> None:
    self = _weather_coverage_probe_tests_env
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
    assert cov is None, 'cov is None'
    assert code == "model_empty", 'code == "model_empty"'


def test_success_cached(_weather_coverage_probe_tests_env) -> None:
    self = _weather_coverage_probe_tests_env
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
    assert code1 is None, 'code1 is None'
    assert code2 is None, 'code2 is None'
    assert cov1["hour_count"] == 6, 'cov1["hour_count"] == 6'
    assert cov1["valid_hour_count"] == 6, 'cov1["valid_hour_count"] == 6'
    assert cov1["valid_times"] == times, 'cov1["valid_times"] == times'
    assert cov2["model"] == "ecmwf_ifs025", 'cov2["model"] == "ecmwf_ifs025"'
    assert mocked.call_count == 1, 'mocked.call_count == 1'


def test_valid_times_skips_null_temps(_weather_coverage_probe_tests_env) -> None:
    self = _weather_coverage_probe_tests_env
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
    assert code is None, 'code is None'
    assert cov is not None
    assert cov["valid_times"] == [times[0], times[2]], 'cov["valid_times"] == [times[0], times[2]]'
    assert cov["valid_hour_count"] == 2, 'cov["valid_hour_count"] == 2'
    assert cov["data_end_iso"] == times[2], 'cov["data_end_iso"] == times[2]'


def test_overview_shape() -> None:
    from app.services import weather_engine_settings as wes

    tmp = tempfile.TemporaryDirectory()
    repo = WeatherEngineSettingsRepository(Path(tmp.name) / "t.sqlite3")
    try:
        with patch.object(wes, "_get_repo", return_value=repo):
            with patch.object(
                wes, "probe_local_open_meteo_reachable", return_value=False
            ):
                overview = wes.get_weather_sync_overview()
        assert "domains" in overview, '"domains" in overview'
        assert "local_reachable" in overview, '"local_reachable" in overview'
        assert "enabled" in overview, '"enabled" in overview'
        assert "cron" in overview, '"cron" in overview'
        assert "variables" in overview, '"variables" in overview'
        assert "data_mode" in overview, '"data_mode" in overview'
        assert overview["data_mode"] == "forecast", 'overview["data_mode"] == "forecast"'
        assert "spatial" in overview, '"spatial" in overview'
        assert "temporal" in overview, '"temporal" in overview'
        assert "models_meta" in overview, '"models_meta" in overview'
        assert not overview["local_reachable"], 'overview["local_reachable"] is falsy'
    finally:
        repo.close()
        tmp.cleanup()
