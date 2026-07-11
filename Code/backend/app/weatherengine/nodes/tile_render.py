"""天气瓦片渲染节点。

按标准 Web Mercator z/x/y 渲染单个瓦片 GeoJSON，供 workflow 使用。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.services.result_storage import result_storage_service
from app.workflow_engine.base import BaseNode
from app.workflow_engine.enums import PortKind, RunStatus
from app.workflow_engine.models import ArtifactRecord, NodeExecutionResult, NodeSpec, PortSpec
from app.weatherengine.client import OpenMeteoClient
from app.weatherengine.constants import WEATHER_LAYER_SPECS
from app.weatherengine.nodes._utils import get_weather_engine_service
from app.weatherengine.tile_service import _grid_data_for_hour, tile_bbox, zoom_to_resolution
from shared.contracts.api_contracts import ResultKind

logger = logging.getLogger(__name__)


class WeatherTileRenderNode(BaseNode):
    """按 z/x/y/hour 渲染单个天气瓦片。"""

    node_type: str = "weather_tile_render"

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        try:
            layer_id = str(inputs.get("layer_id", "wind-field"))
            z = int(inputs.get("z", 0))
            x = int(inputs.get("x", 0))
            y = int(inputs.get("y", 0))
            hour = int(inputs.get("hour", 0))
            model = inputs.get("model") or settings.weather_default_model

            spec = WEATHER_LAYER_SPECS.get(layer_id)
            if spec is None:
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=[f"Unsupported weather tile layer: {layer_id}"],
                )

            bbox = tile_bbox(z, x, y)
            resolution = zoom_to_resolution(z)

            # 直接调用 OpenMeteoClient 并传入固定分辨率，避免相邻瓦片网格不一致
            client = OpenMeteoClient()
            grid_data, cache_status = client.fetch_grid_forecast(
                bbox=bbox,
                resolution=resolution,
                layer_spec=spec,
                model=model,
                ttl_seconds=settings.weather_cache_ttl_seconds,
                pressure_levels=spec.pressure_levels or None,
            )
            grid_data = _grid_data_for_hour(grid_data, hour)

            service = get_weather_engine_service()
            geojson = service._build_geojson_from_grid(grid_data=grid_data, layer_id=layer_id)

            # 注入完整瓦片元数据，便于前端调试与结果校验
            geojson["_tile_meta"] = {
                "layer_id": layer_id,
                "z": z,
                "x": x,
                "y": y,
                "hour": hour,
                "model": model,
                "resolution": resolution,
                "bbox": bbox.model_dump(mode="json"),
                "feature_count": len(geojson.get("features", [])),
                "upstream_cache_status": cache_status,
            }

            logger.info(
                "[WeatherTileRenderNode] generated layer=%s z=%d x=%d y=%d hour=%d "
                "resolution=%.2f features=%d cache=%s bbox=(%.4f,%.4f,%.4f,%.4f)",
                layer_id, z, x, y, hour, resolution,
                len(geojson.get("features", [])), cache_status,
                bbox.west, bbox.south, bbox.east, bbox.north,
            )

            artifact = self._store_geojson_artifact(geojson)

            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.completed,
                outputs={
                    "geojson": geojson,
                    "tile_meta": geojson["_tile_meta"],
                },
                artifacts=[artifact] if artifact else [],
            )
        except Exception as exc:
            logger.exception("[WeatherTileRenderNode] failed")
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.failed,
                warnings=[f"WeatherTileRenderNode failed: {exc}"],
            )

    def _store_geojson_artifact(self, geojson: dict[str, Any]) -> ArtifactRecord | None:
        run_id = self.context.metadata.get("workflow_run_id", self.context.run_id)
        try:
            ref = result_storage_service.create_artifact_result_ref(
                run_id=run_id,
                result_id=f"weather-tile-{self.spec.node_id}",
                result_kind=ResultKind.file,
                title="Weather Tile GeoJSON",
                mime_type="application/geo+json",
                updated_at=datetime.now(timezone.utc),
                payload=geojson,
            )
            return ArtifactRecord(
                artifact_id=ref.resource_key or "",
                workflow_run_id=run_id,
                node_id=self.spec.node_id,
                artifact_type="weather_tile_geojson",
                storage_uri=ref.resource_url or "",
                content_type="application/geo+json",
            )
        except Exception as exc:
            logger.warning("Failed to store tile GeoJSON artifact: %s", exc)
            return None

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="weather_tile_render",
            node_type="weather_tile_render",
            input_ports=[
                PortSpec(name="layer_id", kind=PortKind.value, required=True),
                PortSpec(name="z", kind=PortKind.value, required=True),
                PortSpec(name="x", kind=PortKind.value, required=True),
                PortSpec(name="y", kind=PortKind.value, required=True),
                PortSpec(name="hour", kind=PortKind.value, required=False),
                PortSpec(name="model", kind=PortKind.value, required=False),
            ],
            output_ports=[
                PortSpec(name="geojson", kind=PortKind.geojson),
                PortSpec(name="tile_meta", kind=PortKind.data),
            ],
        )
