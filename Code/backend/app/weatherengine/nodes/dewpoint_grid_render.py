"""Dewpoint grid render node — GeoJSON from grid or point fallback."""

from __future__ import annotations

import logging
from typing import Any

from app.workflow_engine.base import BaseNode
from app.workflow_engine.enums import PortKind, RunStatus
from app.workflow_engine.models import (
    ArtifactRecord,
    NodeExecutionResult,
    NodeSpec,
    PortSpec,
)
from app.weatherengine.nodes._utils import (
    coerce_float,
    get_weather_engine_service,
    resolve_bbox,
)
from shared.contracts.api_contracts import ResultKind, WeatherPointResponse

logger = logging.getLogger(__name__)


def _get_result_storage_service():
    from app.services.result_storage import result_storage_service

    return result_storage_service


class DewpointGridRenderNode(BaseNode):
    """露点网格渲染节点。"""

    node_type: str = "weather_dewpoint_grid"
    _layer_id: str = "dewpoint"

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        try:
            latitude = coerce_float(inputs.get("latitude"))
            longitude = coerce_float(inputs.get("longitude"))
            if latitude is None or longitude is None:
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=[
                        "DewpointGridRenderNode 缺少必需输入: latitude/longitude"
                    ],
                )

            layer_id = inputs.get("layer_id") or self._layer_id
            weather_engine_service = get_weather_engine_service()
            grid_data = inputs.get("grid_data")
            if grid_data:
                geojson = weather_engine_service.build_dewpoint_geojson_from_grid(
                    grid_data, layer_id
                )
            else:
                bbox = resolve_bbox(inputs, latitude, longitude)
                weather_point = inputs.get("weather_point")
                if isinstance(weather_point, dict):
                    weather = WeatherPointResponse.model_validate(weather_point)
                else:
                    weather = weather_engine_service.get_point_weather(
                        layer_id=layer_id,
                        latitude=latitude,
                        longitude=longitude,
                    )
                base = float(getattr(weather.current, "dew_point_2m", None) or 0.0)
                geojson = weather_engine_service.build_scalar_geojson_from_point(
                    weather,
                    bbox,
                    metric_key="dew_point_2m",
                    unit="°C",
                    base_value=base,
                )

            storage = _get_result_storage_service()
            run_id = self.context.metadata.get("workflow_run_id", self.context.run_id)
            artifact = None
            try:
                from datetime import datetime, timezone

                artifact_ref = storage.create_artifact_result_ref(
                    run_id=run_id,
                    result_id=f"dewpoint-geojson-{self.spec.node_id}",
                    result_kind=ResultKind.file,
                    title="Dewpoint Grid GeoJSON",
                    mime_type="application/geo+json",
                    updated_at=datetime.now(timezone.utc),
                    payload=geojson,
                )
                artifact = ArtifactRecord(
                    artifact_id=artifact_ref.resource_key or "",
                    workflow_run_id=run_id,
                    node_id=self.spec.node_id,
                    artifact_type="dewpoint_geojson",
                    storage_uri=artifact_ref.resource_url or "",
                    content_type="application/geo+json",
                )
            except Exception as exc:
                logger.warning("Failed to store dewpoint GeoJSON artifact: %s", exc)

            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.completed,
                outputs={"geojson": geojson},
                artifacts=[artifact] if artifact else [],
            )
        except Exception as exc:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.failed,
                warnings=[f"DewpointGridRenderNode failed: {exc}"],
            )

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id=DewpointGridRenderNode.node_type,
            node_type=DewpointGridRenderNode.node_type,
            input_ports=[
                PortSpec(
                    name="grid_data",
                    kind=PortKind.data,
                    required=False,
                    description="上游 GridFetchNode 输出的网格化天气数据",
                ),
                PortSpec(
                    name="weather_point",
                    kind=PortKind.data,
                    required=False,
                    description="上游点天气数据（无 grid_data 时回退）",
                ),
                PortSpec(name="latitude", kind=PortKind.value, description="中心纬度"),
                PortSpec(name="longitude", kind=PortKind.value, description="中心经度"),
                PortSpec(
                    name="bbox",
                    kind=PortKind.data,
                    required=False,
                    description="可选包围盒",
                ),
                PortSpec(
                    name="layer_id",
                    kind=PortKind.value,
                    required=False,
                    description="图层 ID，默认 dewpoint",
                ),
            ],
            output_ports=[
                PortSpec(
                    name="geojson", kind=PortKind.data, description="露点 GeoJSON"
                ),
            ],
        )
