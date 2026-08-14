"""Phase D1: weather coverage probe — unreachable / empty / timeout / success."""

from __future__ import annotations

import pytest
import types
import json
from unittest.mock import MagicMock, patch
from urllib.error import URLError


@pytest.fixture
def _weather_coverage_probe_phase_d_tests_env():
    ns = types.SimpleNamespace()
    import importlib

    ns.wr = importlib.import_module("app.api.routers.weather_router")
    ns.wr._COVERAGE_CACHE.clear()
    # C2：coverage 结果落 Redis（TTL 300s），测试间残留会污染后续用例，
    # 故 setUp 一并清除 Redis 中的 coverage 键，保证用例隔离。
    client = ns.wr.get_redis_client()
    if client is not None:
        try:
            for _model in ("ecmwf_ifs025", "gfs_global"):
                client.delete(ns.wr._COVERAGE_REDIS_PREFIX + _model)
        except Exception:
            pass
    yield ns


def test_unreachable(_weather_coverage_probe_phase_d_tests_env) -> None:
    self = _weather_coverage_probe_phase_d_tests_env
    with patch.object(self.wr, "urlopen", side_effect=OSError("down")):
        cov, code = self.wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
    assert cov is None, 'cov is None'
    assert code == "local_unreachable", 'code == "local_unreachable"'


def test_timeout_as_unreachable(_weather_coverage_probe_phase_d_tests_env) -> None:
    self = _weather_coverage_probe_phase_d_tests_env
    with patch.object(self.wr, "urlopen", side_effect=URLError("timed out")):
        cov, code = self.wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
    assert cov is None, 'cov is None'
    assert code == "local_unreachable", 'code == "local_unreachable"'


def test_model_empty(_weather_coverage_probe_phase_d_tests_env) -> None:
    self = _weather_coverage_probe_phase_d_tests_env
    payload = {"hourly": {"time": [], "temperature_2m": []}}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    with patch.object(self.wr, "urlopen", return_value=mock_resp):
        cov, code = self.wr._probe_local_open_meteo_coverage("gfs_global")
    assert cov is None, 'cov is None'
    assert code == "model_empty", 'code == "model_empty"'


def test_all_null_temps_model_empty(_weather_coverage_probe_phase_d_tests_env) -> None:
    self = _weather_coverage_probe_phase_d_tests_env
    times = [f"2026-07-21T{h:02d}:00" for h in range(3)]
    payload = {"hourly": {"time": times, "temperature_2m": [None, None, None]}}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    with patch.object(self.wr, "urlopen", return_value=mock_resp):
        cov, code = self.wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
    assert cov is None, 'cov is None'
    assert code == "model_empty", 'code == "model_empty"'


def test_success(_weather_coverage_probe_phase_d_tests_env) -> None:
    self = _weather_coverage_probe_phase_d_tests_env
    times = [f"2026-07-21T{h:02d}:00" for h in range(4)]
    payload = {"hourly": {"time": times, "temperature_2m": [1.0, 2.0, 3.0, 4.0]}}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    with patch.object(self.wr, "urlopen", return_value=mock_resp):
        cov, code = self.wr._probe_local_open_meteo_coverage("ecmwf_ifs025")
    assert code is None, 'code is None'
    assert cov is not None
    assert cov["hour_count"] == 4, 'cov["hour_count"] == 4'
    assert cov["valid_hour_count"] == 4, 'cov["valid_hour_count"] == 4'


def test_route_returns_503_on_unreachable(_weather_coverage_probe_phase_d_tests_env) -> None:
    self = _weather_coverage_probe_phase_d_tests_env
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
            with pytest.raises(HTTPException) as ctx:
                self.wr.get_weather_coverage(model=None)
    assert ctx.value.status_code == 503, 'ctx.exception.status_code == 503'
    detail = ctx.value.detail
    assert isinstance(detail, dict), 'isinstance(detail, dict)'
    assert detail.get("code") == "local_unreachable", 'detail.get("code") == "local_unreachable"'


def test_invalidate_noarg_deletes_all_redis_coverage_keys(_weather_coverage_probe_phase_d_tests_env) -> None:
    self = _weather_coverage_probe_phase_d_tests_env
    client = MagicMock()
    with (
        patch("app.services.weather_coverage_cache.get_redis_client", return_value=client),
        patch(
            "app.services.weather_coverage_cache.scan_keys",
            return_value=[
                "weather:coverage:ecmwf_ifs025",
                "weather:coverage:gfs_global",
            ],
        ),
    ):
        self.wr.invalidate_weather_coverage_cache()
    client.delete.assert_called_once()
    assert sorted(client.delete.call_args[0]) == ["weather:coverage:ecmwf_ifs025", "weather:coverage:gfs_global"], 'sorted(client.delete.call_args[0]) == ["weather:coverage:ecmwf_ifs025", "weather:coverage:gfs_global"]'


def test_invalidate_model_deletes_single_redis_key(_weather_coverage_probe_phase_d_tests_env) -> None:
    self = _weather_coverage_probe_phase_d_tests_env
    client = MagicMock()
    with patch("app.services.weather_coverage_cache.get_redis_client", return_value=client):
        self.wr.invalidate_weather_coverage_cache("ecmwf_ifs025")
    client.delete.assert_called_once_with("weather:coverage:ecmwf_ifs025")
    # 带 model 分支按 key 删，不触发 scan
    client.reset_mock()
    with patch("app.services.weather_coverage_cache.get_redis_client", return_value=client):
        self.wr.invalidate_weather_coverage_cache("gfs_global")
    client.delete.assert_called_once_with("weather:coverage:gfs_global")
