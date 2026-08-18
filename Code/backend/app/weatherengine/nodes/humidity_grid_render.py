"""Humidity grid render node — GeoJSON from grid or point fallback (N1 薄壳)."""

from __future__ import annotations

from typing import Any

from app.workflow_engine.enums import PortKind
from app.workflow_engine.models import NodeSpec, PortSpec
from app.weatherengine.nodes.scalar_grid_render import ScalarGridRenderNode
from shared.contracts.api_contracts import WeatherPointResponse


class HumidityGridRenderNode(ScalarGridRenderNode):
    """湿度网格渲染节点。"""

    node_type: str = "weather_humidity_grid"
    _layer_id: str = "humidity"
    _metric_key: str = "relative_humidity_2m"
    _unit: str = "%"
    _artifact_type: str = "humidity_geojson"
    _result_prefix: str = "humidity"
    _display_title: str = "Humidity Grid GeoJSON"
    _node_label: str = "HumidityGridRenderNode"

    def _build_point_fallback(
        self, service: Any, weather: WeatherPointResponse, bbox: Any
    ) -> dict[str, object]:
        return service.build_humidity_geojson(weather, bbox)

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id=HumidityGridRenderNode.node_type,
            node_type=HumidityGridRenderNode.node_type,
            input_ports=[
                PortSpec(
                    name="grid_data",
                    kind=PortKind.data,
                    required=False,
                    description="上游 GridFetchNode 输出的网格化天气数据，优先使用",
                ),
                PortSpec(
                    name="weather_point",
                    kind=PortKind.data,
                    required=False,
                    description="上游 PointParseNode 输出的天气点位数据，未提供且无 grid_data 时使用",
                ),
                PortSpec(name="latitude", kind=PortKind.value, description="中心纬度"),
                PortSpec(name="longitude", kind=PortKind.value, description="中心经度"),
                PortSpec(
                    name="layer_id",
                    kind=PortKind.value,
                    required=False,
                    description="图层类型",
                ),
                PortSpec(
                    name="viewport_bbox",
                    kind=PortKind.data,
                    required=False,
                    description="视口边界框",
                ),
                PortSpec(
                    name="bbox",
                    kind=PortKind.data,
                    required=False,
                    description="空间过滤器边界框",
                ),
            ],
            output_ports=[
                PortSpec(
                    name="geojson",
                    kind=PortKind.geojson,
                    description="湿度网格 GeoJSON FeatureCollection",
                ),
            ],
        )
