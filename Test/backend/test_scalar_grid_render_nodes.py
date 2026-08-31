"""N1 标量网格渲染基类与薄壳节点的参数化行为测试。

覆盖：grid 路径指标/单位/skip_none/min_value 语义、point 回退 hook 分派
（参数化路径与专用 builder 路径）、缺坐标失败、薄壳契约字段完整性。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.weatherengine.nodes import scalar_grid_render as sgr_module
from app.weatherengine.nodes.cloud_cover_grid_render import CloudCoverGridRenderNode
from app.weatherengine.nodes.dewpoint_grid_render import DewpointGridRenderNode
from app.weatherengine.nodes.humidity_grid_render import HumidityGridRenderNode
from app.weatherengine.nodes.precipitation_grid_render import (
    PrecipitationGridRenderNode,
)
from app.weatherengine.nodes.pressure_grid_render import PressureGridRenderNode
from app.weatherengine.nodes.scalar_grid_render import ScalarGridRenderNode
from app.weatherengine.nodes.visibility_grid_render import VisibilityGridRenderNode
from app.workflow_engine.enums import RunStatus
from app.workflow_engine.models import ExecutionContext

_THIN_SHELLS = (
    CloudCoverGridRenderNode,
    DewpointGridRenderNode,
    HumidityGridRenderNode,
    PrecipitationGridRenderNode,
    PressureGridRenderNode,
    VisibilityGridRenderNode,
)


class _FakeStorage:
    def create_artifact_result_ref(self, **kwargs: Any) -> Any:
        class _Ref:
            resource_key = "fake-key"
            resource_url = "fake-url"

        return _Ref()


class _FakeService:
    """记录 builder 调用并返回可断言 geojson 的假天气引擎服务。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.grid_payload: dict[str, Any] = {}

    def build_scalar_geojson_from_grid(
        self, grid_data: Any, **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append(("scalar_from_grid", kwargs))
        return {"type": "FeatureCollection", "features": [{"properties": {}}]}

    def build_scalar_geojson_from_point(
        self, weather: Any, bbox: Any, **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append(("scalar_from_point", kwargs))
        return {"type": "FeatureCollection", "features": [{"properties": {}}]}

    def build_humidity_geojson(self, weather: Any, bbox: Any) -> dict[str, Any]:
        self.calls.append(("humidity_dedicated", {"weather": weather, "bbox": bbox}))
        return {"type": "FeatureCollection", "features": [{"properties": {}}]}

    def build_precipitation_geojson(self, weather: Any, bbox: Any) -> dict[str, Any]:
        self.calls.append(("precipitation_dedicated", {}))
        return {"type": "FeatureCollection", "features": [{"properties": {}}]}


def _make_node(cls: type[ScalarGridRenderNode]) -> ScalarGridRenderNode:
    return cls(spec=cls.build_spec(), context=ExecutionContext())


def _grid_payload(metric_key: str, values: list[Any]) -> dict[str, Any]:
    cols = len(values)
    return {
        "grid": {
            "rows": 1,
            "cols": cols,
            "bbox": {
                "west": 100.0,
                "south": 20.0,
                "east": 100.0 + 0.5 * cols,
                "north": 21.0,
            },
        },
        "data": {"current": {metric_key: values}},
    }


@pytest.fixture()
def _patched_services(monkeypatch: pytest.MonkeyPatch) -> _FakeService:
    service = _FakeService()
    monkeypatch.setattr(
        sgr_module, "get_weather_engine_service", lambda: service
    )
    monkeypatch.setattr(
        sgr_module, "_get_result_storage_service", lambda: _FakeStorage()
    )
    return service


def test_grid_path_dewpoint_passes_skip_none(_patched_services: _FakeService) -> None:
    node = _make_node(DewpointGridRenderNode)
    result = node.execute(
        {
            "latitude": 20.5,
            "longitude": 100.2,
            "grid_data": _grid_payload("dew_point_2m", [10.0, None, 20.5]),
        }
    )
    assert result.status == RunStatus.completed
    assert _patched_services.calls[0][0] == "scalar_from_grid"
    kwargs = _patched_services.calls[0][1]
    assert kwargs["metric_key"] == "dew_point_2m"
    assert kwargs["unit"] == "C"
    assert kwargs["skip_none"] is True


def test_grid_path_precipitation_applies_min_value(
    _patched_services: _FakeService,
) -> None:
    node = _make_node(PrecipitationGridRenderNode)
    result = node.execute(
        {
            "latitude": 20.5,
            "longitude": 100.2,
            "grid_data": _grid_payload("precipitation", [0.05, 0.5]),
        }
    )
    assert result.status == RunStatus.completed
    kwargs = _patched_services.calls[0][1]
    assert kwargs["metric_key"] == "precipitation"
    assert kwargs["unit"] == "mm"
    assert kwargs["min_value"] == 0.1


def test_point_fallback_parametrized_path(_patched_services: _FakeService) -> None:
    """声明 _point_unit/_base_field 的薄壳走参数化 scalar_from_point。"""

    class _Current:
        dew_point_2m = 12.3

    class _Weather:
        current = _Current()

    node = _make_node(DewpointGridRenderNode)
    geojson = node._build_point_fallback(_patched_services, _Weather(), bbox=object())
    assert geojson["type"] == "FeatureCollection"
    name, kwargs = _patched_services.calls[0]
    assert name == "scalar_from_point"
    assert kwargs["metric_key"] == "dew_point_2m"
    assert kwargs["unit"] == "°C"
    assert kwargs["base_value"] == pytest.approx(12.3)


def test_point_fallback_dedicated_builder(_patched_services: _FakeService) -> None:
    """覆写 _build_point_fallback 的薄壳挂接专用 builder。"""

    node = _make_node(HumidityGridRenderNode)
    geojson = node._build_point_fallback(
        _patched_services, weather=object(), bbox=object()
    )
    assert geojson["type"] == "FeatureCollection"
    assert _patched_services.calls[0][0] == "humidity_dedicated"


def test_missing_coordinates_fails(_patched_services: _FakeService) -> None:
    node = _make_node(VisibilityGridRenderNode)
    result = node.execute({"latitude": 20.5})
    assert result.status == RunStatus.failed
    assert any("latitude/longitude" in w for w in result.warnings)


def test_thin_shells_declare_contract() -> None:
    """6 个薄壳必须声明完整差异字段且 node_type 对外不变。"""

    expected_types = {
        CloudCoverGridRenderNode: "weather_cloud_cover_grid",
        DewpointGridRenderNode: "weather_dewpoint_grid",
        HumidityGridRenderNode: "weather_humidity_grid",
        PrecipitationGridRenderNode: "weather_precipitation_grid",
        PressureGridRenderNode: "weather_pressure_grid",
        VisibilityGridRenderNode: "weather_visibility_grid",
    }
    required_fields = (
        "_layer_id",
        "_metric_key",
        "_unit",
        "_artifact_type",
        "_result_prefix",
        "_display_title",
        "_node_label",
    )
    for cls in _THIN_SHELLS:
        assert issubclass(cls, ScalarGridRenderNode)
        assert cls.node_type == expected_types[cls]
        for field in required_fields:
            assert getattr(cls, field), f"{cls.__name__} 未声明 {field}"
        assert cls.build_spec().node_type == expected_types[cls]
