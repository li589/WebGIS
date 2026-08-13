"""weatherengine get_point_weather 单元测试。

验证 3 个图层（wind-field/temperature/precipitation）的 forecast 解析、
render_hint 构造、缓存 miss→hit 转换逻辑，mock Open-Meteo API 避免网络依赖。
"""

from __future__ import annotations

import pytest
import types
from typing import Any

from app.weatherengine.constants import WEATHER_LAYER_SPECS
from app.weatherengine.service import WeatherEngineService
from app.weatherengine.provider_registry import get_registry
from app.weatherengine.providers.open_meteo_provider import OpenMeteoProvider


class _FakeOpenMeteoClient:
    """模拟 OpenMeteoClient，支持 cache_status 序列以测试 miss→hit 转换。"""

    def __init__(self, cache_status_sequence: list[str] | None = None) -> None:
        self._status_seq = cache_status_sequence or ["miss", "hit"]
        self._call_count = 0
        self.call_history: list[dict[str, Any]] = []

    def fetch_point_forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        layer_spec,
        model: str,
        forecast_hours: int,
        ttl_seconds: int,
        pressure_levels: tuple[int, ...] | None = None,
    ) -> tuple[dict[str, Any], str]:
        status = self._status_seq[self._call_count % len(self._status_seq)]
        self._call_count += 1
        self.call_history.append(
            {
                "latitude": latitude,
                "longitude": longitude,
                "layer_id": layer_spec.layer_id,
                "model": model,
                "forecast_hours": forecast_hours,
                "cache_status": status,
            }
        )
        return (_build_mock_payload(layer_spec), status)


def _build_mock_payload(layer_spec) -> dict[str, Any]:
    """根据 layer_spec 构造模拟 Open-Meteo 响应 payload。"""
    current: dict[str, Any] = {
        "time": "2026-07-06T00:00",
        "temperature_2m": 25.7,
        "apparent_temperature": 30.4,
        "precipitation": 0.2,
        "rain": 0.1,
        "weather_code": 3,
        "cloud_cover": 65,
        "wind_speed_10m": 13.2,
        "wind_direction_10m": 154.0,
        "wind_gusts_10m": 27.0,
    }
    hourly: dict[str, list] = {
        "time": [
            "2026-07-06T00:00",
            "2026-07-06T01:00",
            "2026-07-06T02:00",
            "2026-07-06T03:00",
            "2026-07-06T04:00",
            "2026-07-06T05:00",
        ],
        "temperature_2m": [25.7, 25.3, 24.9, 24.5, 24.1, 23.8],
        "precipitation": [0.2, 0.7, 0.0, 0.0, 0.1, 0.3],
        "wind_speed_10m": [13.2, 12.9, 13.2, 12.5, 11.8, 11.1],
    }
    return {
        "timezone": "Asia/Shanghai",
        "utc_offset_seconds": 28800,
        "generationtime_ms": 0.0123,
        "model": "best_match",
        "current": current,
        "hourly": hourly,
    }


@pytest.fixture
def _get_point_weather_tests_env():
    ns = types.SimpleNamespace()
    # 注册带 fake client 的 OpenMeteoProvider，供 get_point_weather 通过 registry 路由
    registry = get_registry()
    registry.clear()  # 清理前序测试残留的 provider，防止 local provider 干扰
    registry.register(
        OpenMeteoProvider(client=_FakeOpenMeteoClient()),
        priority=0,
        enabled=True,
    )
    yield ns
    get_registry().clear()


def _make_service(
    cache_status_sequence: list[str] | None = None
) -> tuple[WeatherEngineService, _FakeOpenMeteoClient]:
    client = _FakeOpenMeteoClient(cache_status_sequence=cache_status_sequence)
    # 覆盖 setUp 中的默认 provider，使用带特定 cache_status_sequence 的 fake client
    # 确保 get_point_weather 通过 registry 路由到此 client（而非 setUp 的默认 client）
    get_registry().register(
        OpenMeteoProvider(client=client),
        priority=0,
        enabled=True,
    )
    return WeatherEngineService(), client


def test_wind_field_layer(_get_point_weather_tests_env) -> None:
    self = _get_point_weather_tests_env
    service, _ = _make_service()
    response = service.get_point_weather(
        layer_id="wind-field",
        latitude=23.1291,
        longitude=113.2644,
        model="best_match",
        forecast_hours=6,
        place_name="Guangzhou",
    )
    assert response.provider == "open-meteo-online", 'response.provider == "open-meteo-online"'
    assert response.layer_id == "wind-field", 'response.layer_id == "wind-field"'
    assert response.place_name == "Guangzhou", 'response.place_name == "Guangzhou"'
    assert response.cache_status == "miss", 'response.cache_status == "miss"'
    # wind-field spec 验证
    spec = WEATHER_LAYER_SPECS["wind-field"]
    assert response.render_hint.primary_metric == spec.primary_metric, 'response.render_hint.primary_metric == spec.primary_metric'
    assert response.render_hint.paint_mode == spec.paint_mode, 'response.render_hint.paint_mode == spec.paint_mode'
    assert response.render_hint.palette == spec.palette, 'response.render_hint.palette == spec.palette'
    assert response.render_hint.unit_label == spec.unit_label, 'response.render_hint.unit_label == spec.unit_label'
    # current 数据
    assert round(response.current.wind_speed_10m or 0.0, 7) == round(13.2, 7), 'round(response.current.wind_speed_10m or 0.0, 7) == round(13.2, 7)'
    assert round(response.current.wind_direction_10m or 0.0, 7) == round(154.0, 7), 'round(response.current.wind_direction_10m or 0.0, 7) == round(154.0, 7)'
    assert round(response.current.wind_gusts_10m or 0.0, 7) == round(27.0, 7), 'round(response.current.wind_gusts_10m or 0.0, 7) == round(27.0, 7)'
    # hourly 数据
    assert len(response.hourly) == 6, 'len(response.hourly) == 6'
    assert round(response.hourly[0].wind_speed_10m or 0.0, 7) == round(13.2, 7), 'round(response.hourly[0].wind_speed_10m or 0.0, 7) == round(13.2, 7)'


