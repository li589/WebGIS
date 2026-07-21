"""网格数据获取节点，支持批量请求和懒加载。"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.weatherengine.default_model import weather_default_model
from app.weatherengine.constants import WEATHER_LAYER_SPECS
from app.weatherengine.fetch_gateway import fetch_grid_forecast
from app.workflow_engine.base import BaseNode
from app.workflow_engine.enums import PortKind, RunStatus
from app.workflow_engine.models import NodeExecutionResult, NodeSpec, PortSpec
from app.weatherengine.nodes._utils import compute_dynamic_resolution, coerce_float, resolve_bbox

logger = logging.getLogger(__name__)


class GridFetchNode(BaseNode):
    """网格数据获取节点（经 fetch_gateway / Registry）。

    输入：
    - latitude / longitude: 中心点
    - layer_id: 图层类型
    - resolution: 网格分辨率（度），可选
    - model: 气象模型，可选
    - viewport_bbox / bbox: 范围

    输出：
    - grid_data / grid_rows / grid_cols / bbox / cache_status / layer_id
    """

    node_type: str = "weather_grid_fetch"

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        try:
            latitude = coerce_float(inputs.get("latitude"))
            longitude = coerce_float(inputs.get("longitude"))

            if latitude is None or longitude is None:
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=["GridFetchNode 缺少必需输入: latitude/longitude"],
                )

            bbox = resolve_bbox(inputs, latitude, longitude)

            layer_id = inputs.get("layer_id", "wind-field")
            layer_spec = WEATHER_LAYER_SPECS.get(layer_id)

            if layer_spec is None:
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=[f"Unknown layer_id: {layer_id}"],
                )

            explicit_resolution = inputs.get("resolution")
            if explicit_resolution is not None:
                resolution = float(explicit_resolution)
            else:
                resolution = compute_dynamic_resolution(bbox)

            model = inputs.get("model") or weather_default_model()
            provider_id = inputs.get("provider_id") or inputs.get("provider")

            grid_data, cache_status, resolved_provider = fetch_grid_forecast(
                layer_id=layer_id,
                bbox=bbox,
                resolution=resolution,
                model=model,
                layer_spec=layer_spec,
                provider_id=provider_id,
            )

            logger.info(
                "[GridFetchNode] Fetched grid data: layer=%s rows=%d cols=%d resolution=%.2f "
                "bbox=(%.2f,%.2f,%.2f,%.2f) cache=%s provider=%s",
                layer_id,
                grid_data["grid"]["rows"],
                grid_data["grid"]["cols"],
                resolution,
                bbox.west,
                bbox.south,
                bbox.east,
                bbox.north,
                cache_status,
                resolved_provider,
            )

            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.completed,
                outputs={
                    "grid_data": grid_data,
                    "grid_rows": grid_data["grid"]["rows"],
                    "grid_cols": grid_data["grid"]["cols"],
                    "bbox": grid_data["grid"]["bbox"],
                    "cache_status": cache_status,
                    "layer_id": layer_id,
                    "provider_id": resolved_provider,
                },
            )

        except Exception as exc:
            logger.exception(f"[GridFetchNode] Failed: {exc}")
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.failed,
                warnings=[f"GridFetchNode failed: {exc}"],
            )

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id=GridFetchNode.node_type,
            node_type=GridFetchNode.node_type,
            input_ports=[
                PortSpec(name="latitude", kind=PortKind.value, description="中心纬度"),
                PortSpec(name="longitude", kind=PortKind.value, description="中心经度"),
                PortSpec(name="layer_id", kind=PortKind.value, description="图层类型"),
                PortSpec(name="resolution", kind=PortKind.value, description="网格分辨率（度）"),
                PortSpec(name="model", kind=PortKind.value, required=False, description="气象模型，可选"),
                PortSpec(name="provider_id", kind=PortKind.value, required=False, description="天气源 Provider ID（钉源），可选"),
                PortSpec(name="viewport_bbox", kind=PortKind.data, required=False, description="视口边界框"),
                PortSpec(name="bbox", kind=PortKind.data, required=False, description="空间过滤器边界框"),
            ],
            output_ports=[
                PortSpec(name="grid_data", kind=PortKind.data, description="网格化天气数据"),
                PortSpec(name="grid_rows", kind=PortKind.value, description="网格行数"),
                PortSpec(name="grid_cols", kind=PortKind.value, description="网格列数"),
                PortSpec(name="bbox", kind=PortKind.data, description="网格边界框"),
                PortSpec(name="cache_status", kind=PortKind.value, description="缓存状态"),
                PortSpec(name="layer_id", kind=PortKind.value, description="图层类型"),
                PortSpec(name="provider_id", kind=PortKind.value, description="实际使用的天气源 Provider ID"),
            ],
        )
