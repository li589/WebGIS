from __future__ import annotations

from typing import Any

from app.workflow_engine.base import BaseNode
from app.workflow_engine.enums import PortKind, RunStatus
from app.workflow_engine.models import (
    NodeExecutionResult,
    NodeSpec,
    PortSpec,
)
from app.weatherengine.nodes._utils import coerce_float, get_weather_engine_service, resolve_bbox
from shared.contracts.api_contracts import WeatherPointResponse


class PrecipitationGridRenderNode(BaseNode):
    """降水网格渲染节点，基于预报数据生成降水网格 GeoJSON。"""

    node_type: str = "weather_precipitation_grid"
    _layer_id: str = "precipitation"

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        try:
            latitude = coerce_float(inputs.get("latitude"))
            longitude = coerce_float(inputs.get("longitude"))

            if latitude is None or longitude is None:
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=["PrecipitationGridRenderNode 缺少必需输入: latitude/longitude"],
                )

            # 优先消费上游 weather_point，避免冗余 API 调用
            weather_engine_service = get_weather_engine_service()
            weather_point = inputs.get("weather_point")
            if isinstance(weather_point, dict):
                weather = WeatherPointResponse.model_validate(weather_point)
            else:
                weather = weather_engine_service.get_point_weather(
                    layer_id=self._layer_id,
                    latitude=latitude,
                    longitude=longitude,
                )

            bbox = resolve_bbox(inputs, latitude, longitude)
            geojson = weather_engine_service.build_precipitation_geojson(weather, bbox)

            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.completed,
                outputs={"geojson": geojson},
            )
        except Exception as exc:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.failed,
                warnings=[f"PrecipitationGridRenderNode failed: {exc}"],
            )

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id=PrecipitationGridRenderNode.node_type,
            node_type=PrecipitationGridRenderNode.node_type,
            input_ports=[
                PortSpec(name="weather_point", kind=PortKind.data, required=False, description="上游 PointParseNode 输出的天气点位数据，未提供时自行获取"),
                PortSpec(name="latitude", kind=PortKind.value, description="中心纬度"),
                PortSpec(name="longitude", kind=PortKind.value, description="中心经度"),
            ],
            output_ports=[
                PortSpec(name="geojson", kind=PortKind.geojson, description="降水网格 GeoJSON FeatureCollection"),
            ],
        )
