from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.core.config import settings
from app.workflow_engine.base import BaseNode
from app.workflow_engine.enums import PortKind, RunStatus
from app.workflow_engine.models import (
    ExecutionContext,
    NodeExecutionResult,
    NodeSpec,
    PortSpec,
)
from app.weatherengine.constants import WEATHER_LAYER_SPECS
from app.weatherengine.fetch_gateway import fetch_point_forecast
from app.weatherengine.nodes._utils import coerce_float, coerce_int


class ForecastFetchNode(BaseNode):
    """天气预测抓取节点，经 fetch_gateway / Registry 获取原始预报数据。"""

    node_type: str = "weather_forecast_fetch"

    def __init__(self, spec: NodeSpec, context: ExecutionContext) -> None:
        super().__init__(spec, context)

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        try:
            layer_id = inputs.get("layer_id")
            if not layer_id or layer_id not in WEATHER_LAYER_SPECS:
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=[f"Unsupported weather layer: {layer_id}"],
                )

            spec = WEATHER_LAYER_SPECS[layer_id]

            # coerce_float(...) or default 会误判 0.0；仅在 coerce 失败时使用默认值
            latitude = coerce_float(inputs.get("latitude"))
            if latitude is None:
                latitude = settings.weather_default_latitude
            longitude = coerce_float(inputs.get("longitude"))
            if longitude is None:
                longitude = settings.weather_default_longitude
            model = inputs.get("model") or settings.weather_default_model
            forecast_hours = coerce_int(inputs.get("forecast_hours"))
            if not forecast_hours:
                forecast_hours = settings.weather_refresh_forecast_hours

            payload, cache_status, _provider_id = fetch_point_forecast(
                layer_id=layer_id,
                latitude=latitude,
                longitude=longitude,
                model=model,
                forecast_hours=forecast_hours,
                layer_spec=spec,
            )

            layer_spec_dict = asdict(spec)

            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.completed,
                outputs={
                    "forecast": payload,
                    "cache_status": cache_status,
                    "layer_spec": layer_spec_dict,
                },
            )
        except Exception as exc:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.failed,
                warnings=[f"ForecastFetchNode failed: {exc}"],
            )

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id=ForecastFetchNode.node_type,
            node_type=ForecastFetchNode.node_type,
            input_ports=[
                PortSpec(name="latitude", kind=PortKind.value, description="纬度"),
                PortSpec(name="longitude", kind=PortKind.value, description="经度"),
                PortSpec(name="layer_id", kind=PortKind.value, description="天气图层标识"),
                PortSpec(name="model", kind=PortKind.value, required=False, description="气象模型，可选"),
                PortSpec(name="forecast_hours", kind=PortKind.value, required=False, description="预报小时数，可选"),
            ],
            output_ports=[
                PortSpec(name="forecast", kind=PortKind.data, description="原始预报数据"),
                PortSpec(name="cache_status", kind=PortKind.value, description="缓存状态（hit/miss）"),
                PortSpec(name="layer_spec", kind=PortKind.data, description="图层规格字典"),
            ],
        )
