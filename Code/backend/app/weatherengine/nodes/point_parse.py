from __future__ import annotations

from typing import Any

from app.weatherengine.default_model import weather_default_model
from app.workflow_engine.base import BaseNode
from app.workflow_engine.enums import PortKind, RunStatus
from app.workflow_engine.models import (
    NodeExecutionResult,
    NodeSpec,
    PortSpec,
)
from app.weatherengine.nodes._utils import (
    coerce_float,
    coerce_int,
    get_weather_engine_service,
)


class PointParseNode(BaseNode):
    """天气点位解析节点，将原始预报数据解析为结构化的天气点位信息。"""

    node_type: str = "weather_point_parse"

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        try:
            layer_id = inputs.get("layer_id")
            latitude = coerce_float(inputs.get("latitude"))
            longitude = coerce_float(inputs.get("longitude"))
            forecast_hours = coerce_int(inputs.get("forecast_hours")) or 6

            if layer_id is None:
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=["PointParseNode 缺少必需输入: layer_id"],
                )
            if latitude is None or longitude is None:
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=["PointParseNode 缺少必需输入: latitude/longitude"],
                )

            weather_engine_service = get_weather_engine_service()
            # M11 修复：优先消费上游 ForecastFetchNode 输出的 forecast，避免重复 API 调用
            forecast = inputs.get("forecast")
            if isinstance(forecast, dict) and forecast:
                cache_status = inputs.get("cache_status") or "upstream"
                resolved_model = inputs.get("model") or weather_default_model()
                weather = weather_engine_service.parse_forecast_to_point(
                    payload=forecast,
                    cache_status=cache_status,
                    layer_id=layer_id,
                    latitude=latitude,
                    longitude=longitude,
                    resolved_model=resolved_model,
                    forecast_hours=forecast_hours,
                )
            else:
                # fallback：无上游 forecast 时调用 get_point_weather（含 API 调用）
                kwargs: dict[str, Any] = {
                    "layer_id": layer_id,
                    "latitude": latitude,
                    "longitude": longitude,
                }
                if forecast_hours is not None:
                    kwargs["forecast_hours"] = forecast_hours
                weather = weather_engine_service.get_point_weather(**kwargs)

            weather_point = weather.model_dump(mode="json")

            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.completed,
                outputs={
                    "weather_point": weather_point,
                    "summary": weather.summary,
                },
            )
        except Exception as exc:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.failed,
                warnings=[f"PointParseNode failed: {exc}"],
            )

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id=PointParseNode.node_type,
            node_type=PointParseNode.node_type,
            input_ports=[
                PortSpec(
                    name="forecast",
                    kind=PortKind.data,
                    required=False,
                    description="上游 ForecastFetchNode 输出的原始预报数据，未提供时自行获取",
                ),
                PortSpec(
                    name="layer_id", kind=PortKind.value, description="天气图层标识"
                ),
                PortSpec(name="latitude", kind=PortKind.value, description="纬度"),
                PortSpec(name="longitude", kind=PortKind.value, description="经度"),
                PortSpec(
                    name="forecast_hours",
                    kind=PortKind.value,
                    required=False,
                    description="预报小时数，可选",
                ),
                PortSpec(
                    name="cache_status",
                    kind=PortKind.value,
                    required=False,
                    description="上游缓存状态，可选",
                ),
                PortSpec(
                    name="model",
                    kind=PortKind.value,
                    required=False,
                    description="气象模型，可选",
                ),
            ],
            output_ports=[
                PortSpec(
                    name="weather_point",
                    kind=PortKind.data,
                    description="结构化天气点位数据",
                ),
                PortSpec(
                    name="summary", kind=PortKind.value, description="天气摘要文本"
                ),
            ],
        )
