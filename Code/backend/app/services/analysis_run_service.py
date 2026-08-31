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


def _assert_path_under_allowed_roots(path_str: str) -> Path:
    """Reject client path injection outside data / imports / output roots."""
    from app.core.config import settings
    from app.data_io.services.paths import IMPORTS_DIR

    candidate = Path(path_str).expanduser()
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise AnalysisRunError(f"非法路径: {path_str}") from exc

    roots: list[Path] = []
    for raw in (
        settings.data_root,
        settings.output_root,
        str(IMPORTS_DIR),
    ):
        if not raw:
            continue
        p = Path(raw)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / p
        try:
            roots.append(p.resolve(strict=False))
        except OSError:
            continue
    if not roots:
        raise AnalysisRunError("服务器未配置数据根，拒绝路径参数")
    for root in roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise AnalysisRunError("路径不在允许的数据目录内")


def resolve_imported_vector_geojson(backend_layer_id: str) -> Path:
    from app.data_io.services.paths import IMPORTS_DIR

    layer_id = str(backend_layer_id or "").strip()
    if not layer_id or "/" in layer_id or "\\" in layer_id or ".." in layer_id:
        raise AnalysisRunError("非法导入矢量图层 id")
    path = (IMPORTS_DIR / layer_id / "data.geojson").resolve(strict=False)
    _assert_path_under_allowed_roots(str(path))
    if not path.is_file():
        raise AnalysisRunError(f"导入矢量层无 data.geojson: {layer_id}")
    return path


def _param_or_bbox(
    params: dict[str, Any],
    key: str,
    bbox_value: float | None,
) -> float | None:
    raw = params.get(key, bbox_value)
    if raw is None:
        return bbox_value
    if isinstance(raw, str) and not raw.strip():
        return bbox_value
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise AnalysisRunError(f"裁剪参数 {key} 无效: {raw!r}") from exc


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
        elif tool_id == "gis.reclassify" and ntype == "gis/reclassify":
            for key in ("remap_table", "nodata_value"):
                if key in params and params[key] is not None:
                    props[key] = params[key]
        elif tool_id == "gis.clip" and ntype == "preprocess/clip":
            if "buffer_meters" in params and params["buffer_meters"] is not None:
                props["buffer_meters"] = params["buffer_meters"]
        elif tool_id == "gis.contour" and ntype == "gis/contour":
            for key in ("interval", "band"):
                if key in params and params[key] is not None:
                    props[key] = params[key]
            if "smoothing" in params and params["smoothing"] is not None:
                props["smoothing"] = str(params["smoothing"]).lower() == "true"
        elif tool_id == "gis.slope_aspect" and ntype == "gis/slope_aspect":
            for key in ("z_unit", "algorithm"):
                if key in params and params[key] is not None:
                    props[key] = params[key]
        elif tool_id == "gis.raster_calc" and ntype == "gis/raster_calculator":
            for key in ("expression", "nodata_handling"):
                if key in params and params[key] is not None:
                    props[key] = params[key]
        elif tool_id == "gis.vector_to_raster" and ntype == "gis/vector_to_raster":
            for key in ("attribute_field", "resolution", "fill_value"):
                if key in params and params[key] is not None:
                    props[key] = params[key]
        elif tool_id == "gis.raster_to_vector" and ntype == "gis/raster_to_vector":
            for key in ("band", "threshold", "simplify_tolerance"):
                if key in params and params[key] is not None:
                    props[key] = params[key]
        elif tool_id == "gis.watershed" and ntype == "gis/watershed":
            for key in ("fill_threshold", "max_dem_pixels"):
                if key in params and params[key] is not None:
                    props[key] = params[key]


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


