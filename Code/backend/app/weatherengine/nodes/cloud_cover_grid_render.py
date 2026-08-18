"""Cloud cover grid render node — GeoJSON from grid or point fallback (N1 薄壳)."""

from __future__ import annotations

from app.workflow_engine.enums import PortKind
from app.workflow_engine.models import NodeSpec, PortSpec
from app.weatherengine.nodes.scalar_grid_render import ScalarGridRenderNode


class CloudCoverGridRenderNode(ScalarGridRenderNode):
    """云量网格渲染节点。"""

    node_type: str = "weather_cloud_cover_grid"
    _layer_id: str = "cloud-cover"
    _metric_key: str = "cloud_cover"
    _unit: str = "%"
    _point_unit: str = "%"
    _base_field: str = "cloud_cover"
    _artifact_type: str = "cloud_cover_geojson"
    _result_prefix: str = "cloud-cover"
    _display_title: str = "Cloud Cover Grid GeoJSON"
    _node_label: str = "CloudCoverGridRenderNode"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id=CloudCoverGridRenderNode.node_type,
            node_type=CloudCoverGridRenderNode.node_type,
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
                    description="图层 ID，默认 cloud-cover",
                ),
            ],
            output_ports=[
                PortSpec(
                    name="geojson", kind=PortKind.data, description="云量 GeoJSON"
                ),
            ],
        )
