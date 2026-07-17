"""天气瓦片渲染节点。

按标准 Web Mercator z/x/y 渲染单个瓦片 GeoJSON，供 workflow 使用。
生成逻辑委托 WeatherTileService，与 /unified-tiles 热路径共用缓存与网格语义。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.result_storage import result_storage_service
from app.workflow_engine.base import BaseNode
from app.workflow_engine.enums import PortKind, RunStatus
from app.workflow_engine.models import ArtifactRecord, NodeExecutionResult, NodeSpec, PortSpec
from app.weatherengine.tile_service import get_weather_tile_service
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
            model = inputs.get("model")
            provider_id = inputs.get("provider_id") or inputs.get("provider")

            tile_service = get_weather_tile_service()
            geojson, cache_status = tile_service.get_or_generate_tile_sync(
                layer_id=layer_id,
                z=z,
                x=x,
                y=y,
                hour=hour,
                model=model,
                provider_id=provider_id,
            )

            tile_meta = dict(geojson.get("_tile_meta") or {})
            tile_meta["service_cache_status"] = cache_status

            logger.info(
                "[WeatherTileRenderNode] generated layer=%s z=%d x=%d y=%d hour=%d "
                "features=%d cache=%s service_cache=%s",
                layer_id,
                z,
                x,
                y,
                hour,
                len(geojson.get("features", [])),
                tile_meta.get("upstream_cache_status"),
                cache_status,
            )

            artifact = self._store_geojson_artifact(geojson)

            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.completed,
                outputs={
                    "geojson": geojson,
                    "tile_meta": tile_meta,
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
                PortSpec(name="provider_id", kind=PortKind.value, required=False, description="天气源 Provider ID，可选"),
            ],
            output_ports=[
                PortSpec(name="geojson", kind=PortKind.geojson),
                PortSpec(name="tile_meta", kind=PortKind.data),
            ],
        )
