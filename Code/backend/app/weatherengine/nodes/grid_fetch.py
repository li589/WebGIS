"""网格数据获取节点，支持批量请求和懒加载。"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.weatherengine.client import OpenMeteoClient
from app.weatherengine.constants import WEATHER_LAYER_SPECS
from app.workflow_engine.base import BaseNode
from app.workflow_engine.enums import PortKind, RunStatus
from app.workflow_engine.models import NodeExecutionResult, NodeSpec, PortSpec
from app.weatherengine.nodes._utils import compute_dynamic_resolution, coerce_float, resolve_bbox

logger = logging.getLogger(__name__)


class GridFetchNode(BaseNode):
    """网格数据获取节点，支持批量请求和懒加载。

    该节点从 Open-Meteo API 批量获取网格化天气预报数据，
    替代单点请求，提供更丰富的网格数据供后续渲染节点使用。

    输入：
    - latitude: 中心纬度
    - longitude: 中心经度
    - layer_id: 图层类型（如 wind-field, temperature 等）
    - resolution: 网格分辨率（度），默认 0.25
    - viewport_bbox: 可选，视口边界框（优先使用）

    输出：
    - grid_data: 网格化天气数据
    - grid_rows: 网格行数
    - grid_cols: 网格列数
    - bbox: 网格边界框
    - cache_status: 缓存状态（hit/miss）
    """

    node_type: str = "weather_grid_fetch"

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        try:
            # 1. 解析经纬度输入
            latitude = coerce_float(inputs.get("latitude"))
            longitude = coerce_float(inputs.get("longitude"))

            if latitude is None or longitude is None:
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=["GridFetchNode 缺少必需输入: latitude/longitude"],
                )

            # 2. 解析渲染范围（优先级：viewport_bbox > bbox > 默认）
            bbox = resolve_bbox(inputs, latitude, longitude)

            # 3. 获取图层规格
            layer_id = inputs.get("layer_id", "wind-field")
            layer_spec = WEATHER_LAYER_SPECS.get(layer_id)

            if layer_spec is None:
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=[f"Unknown layer_id: {layer_id}"],
                )

            # 4. 调用批量 API 获取网格数据
            client = OpenMeteoClient()
            # 动态分辨率：未显式指定 resolution 时，根据 bbox 范围自动选择
            # 避免大 bbox（如全球视图）导致网格点数过多、API 请求超时
            explicit_resolution = inputs.get("resolution")
            if explicit_resolution is not None:
                resolution = float(explicit_resolution)
            else:
                resolution = compute_dynamic_resolution(bbox)

            grid_data, cache_status = client.fetch_grid_forecast(
                bbox=bbox,
                resolution=resolution,
                layer_spec=layer_spec,
                model=settings.weather_default_model,
                ttl_seconds=settings.weather_cache_ttl_seconds,
                pressure_levels=layer_spec.pressure_levels if layer_spec else None,
            )

            logger.info(
                "[GridFetchNode] Fetched grid data: layer=%s rows=%d cols=%d resolution=%.2f bbox=(%.2f,%.2f,%.2f,%.2f) cache=%s",
                layer_id,
                grid_data["grid"]["rows"],
                grid_data["grid"]["cols"],
                resolution,
                bbox.west, bbox.south, bbox.east, bbox.north,
                cache_status,
            )

            # 5. 返回网格数据（供后续渲染节点使用）
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
            ],
        )