def test_temperature_layer(_get_point_weather_tests_env) -> None:
    self = _get_point_weather_tests_env
    service, _ = _make_service()
    response = service.get_point_weather(
        layer_id="temperature",
        latitude=23.1291,
        longitude=113.2644,
        model="best_match",
        forecast_hours=3,
    )
    spec = WEATHER_LAYER_SPECS["temperature"]
    assert response.render_hint.paint_mode == spec.paint_mode, 'response.render_hint.paint_mode == spec.paint_mode'
    assert response.render_hint.palette == "thermal-orange", 'response.render_hint.palette == "thermal-orange"'
    assert response.render_hint.unit_label == "C", 'response.render_hint.unit_label == "C"'
    assert round(response.current.temperature_2m or 0.0, 7) == round(25.7, 7), 'round(response.current.temperature_2m or 0.0, 7) == round(25.7, 7)'
    assert round(response.current.apparent_temperature or 0.0, 7) == round(30.4, 7), 'round(response.current.apparent_temperature or 0.0, 7) == round(30.4, 7)'
    assert len(response.hourly) == 3, 'len(response.hourly) == 3'


def test_precipitation_layer(_get_point_weather_tests_env) -> None:
    self = _get_point_weather_tests_env
    service, _ = _make_service()
    response = service.get_point_weather(
        layer_id="precipitation",
        latitude=23.1291,
        longitude=113.2644,
        model="best_match",
        forecast_hours=4,
    )
    spec = WEATHER_LAYER_SPECS["precipitation"]
    assert response.render_hint.paint_mode == spec.paint_mode, 'response.render_hint.paint_mode == spec.paint_mode'
    assert response.render_hint.palette == "precip-cyan", 'response.render_hint.palette == "precip-cyan"'
    assert response.render_hint.unit_label == "mm", 'response.render_hint.unit_label == "mm"'
    assert round(response.current.precipitation or 0.0, 7) == round(0.2, 7), 'round(response.current.precipitation or 0.0, 7) == round(0.2, 7)'
    assert len(response.hourly) == 4, 'len(response.hourly) == 4'
    assert round(response.hourly[0].precipitation or 0.0, 7) == round(0.2, 7), 'round(response.hourly[0].precipitation or 0.0, 7) == round(0.2, 7)'


def test_unsupported_layer_raises(_get_point_weather_tests_env) -> None:
    self = _get_point_weather_tests_env
    service, _ = _make_service()
    with pytest.raises(ValueError):
        service.get_point_weather(
            layer_id="nonexistent",
            latitude=23.0,
            longitude=113.0,
        )


def test_cache_miss_then_hit(_get_point_weather_tests_env) -> None:
    """验证首次调用 miss，二次调用 hit 的缓存逻辑。"""
    self = _get_point_weather_tests_env
    service, client = _make_service(cache_status_sequence=["miss", "hit"])

    response1 = service.get_point_weather(
        layer_id="wind-field",
        latitude=23.1291,
        longitude=113.2644,
        forecast_hours=6,
    )
    assert response1.cache_status == "miss", 'response1.cache_status == "miss"'

    response2 = service.get_point_weather(
        layer_id="wind-field",
        latitude=23.1291,
        longitude=113.2644,
        forecast_hours=6,
    )
    assert response2.cache_status == "hit", 'response2.cache_status == "hit"'

    # 验证 client 被调用 2 次
    assert len(client.call_history) == 2, 'len(client.call_history) == 2'
    assert client.call_history[0]["cache_status"] == "miss", 'client.call_history[0]["cache_status"] == "miss"'
    assert client.call_history[1]["cache_status"] == "hit", 'client.call_history[1]["cache_status"] == "hit"'


def test_diagnostics_content(_get_point_weather_tests_env) -> None:
    """验证 diagnostics 含 provider/layer_id/model/cache_status 信息。"""
    self = _get_point_weather_tests_env
    service, _ = _make_service()
    response = service.get_point_weather(
        layer_id="wind-field",
        latitude=23.0,
        longitude=113.0,
        model="best_match",
    )
    diag_text = "\n".join(response.diagnostics)
    assert "provider=open-meteo-online" in diag_text, '"provider=open-meteo-online" in diag_text'
    assert "layer_id=wind-field" in diag_text, '"layer_id=wind-field" in diag_text'
    assert "model=best_match" in diag_text, '"model=best_match" in diag_text'
    assert "cache_status=" in diag_text, '"cache_status=" in diag_text'
