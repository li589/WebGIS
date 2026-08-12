"""Build and submit InfoPanel analysis runs from tool_id + layer binding."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services import workflow_definition_service as wds
from app.services.analysis_tool_catalog import get_tool
from app.services.overlay_registry import get_overlay_spec
from app.services.workflow.service_container import submission_service
from shared.contracts.api_contracts import (
    AlgorithmWorkflowRequest,
    AnalysisRunRequest,
    ResultKind,
    WorkflowAcceptedResponse,
    WorkflowCommandType,
    WorkflowResourceProfile,
    WorkflowSubmitRequest,
)

logger = logging.getLogger(__name__)


class AnalysisRunError(ValueError):
    """User-facing analysis submit error."""


def _definition_graph_body(definition: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in definition.items() if k != "_meta"}


def resolve_overlay_source_path(overlay_layer_id: str) -> Path:
    spec = get_overlay_spec(overlay_layer_id)
    if spec is None:
        raise AnalysisRunError(f"未找到 overlay 图层: {overlay_layer_id}")
    path = spec.resolve_source_path(None)
    if path is None or not path.is_file():
        raise AnalysisRunError(
            f"overlay 图层无本地栅格文件: {overlay_layer_id}（请确认已导入并完成 CRS）"
        )
    return path


def _inject_node_path(
    nodes: list[dict[str, Any]], *, dataset_key: str, path: str
) -> None:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        props = node.get("properties")
        if not isinstance(props, dict):
            continue
        if str(props.get("dataset_key") or "") == dataset_key:
            props["path"] = path
            return
    # Fallback: first data/source
    for node in nodes:
        if isinstance(node, dict) and str(node.get("type") or "") == "data/source":
            props = node.setdefault("properties", {})
            if isinstance(props, dict):
                props["path"] = path
            return


def _inject_bbox(
    nodes: list[dict[str, Any]],
    *,
    west: float,
    south: float,
    east: float,
    north: float,
    buffer_meters: float = 0.0,
) -> None:
    bbox = [west, south, east, north]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        props = node.setdefault("properties", {})
        if not isinstance(props, dict):
            continue
        if ntype == "data/bbox":
            props["west"] = west
            props["south"] = south
            props["east"] = east
            props["north"] = north
            props["crs"] = "EPSG:4326"
        elif ntype == "preprocess/clip":
            props["bbox"] = bbox
            props["buffer_meters"] = buffer_meters


def _inject_tool_params(
    nodes: list[dict[str, Any]],
    *,
    tool_id: str,
    params: dict[str, Any],
) -> None:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        props = node.setdefault("properties", {})
        if not isinstance(props, dict):
            continue
        if tool_id == "gis.buffer" and ntype == "gis/buffer_analysis":
            for key in ("distance", "distance_unit", "segments"):
                if key in params and params[key] is not None:
                    props[key] = params[key]
        elif tool_id == "gis.zonal_stats" and ntype == "gis/zonal_statistics":
            for key in ("statistic", "band", "all_touched"):
                if key in params and params[key] is not None:
                    props[key] = params[key]
        elif tool_id == "stats.histogram" and ntype == "stats/histogram":
            for key in ("bins", "band", "density", "variable", "nodata"):
                if key in params and params[key] is not None:
                    props[key] = params[key]
        elif tool_id == "gis.reclassify" and ntype == "gis/reclassify":
            for key in ("remap_table", "nodata_value"):
                if key in params and params[key] is not None:
                    props[key] = params[key]
        elif tool_id == "gis.clip" and ntype == "preprocess/clip":
            if "buffer_meters" in params and params["buffer_meters"] is not None:
                props["buffer_meters"] = params["buffer_meters"]


def _write_point_geojson(lng: float, lat: float) -> str:
    """Write ephemeral point FeatureCollection under backend .data for buffer tool."""
    from app.core.config import settings

    root = Path(settings.data_root or ".data")
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    out_dir = root / "_runtime" / "analysis_points"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AnalysisRunError(f"无法创建临时目录: {exc}") from exc
    path = out_dir / f"point_{uuid4().hex[:10]}.geojson"
    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": {},
            }
        ],
    }
    try:
        path.write_text(json.dumps(gj), encoding="utf-8")
    except OSError as exc:
        raise AnalysisRunError(f"无法写入临时点文件: {exc}") from exc
    return str(path)


def build_analysis_submit_request(req: AnalysisRunRequest) -> WorkflowSubmitRequest:
    tool = get_tool(req.tool_id)
    if tool is None:
        raise AnalysisRunError(f"未知分析工具: {req.tool_id}")

    template_id = tool.workflow_template_id
    definition = wds.get_definition(template_id)
    if definition is None:
        raise AnalysisRunError(f"工作流模板不存在: {template_id}")

    graph = copy.deepcopy(_definition_graph_body(definition))
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        raise AnalysisRunError(f"模板无节点: {template_id}")

    params = dict(req.params or {})
    layer_id = str(req.layer_id or "").strip()
    exclusivity = f"{layer_id}:{tool.tool_id}"

    # Resolve primary raster/vector input from overlay when provided
    primary_path: str | None = None
    if req.overlay_layer_id:
        primary_path = str(resolve_overlay_source_path(req.overlay_layer_id))
    elif params.get("input_path"):
        primary_path = str(params["input_path"])

    if tool.tool_id == "gis.buffer":
        if req.geojson_path:
            primary_path = str(req.geojson_path)
        elif req.map_point is not None:
            primary_path = _write_point_geojson(req.map_point.lng, req.map_point.lat)
        if not primary_path:
            raise AnalysisRunError(
                "缓冲分析需要矢量路径（geojson_path）、导入矢量层或地图选点"
            )
        _inject_node_path(nodes, dataset_key="input_path", path=primary_path)
    elif tool.tool_id == "gis.zonal_stats":
        if not primary_path:
            raise AnalysisRunError("分区统计需要值栅格（overlay_layer_id）")
        _inject_node_path(nodes, dataset_key="input_path", path=primary_path)
        zones_id = str(
            params.get("zones_overlay_layer_id") or req.zones_overlay_layer_id or ""
        ).strip()
        if zones_id:
            zones_path = str(resolve_overlay_source_path(zones_id))
            _inject_node_path(nodes, dataset_key="zones_path", path=zones_path)
        elif req.zones_geojson_path:
            _inject_node_path(
                nodes, dataset_key="zones_path", path=str(req.zones_geojson_path)
            )
    elif tool.tool_id in {"gis.clip", "stats.histogram", "gis.reclassify"}:
        if not primary_path:
            raise AnalysisRunError(f"{tool.title}需要栅格输入（overlay_layer_id）")
        _inject_node_path(nodes, dataset_key="input_path", path=primary_path)
        if tool.tool_id == "gis.clip":
            west = params.get("west", req.bbox.west if req.bbox else None)
            south = params.get("south", req.bbox.south if req.bbox else None)
            east = params.get("east", req.bbox.east if req.bbox else None)
            north = params.get("north", req.bbox.north if req.bbox else None)
            if None in (west, south, east, north):
                raise AnalysisRunError(
                    "裁剪需要 bbox（west/south/east/north 或请求 bbox）"
                )
            _inject_bbox(
                nodes,
                west=float(west),
                south=float(south),
                east=float(east),
                north=float(north),
                buffer_meters=float(params.get("buffer_meters") or 0),
            )

    _inject_tool_params(nodes, tool_id=tool.tool_id, params=params)

    profile = tool.resource_profile
    try:
        resource_profile = WorkflowResourceProfile(profile)
    except ValueError:
        resource_profile = WorkflowResourceProfile.standard

    requested: list[ResultKind] = [ResultKind.json, ResultKind.table, ResultKind.chart]
    if req.show_on_map and "map_layer" in tool.outputs:
        requested.append(ResultKind.map_layer)

    algo_params = {
        k: v
        for k, v in params.items()
        if k
        not in {
            "input_path",
            "zones_overlay_layer_id",
            "west",
            "south",
            "east",
            "north",
        }
    }

    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label=f"analysis:{tool.tool_id}",
        layer_id=layer_id or None,
        resource_profile=resource_profile,
        parameters={
            "analysis_tool_id": tool.tool_id,
            "analysis_exclusivity_key": exclusivity,
            "source_overlay_layer_id": req.overlay_layer_id,
        },
        algorithm_request=AlgorithmWorkflowRequest(
            workflow_name=template_id,
            workflow_definition=graph,
            algorithm_params=algo_params,
            datasource_selection=({"input_path": primary_path} if primary_path else {}),
            tags={
                "analysis_tool_id": tool.tool_id,
                "ui_panel": "true",
            },
        ),
        requested_outputs=requested,
    )


def submit_analysis_run(req: AnalysisRunRequest) -> WorkflowAcceptedResponse:
    payload = build_analysis_submit_request(req)
    return submission_service.submit_workflow(payload)
