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
from app.weatherengine.nodes._utils import coerce_float, get_weather_engine_service, resolve_bbox
from shared.contracts.api_contracts import ResultKind, WeatherPointResponse

logger = logging.getLogger(__name__)


def _get_result_storage_service():
    """延迟导入 result_storage_service，避免循环导入。"""
    from app.services.result_storage import result_storage_service
    return result_storage_service


class PressureGridRenderNode(BaseNode):
    """气压网格渲染节点，基于预报数据生成海平面气压网格 GeoJSON。"""

    node_type: str = "weather_pressure_grid"
    _layer_id: str = "pressure"

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        try:
            latitude = coerce_float(inputs.get("latitude"))
            longitude = coerce_float(inputs.get("longitude"))

            if latitude is None or longitude is None:
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=["PressureGridRenderNode 缺少必需输入: latitude/longitude"],
                )

            # 获取 layer_id
            layer_id = inputs.get("layer_id") or self._layer_id

            weather_engine_service = get_weather_engine_service()

            # 优先使用真实网格数据（从 GridFetchNode 上游传入）
            grid_data = inputs.get("grid_data")
            if grid_data:
                # 使用真实网格数据构建 GeoJSON
                geojson = weather_engine_service.build_pressure_geojson_from_grid(
                    grid_data,
                    layer_id,
                )
                logger.info(
                    "[PressureGridRenderNode] Built from grid data: layer=%s features=%d",
                    layer_id, len(geojson.get("features", [])),
                )
            else:
                # 降级：使用单点数据 + 模拟算法
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
                geojson = weather_engine_service.build_pressure_geojson(weather, bbox)
                logger.info(
                    "[PressureGridRenderNode] Built from point data (fallback): layer=%s features=%d",
                    layer_id, len(geojson.get("features", [])),
                )

            # 将 GeoJSON 存储为 artifact，使前端可通过 /artifacts/{id} 访问
            storage = _get_result_storage_service()
            run_id = self.context.metadata.get("workflow_run_id", self.context.run_id)
            artifact = None
            try:
                from datetime import datetime, timezone
                artifact_ref = storage.create_artifact_result_ref(
                    run_id=run_id,
                    result_id=f"pressure-geojson-{self.spec.node_id}",
                    result_kind=ResultKind.file,
                    title="气压网格 GeoJSON",
                    mime_type="application/geo+json",
                    updated_at=datetime.now(timezone.utc),
                    payload=geojson,
                )
                artifact = ArtifactRecord(
                    artifact_id=artifact_ref.resource_key or "",
                    workflow_run_id=run_id,
                    node_id=self.spec.node_id,
                    artifact_type="pressure_geojson",
                    storage_uri=artifact_ref.resource_url or "",
                    content_type="application/geo+json",
                )
            except Exception as exc:
                logger.warning("Failed to store pressure GeoJSON artifact: %s", exc)

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
                warnings=[f"PressureGridRenderNode failed: {exc}"],
            )

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id=PressureGridRenderNode.node_type,
            node_type=PressureGridRenderNode.node_type,
            input_ports=[
                PortSpec(name="grid_data", kind=PortKind.data, required=False, description="上游 GridFetchNode 输出的网格化天气数据，优先使用"),
                PortSpec(name="weather_point", kind=PortKind.data, required=False, description="上游 PointParseNode 输出的天气点位数据，未提供且无 grid_data 时使用"),
                PortSpec(name="latitude", kind=PortKind.value, description="中心纬度"),
                PortSpec(name="longitude", kind=PortKind.value, description="中心经度"),
                PortSpec(name="layer_id", kind=PortKind.value, required=False, description="图层类型"),
                PortSpec(name="viewport_bbox", kind=PortKind.data, required=False, description="视口边界框"),
                PortSpec(name="bbox", kind=PortKind.data, required=False, description="空间过滤器边界框"),
            ],
            output_ports=[
                PortSpec(name="geojson", kind=PortKind.geojson, description="气压网格 GeoJSON FeatureCollection"),
            ],
        )