def _validate_tool_params(
    tool_id: str,
    param_schema: list[Any],
    params: dict[str, Any],
) -> None:
    """Validate user-supplied params against the tool's declared param_schema.

    Checks ``min`` / ``max`` bounds for numeric fields and ``options``
    enumeration for fields with a fixed choice set.  Raises
    :class:`AnalysisRunError` on violation — this is a fail-closed gate
    before params are injected into the workflow graph.
    """
    schema_map: dict[str, Any] = {}
    for field in param_schema:
        if hasattr(field, "key"):
            schema_map[field.key] = field
        elif isinstance(field, dict):
            key = field.get("key")
            if key:
                schema_map[key] = field

    for key, value in params.items():
        spec = schema_map.get(key)
        if spec is None:
            continue  # unknown keys are ignored — workflow may inject extras

        # Resolve attributes from either a Pydantic model or a plain dict
        def _get(attr: str) -> Any:
            if hasattr(spec, attr):
                return getattr(spec, attr)
            return spec.get(attr) if isinstance(spec, dict) else None

        field_min = _get("min")
        field_max = _get("max")
        field_options = _get("options")

        if value is None:
            continue

        # Options (enum) check — coerce to str for comparison
        if field_options:
            str_value = str(value)
            if str_value not in [str(o) for o in field_options]:
                raise AnalysisRunError(
                    f"参数 '{key}' 的值 '{str_value}' 不在允许选项中: {field_options}"
                )
            continue

        # Numeric bounds check (only for int/float values)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if field_min is not None and value < field_min:
                raise AnalysisRunError(
                    f"参数 '{key}' 的值 {value} 小于最小值 {field_min}"
                )
            if field_max is not None and value > field_max:
                raise AnalysisRunError(
                    f"参数 '{key}' 的值 {value} 大于最大值 {field_max}"
                )


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
        primary_path = str(_assert_path_under_allowed_roots(str(params["input_path"])))

    if tool.tool_id == "gis.buffer":
        if req.geojson_path:
            primary_path = str(_assert_path_under_allowed_roots(str(req.geojson_path)))
        elif params.get("imported_vector_layer_id"):
            primary_path = str(
                resolve_imported_vector_geojson(str(params["imported_vector_layer_id"]))
            )
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
                nodes,
                dataset_key="zones_path",
                path=str(_assert_path_under_allowed_roots(str(req.zones_geojson_path))),
            )
        elif params.get("zones_imported_vector_layer_id"):
            _inject_node_path(
                nodes,
                dataset_key="zones_path",
                path=str(
                    resolve_imported_vector_geojson(
                        str(params["zones_imported_vector_layer_id"])
                    )
                ),
            )
    elif tool.tool_id == "gis.vector_to_raster":
        if req.geojson_path:
            primary_path = str(_assert_path_under_allowed_roots(str(req.geojson_path)))
        elif params.get("imported_vector_layer_id"):
            primary_path = str(
                resolve_imported_vector_geojson(str(params["imported_vector_layer_id"]))
            )
        if not primary_path:
            raise AnalysisRunError(
                "矢量转栅格需要矢量输入（导入矢量层或 geojson_path）"
            )
        _inject_node_path(nodes, dataset_key="input_path", path=primary_path)
    elif tool.tool_id in {
        "gis.clip",
        "gis.reclassify",
        "gis.contour",
        "gis.slope_aspect",
        "gis.raster_calc",
        "gis.raster_to_vector",
        "gis.watershed",
    }:
        if not primary_path:
            raise AnalysisRunError(f"{tool.title}需要栅格输入（overlay_layer_id）")
        _inject_node_path(nodes, dataset_key="input_path", path=primary_path)
        if tool.tool_id == "gis.watershed":
            pour_path: str | None = None
            if req.map_point is not None:
                pour_path = _write_point_geojson(req.map_point.lng, req.map_point.lat)
            elif params.get("imported_vector_layer_id"):
                pour_path = str(
                    resolve_imported_vector_geojson(
                        str(params["imported_vector_layer_id"])
                    )
                )
            elif req.geojson_path:
                pour_path = str(_assert_path_under_allowed_roots(str(req.geojson_path)))
            if pour_path:
                _inject_node_path(nodes, dataset_key="pour_points_path", path=pour_path)
        if tool.tool_id == "gis.clip":
            west = _param_or_bbox(params, "west", req.bbox.west if req.bbox else None)
            south = _param_or_bbox(
                params, "south", req.bbox.south if req.bbox else None
            )
            east = _param_or_bbox(params, "east", req.bbox.east if req.bbox else None)
            north = _param_or_bbox(
                params, "north", req.bbox.north if req.bbox else None
            )
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

    _validate_tool_params(tool.tool_id, tool.param_schema, params)
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


def submit_analysis_run(
    req: AnalysisRunRequest,
    *,
    user_id: int | None = None,
    role: str | None = None,
) -> WorkflowAcceptedResponse:
    payload = build_analysis_submit_request(req)
    return submission_service.submit_workflow(payload, user_id=user_id, role=role)
