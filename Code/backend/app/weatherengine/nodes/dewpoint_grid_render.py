"""Dewpoint grid render node — GeoJSON from grid or point fallback (N1 薄壳)."""

from __future__ import annotations

from app.workflow_engine.enums import PortKind
from app.workflow_engine.models import NodeSpec, PortSpec
from app.weatherengine.nodes.scalar_grid_render import ScalarGridRenderNode


class DewpointGridRenderNode(ScalarGridRenderNode):
    """露点网格渲染节点。"""

    node_type: str = "weather_dewpoint_grid"
    _layer_id: str = "dewpoint"
    _metric_key: str = "dew_point_2m"
    _unit: str = "C"
    _point_unit: str = "°C"
    _base_field: str = "dew_point_2m"
    _skip_none: bool = True
    _artifact_type: str = "dewpoint_geojson"
    _result_prefix: str = "dewpoint"
    _display_title: str = "Dewpoint Grid GeoJSON"
    _node_label: str = "DewpointGridRenderNode"

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
