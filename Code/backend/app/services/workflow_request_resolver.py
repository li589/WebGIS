from __future__ import annotations

from contextlib import contextmanager, suppress
from functools import lru_cache
import importlib
import logging
from pathlib import Path
import sys
import threading
from typing import Any
from collections.abc import Iterator

from app.core.config import settings
from app.services.engine_request_registry import (
    get_engine_populator,
    register_engine_populator,
)
from app.services.layer_catalog import get_layer_descriptor
from shared.contracts.api_contracts import WorkflowCommandType, WorkflowSubmitRequest

logger = logging.getLogger(__name__)

_ALGORITHM_ENTRY_KEYS: tuple[str, ...] = (
    "module_name",
    "workflow_name",
    "workflow_definition",
)
_GEE_ENTRY_KEYS: tuple[str, ...] = ("workflow", "manifest_uri")
_WEATHER_ENTRY_KEYS: tuple[str, ...] = ("workflow",)


def normalize_workflow_submit_request(
    payload: WorkflowSubmitRequest,
) -> WorkflowSubmitRequest:
    """按 layer catalog 元数据补齐 bridge 所需请求字段。

    当前前端只提交 `layer_id + parameters + map_context`，而 Python provider bridge
    需要 `algorithm_request.module_name/workflow_name/workflow_definition` 才会接管。
    这里优先使用后端 `layer_catalog` 作为执行事实源，避免前端维护第二份 workflow 元数据。

    引擎分发通过 engine_request_registry 注册表完成，新增引擎只需注册 populator。
    """

    if payload.command_type != WorkflowCommandType.analysis:
        return payload

    layer_id = payload.layer_id or payload.map_context.active_layer_id
    if not layer_id:
        return payload

    descriptor = get_layer_descriptor(layer_id)
    if descriptor is None or not descriptor.engine:
        return payload

    populator = get_engine_populator(descriptor.engine)
    if populator is None:
        return payload

    return populator.populate(payload=payload, layer_id=layer_id, descriptor=descriptor)


def describe_python_provider_resolution(
    payload: WorkflowSubmitRequest,
) -> dict[str, Any] | None:
    """公开 API：委托给 python_provider populator。"""
    populator = get_engine_populator("python_provider")
    if populator is None:
        return None
    return populator.describe_resolution(payload)


def _describe_python_provider_resolution_impl(
    payload: WorkflowSubmitRequest,
) -> dict[str, Any] | None:
    layer_id = payload.layer_id or payload.map_context.active_layer_id
    if not layer_id:
        return None

    descriptor = get_layer_descriptor(layer_id)
    if (
        descriptor is None
        or descriptor.engine != "python_provider"
        or not descriptor.module_name
    ):
        return None

    algorithm_request = _normalize_algorithm_request(payload.algorithm_request)
    datasource_selection = _normalize_request(
        algorithm_request.get("datasource_selection")
    )
    explicit_data_access_requests = _normalize_request(
        datasource_selection.get("_data_access_requests")
    )
    default_datasets: list[dict[str, Any]] = []
    unresolved_default_datasets: list[dict[str, Any]] = []

    for dataset_name, candidates in descriptor.default_data_access_sources.items():
        resolution = _resolve_data_access_candidates(candidates)
        dataset_summary = {
            "dataset_name": dataset_name,
            "resolved_uri": resolution["resolved_uri"],
            "candidate_sources": [item["source"] for item in resolution["candidates"]],
            "candidates": resolution["candidates"],
        }
        default_datasets.append(dataset_summary)
        if resolution["resolved_uri"] is None:
            unresolved_default_datasets.append(dataset_summary)

    return {
        "layer_id": layer_id,
        "layer_status": descriptor.status,
        "module_name": descriptor.module_name,
        "workflow_entry_name": descriptor.workflow_name or descriptor.module_name,
        "task_type": algorithm_request.get("task_type")
        or descriptor.default_task_type
        or descriptor.module_name,
        "explicit_data_access_datasets": sorted(explicit_data_access_requests.keys()),
        "default_datasets": default_datasets,
        "unresolved_default_datasets": unresolved_default_datasets,
    }


def describe_layer_run_readiness(layer_id: str) -> dict[str, Any] | None:
    descriptor = get_layer_descriptor(layer_id)
    if descriptor is None:
        return None

    readiness = "ready"
    notes: list[str] = list(descriptor.run_readiness_notes)
    summary: str | None = descriptor.run_readiness_summary

    if descriptor.status == "sample":
        notes.append("当前图层为样板 provider 链路，可运行但结果仅用于联调/演示。")
        summary = summary or "样板 provider 可运行，但不代表正式生产数据。"
    elif descriptor.status == "placeholder":
        readiness = "blocked"
        notes.append("图层仍处于占位状态，真实数据源尚未接入。")

    # 引擎特定就绪检查通过注册表分发
    unresolved_default_datasets: list[dict[str, Any]] = []
    if descriptor.engine:
        populator = get_engine_populator(descriptor.engine)
        if populator is not None:
            engine_result = populator.describe_readiness(descriptor)
            if engine_result:
                unresolved_default_datasets = engine_result.get(
                    "unresolved_default_datasets", []
                )

    if unresolved_default_datasets:
        readiness = "blocked"
        for item in unresolved_default_datasets:
            candidate_text = ", ".join(item["candidate_sources"]) or "未提供候选源"
            notes.append(
                f"缺少默认数据集 {item['dataset_name']}；已检查：{candidate_text}"
            )

    if unresolved_default_datasets:
        dataset_names = "、".join(
            item["dataset_name"] for item in unresolved_default_datasets
        )
        summary = f"默认数据源未就绪：{dataset_names}"
    elif summary is None and readiness == "blocked" and notes:
        summary = notes[0]

    return {
        "run_readiness": readiness,
        "run_readiness_summary": summary,
        "run_readiness_notes": notes,
        "unresolved_default_datasets": unresolved_default_datasets,
    }


@lru_cache(maxsize=1)
def _load_module_template_map():
    """加载 Python provider 的 module request templates（含手工表 + 自动推导）。

    返回 {module_name: RequestTemplateSpec} 字典。若 provider root 不存在或导入失败返回空 dict。
    """
    provider_root = Path(settings.python_provider_root)
    if not provider_root.exists():
        return {}
    try:
        with _python_provider_import_path(provider_root):
            deriver = importlib.import_module("contracts.template_deriver")
            return deriver.list_module_templates()
    except Exception:
        logger.debug(
            "Failed to load module templates from python provider", exc_info=True
        )
        return {}


def _get_module_request_template(module_name: str):
    """获取指定 module 的 RequestTemplateSpec，未找到返回 None。"""
    templates = _load_module_template_map()
    return templates.get(module_name)


def _node_props(node: dict[str, Any]) -> dict[str, Any]:
    """统一读取种子节点 properties 或编译节点 params。"""
    props = node.get("properties")
    if isinstance(props, dict) and props:
        return props
    params = node.get("params")
    if isinstance(params, dict) and params:
        return params
    return {}


def _node_module_name(node: dict[str, Any]) -> str:
    """识别节点逻辑类型：data/source、time_range、bbox、omega_sf_fenkuai 等。"""
    node_type = str(node.get("type") or "")
    if node_type.startswith("data/"):
        return node_type.split("/", 1)[-1]
    if node_type.startswith("module/"):
        return node_type.split("/", 1)[-1]
    if node_type.startswith("output/"):
        return node_type.split("/", 1)[-1]
    props = _node_props(node)
    module_name = props.get("module_name")
    if module_name:
        return str(module_name)
    return str(node.get("node_type") or "")


def _extract_time_range_from_nodes(nodes: list[Any] | None):
    """从 data/time_range（或编译后的 time_range 模块）节点提取 TimeRange。"""
    if not nodes:
        return None
    try:
        from datetime import datetime

        from shared.contracts.api_contracts import TimeGranularity, TimeRange

        for node in nodes:
            if not isinstance(node, dict):
                continue
            if _node_module_name(node) != "time_range":
                continue
            props = _node_props(node)
            start_str = props.get("start_at")
            end_str = props.get("end_at")
            if not start_str or not end_str:
                continue
            start_dt = datetime.fromisoformat(str(start_str))
            end_dt = datetime.fromisoformat(str(end_str))
            granularity_str = str(props.get("granularity") or "day")
            try:
                granularity = TimeGranularity(granularity_str)
            except ValueError:
                granularity = TimeGranularity.day
            return TimeRange(start_at=start_dt, end_at=end_dt, granularity=granularity)
    except Exception:
        logger.debug("Failed to extract time_range from nodes", exc_info=True)
    return None


def _extract_time_range_from_seed(workflow_name: str):
    """从工作流种子的 data/time_range 节点提取 TimeRange。

    前端 UI 提交工作流时不带 time_range，Python provider 的 validate_job
    要求 job_request.time_range 必填。这里从种子中读取默认值填充。
    """
    try:
        from app.services.workflow_definition_service import get_definition

        definition = get_definition(workflow_name)
        if not definition:
            return None
        return _extract_time_range_from_nodes(definition.get("nodes"))
    except Exception:
        logger.debug("Failed to extract time_range from seed", exc_info=True)
    return None


def _resolve_missing_time_range(
    *,
    payload: WorkflowSubmitRequest,
    algorithm_request: dict[str, Any],
    descriptor: Any,
):
    """UI 提交常缺 time_range：从画布定义 / entry 名 / 图层种子补齐。"""
    if payload.time_range is not None:
        return None

    workflow_definition = algorithm_request.get("workflow_definition")
    if isinstance(workflow_definition, dict):
        from_nodes = _extract_time_range_from_nodes(workflow_definition.get("nodes"))
        if from_nodes is not None:
            return from_nodes

    tags = algorithm_request.get("tags")
    tag_workflow_id = tags.get("workflow_id") if isinstance(tags, dict) else None
    candidates = (
        algorithm_request.get("workflow_entry_name"),
        algorithm_request.get("workflow_name"),
        tag_workflow_id,
        getattr(descriptor, "workflow_name", None),
    )
    for name in candidates:
        if not name:
            continue
        from_seed = _extract_time_range_from_seed(str(name))
        if from_seed is not None:
            return from_seed
    return None


def _extract_bbox_from_nodes(nodes: list[Any] | None):
    """从 data/bbox（或编译后的 bbox 模块）节点提取 SpatialFilter。"""
    if not nodes:
        return None
    try:
        from shared.contracts.api_contracts import BoundingBox, SpatialFilter

        for node in nodes:
            if not isinstance(node, dict):
                continue
            if _node_module_name(node) != "bbox":
                continue
            props = _node_props(node)
            required = ("west", "south", "east", "north")
            if any(props.get(k) is None for k in required):
                continue
            bbox = BoundingBox(
                west=float(props["west"]),
                south=float(props["south"]),
                east=float(props["east"]),
                north=float(props["north"]),
                crs=str(props.get("crs") or "EPSG:4326"),
            )
            return SpatialFilter(filter_type="bbox", bbox=bbox)
    except Exception:
        logger.debug("Failed to extract bbox from nodes", exc_info=True)
    return None


def _extract_algorithm_params_from_nodes(
    nodes: list[Any] | None,
) -> dict[str, Any] | None:
    """从画布算法模块节点读取 algorithm_params。"""
    if not nodes:
        return None
    skip = {"data_source", "time_range", "bbox", "output_map_layer", "module"}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        module_name = _node_module_name(node)
        node_type = str(node.get("type") or "")
        # 种子：module/*；编译：params.module_name=算法名
        if node_type.startswith("module/") or (
            module_name and module_name not in skip and module_name != "module"
        ):
            props = _node_props(node)
            params = props.get("algorithm_params")
            if isinstance(params, dict) and params:
                return dict(params)
    return None


def _extract_datasource_selection_from_nodes(
    nodes: list[Any] | None,
) -> dict[str, Any]:
    """从 data/source（或编译后的 data_source 模块）提取 datasource_selection。"""
    selection: dict[str, Any] = {}
    if not nodes:
        return selection
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if _node_module_name(node) not in {"source", "data_source"}:
            continue
        props = _node_props(node)
        key = props.get("dataset_key") or props.get("key")
        path = props.get("path") or props.get("uri") or props.get("value")
        if path:
            # Generic analysis modules read datasource_selection.input_path
            selection.setdefault("input_path", str(path))
        if key and path:
            selection[str(key)] = str(path)
    return selection


def _count_executable_module_nodes(nodes: list[Any] | None) -> int:
    """Count algorithm/module nodes, excluding canvas metadata helpers."""
    scrape_only = {
        "data_source",
        "source",
        "time_range",
        "bbox",
        "number_const",
        "string_const",
        "boolean_const",
        "latlng",
        "map_viewport",
        "output_map_layer",
        "output_file",
    }
    count = 0
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        module_name = _node_module_name(node).strip()
        if module_name in scrape_only:
            continue
        ntype = str(node.get("type") or node.get("node_type") or "")
        if (
            ntype.startswith("module/")
            or ntype.startswith("download/")
            or ntype.startswith("stats/")
            or ntype.startswith("viz/")
        ):
            count += 1
            continue
        # Compiled form: node_type=module + params.module_name=<algorithm>
        if str(node.get("node_type") or "") == "module" and module_name not in {
            "",
            "module",
        }:
            count += 1
    return count


def _flatten_ui_workflow_definition(
    algorithm_request: dict[str, Any],
    *,
    descriptor: Any,
) -> tuple[dict[str, Any], Any, Any]:
    """将 UI 画布 workflow_definition 展平为种子式 algorithm_request。

    单模块画布：展平为 module_name + algorithm_params + datasource_selection。
    多模块 DAG（如 timeseries_bundle → omega_block）：保留 workflow_definition，
    仅合并 data/source 到 datasource_selection，避免丢掉模块间边。
    """
    workflow_definition = algorithm_request.get("workflow_definition")
    if not isinstance(workflow_definition, dict):
        return algorithm_request, None, None

    nodes = workflow_definition.get("nodes")
    canvas_params = _extract_algorithm_params_from_nodes(nodes)
    time_range = _extract_time_range_from_nodes(nodes)
    spatial = _extract_bbox_from_nodes(nodes)

    existing_ds = algorithm_request.get("datasource_selection")
    if not isinstance(existing_ds, dict):
        existing_ds = {}
    canvas_ds = _extract_datasource_selection_from_nodes(nodes)
    for key, value in canvas_ds.items():
        existing_ds.setdefault(key, value)
    for key, value in list(existing_ds.items()):
        if key.startswith("_") or not isinstance(value, str) or not value.strip():
            continue
        if Path(value).is_absolute() and Path(value).exists():
            continue
        resolved = _resolve_data_access_source_uri(value)
        if resolved:
            existing_ds[key] = resolved

    existing_params = algorithm_request.get("algorithm_params")
    if not isinstance(existing_params, dict):
        existing_params = {}
    if canvas_params:
        merged = dict(canvas_params)
        merged.update(existing_params)
        existing_params = merged
    if spatial is not None and getattr(spatial, "bbox", None) is not None:
        bbox = spatial.bbox
        existing_params.setdefault("bbox_west", float(bbox.west))
        existing_params.setdefault("bbox_south", float(bbox.south))
        existing_params.setdefault("bbox_east", float(bbox.east))
        existing_params.setdefault("bbox_north", float(bbox.north))
        existing_params.setdefault(
            "bbox", [bbox.west, bbox.south, bbox.east, bbox.north]
        )

    # Multi-module graph: keep executable definition; only enrich request fields.
    if _count_executable_module_nodes(nodes) >= 2:
        enriched = dict(algorithm_request)
        enriched["datasource_selection"] = existing_ds
        enriched["algorithm_params"] = existing_params
        enriched.setdefault("output_spec", {})
        return enriched, time_range, spatial

    flat = {
        key: value
        for key, value in algorithm_request.items()
        if key not in {"workflow_definition", "workflow_name"}
    }
    flat.setdefault("module_name", getattr(descriptor, "module_name", None))
    flat.setdefault(
        "task_type",
        getattr(descriptor, "default_task_type", None)
        or getattr(descriptor, "module_name", None),
    )
    flat.setdefault(
        "workflow_entry_name",
        algorithm_request.get("workflow_entry_name")
        or getattr(descriptor, "workflow_name", None)
        or getattr(descriptor, "module_name", None),
    )
    flat["algorithm_params"] = existing_params
    flat["datasource_selection"] = existing_ds
    flat.setdefault("output_spec", {})
    return flat, time_range, spatial


def _compile_workflow_seed(workflow_name: str) -> dict[str, Any] | None:
    """编译工作流种子，返回 compiled workflow_definition。

    用于将种子的 algorithm_params（如 tb_source）传递到模块执行。

    编译后过滤无效 edge：node_template_registry 会为模块节点添加 time_range/bbox
    等"元输入端口"，但 Python provider 的模块签名不包含它们。这些值通过
    job_request.time_range / job_request.region 在请求级别传递，不走 workflow edge。
    同时合并重复的 datasource_selection edge（多个 data/source → 同一端口）为
    input_bindings，只保留第一条 edge。
    """
    try:
        from app.services.workflow_definition_service import get_definition
        from app.services.workflow_graph_compiler import (
            compile_litegraph_to_workflow_definition,
        )

        definition = get_definition(workflow_name)
        if not definition:
            return None
        compiled = compile_litegraph_to_workflow_definition(
            workflow_id=workflow_name,
            name=definition.get("name"),
            description=definition.get("description"),
            nodes=definition.get("nodes", []),
            links=definition.get("links", []),
        )

        _filter_invalid_edges(compiled)

        return compiled
    except Exception:
        logger.debug("Failed to compile workflow seed", exc_info=True)
        return None


def _extract_algorithm_params_from_seed(workflow_name: str) -> dict[str, Any] | None:
    """从工作流种子的模块节点 properties 中提取 algorithm_params。

    比 _compile_workflow_seed 更轻量：不编译完整 graph，只读取种子的节点属性。
    用于将 algorithm_params（如 tb_source=SMAP）直接合并到 algorithm_request，
    避免设置 workflow_definition 导致 executor 处理 graph 时出现 datasource_selection
    多重绑定问题。
    """
    try:
        from app.services.workflow_definition_service import get_definition

        definition = get_definition(workflow_name)
        if not definition:
            return None
        for node in definition.get("nodes", []):
            node_type = node.get("type") or node.get("node_type") or ""
            if not node_type.startswith("module/"):
                continue
            props = node.get("properties") or {}
            params = props.get("algorithm_params")
            if isinstance(params, dict) and params:
                return dict(params)
        return None
    except Exception:
        logger.debug("Failed to extract algorithm_params from seed", exc_info=True)
        return None


# 这些端口由 job_request 级别处理，不应出现在 workflow edge 中
_NON_EDGE_PORTS = frozenset({"time_range", "bbox", "region"})


def _filter_invalid_edges(compiled: dict[str, Any]) -> None:
    """从编译后的 workflow_definition 中移除引用不存在输入端口的 edge。

    仅过滤 time_range/bbox/region 等由 job_request 级别处理的端口。
    保留所有其他 edge（包括重复连接到同一端口的多条 edge，
    因为多个 data/source 节点可能都连接到 datasource_selection）。
    """
    raw_edges = compiled.get("edges") or []
    if not raw_edges:
        return

    filtered: list[dict[str, str]] = []
    for edge in raw_edges:
        to_port = edge.get("to_port", "")

        # 跳过由 job_request 级别处理的端口
        if to_port in _NON_EDGE_PORTS:
            continue

        filtered.append(edge)

    compiled["edges"] = filtered


def _populate_python_provider_request(
    *, payload: WorkflowSubmitRequest, descriptor
) -> WorkflowSubmitRequest:
    if not descriptor.module_name:
        return payload

    algorithm_request = _normalize_algorithm_request(payload.algorithm_request)
    canvas_time_range = None
    canvas_spatial = None
    if algorithm_request.get("workflow_definition"):
        # UI 画布提交：展平为种子式请求，避免多 datasource edge / 元端口校验失败
        algorithm_request, canvas_time_range, canvas_spatial = (
            _flatten_ui_workflow_definition(algorithm_request, descriptor=descriptor)
        )
        updates: dict[str, Any] = {"algorithm_request": algorithm_request}
        if payload.time_range is None and canvas_time_range is not None:
            updates["time_range"] = canvas_time_range
        if payload.spatial_filter is None and canvas_spatial is not None:
            updates["spatial_filter"] = canvas_spatial
        payload = payload.model_copy(update=updates)
    elif algorithm_request.get("workflow_name"):
        # 仅声明 workflow_name、无 definition：仍补齐 time_range 后交由种子路径
        resolved_tr = _resolve_missing_time_range(
            payload=payload,
            algorithm_request=algorithm_request,
            descriptor=descriptor,
        )
        if resolved_tr is not None:
            payload = payload.model_copy(update={"time_range": resolved_tr})
        return payload

    explicit_module_name = algorithm_request.get("module_name")
    if explicit_module_name and explicit_module_name != descriptor.module_name:
        updates = {}
        resolved_tr = _resolve_missing_time_range(
            payload=payload,
            algorithm_request=algorithm_request,
            descriptor=descriptor,
        )
        if resolved_tr is not None:
            updates["time_range"] = resolved_tr
        return payload.model_copy(update=updates) if updates else payload

    algorithm_request.setdefault(
        "task_type", descriptor.default_task_type or descriptor.module_name
    )

    # 如果图层有 workflow_name，从种子中提取 algorithm_params（如 tb_source=SMAP）
    # 直接合并到 algorithm_request，避免设置 workflow_definition 导致 executor
    # 处理 graph 时出现 datasource_selection 多重绑定问题。
    if descriptor.workflow_name:
        seed_params = _extract_algorithm_params_from_seed(descriptor.workflow_name)
        if seed_params is not None:
            existing_params = algorithm_request.get("algorithm_params")
            if not isinstance(existing_params, dict):
                existing_params = {}
                algorithm_request["algorithm_params"] = existing_params
            for k, v in seed_params.items():
                existing_params.setdefault(k, v)
        algorithm_request.setdefault("module_name", descriptor.module_name)
        algorithm_request.setdefault(
            "workflow_entry_name",
            descriptor.workflow_name or descriptor.module_name,
        )
    else:
        algorithm_request.setdefault("module_name", descriptor.module_name)
        algorithm_request.setdefault("workflow_entry_name", descriptor.module_name)

    datasource_selection = _normalize_request(
        algorithm_request.get("datasource_selection")
    )
    data_access_requests = _normalize_request(
        datasource_selection.get("_data_access_requests")
    )
    default_data_access = _build_default_data_access_requests(
        descriptor.default_data_access_sources
    )
    for dataset_name, request_payload in default_data_access.items():
        data_access_requests.setdefault(dataset_name, request_payload)
    if data_access_requests:
        datasource_selection["_data_access_requests"] = data_access_requests

    # 根据模板的 accepted_data_access_by_required_key 把 dataset URI 映射到 required_key
    # 修复：模板验证检查 datasource_selection 中有 input_dir 等键，
    # 但 _data_access_requests 中用的是 dataset_name（如 NDVI_16DAY_RASTER）。
    # 需要把解析到的 URI 也设置到 datasource_selection[required_key] 中。
    template = _get_module_request_template(descriptor.module_name)
    if template is not None and template.accepted_data_access_by_required_key:
        for (
            required_key,
            accepted_datasets,
        ) in template.accepted_data_access_by_required_key.items():
            if datasource_selection.get(required_key) is not None:
                continue  # 用户已显式提供
            for dataset_name in accepted_datasets:
                da_request = data_access_requests.get(dataset_name)
                if da_request and isinstance(da_request, dict):
                    selector = da_request.get("selector") or {}
                    uris = selector.get("uris") or []
                    if uris:
                        datasource_selection[required_key] = uris[0]
                        break

    # 显式相对路径（画布/种子）→ 绝对本地 URI，供 omega_sf 读 IGBP 等
    for key, value in list(datasource_selection.items()):
        if key.startswith("_") or not isinstance(value, str) or not value.strip():
            continue
        if Path(value).is_absolute() and Path(value).exists():
            continue
        resolved = _resolve_data_access_source_uri(value)
        if resolved:
            datasource_selection[key] = resolved

    if datasource_selection:
        algorithm_request["datasource_selection"] = datasource_selection

    # 从画布/种子补齐 time_range（前端 UI 提交时常缺该字段）
    updates: dict[str, Any] = {"algorithm_request": algorithm_request}
    resolved_tr = _resolve_missing_time_range(
        payload=payload,
        algorithm_request=algorithm_request,
        descriptor=descriptor,
    )
    if resolved_tr is not None:
        updates["time_range"] = resolved_tr

    return payload.model_copy(update=updates)


def _populate_gee_request(
    *, payload: WorkflowSubmitRequest, layer_id: str, descriptor
) -> WorkflowSubmitRequest:
    if not descriptor.workflow_definition:
        return payload

    gee_request = _normalize_request(payload.gee_request)
    if any(gee_request.get(key) for key in _GEE_ENTRY_KEYS):
        return payload

    gee_request.setdefault("workflow", descriptor.workflow_definition)
    gee_request.setdefault(
        "workflow_id", descriptor.workflow_id or descriptor.workflow_name or layer_id
    )
    return payload.model_copy(update={"gee_request": gee_request})


def _populate_weather_request(
    *, payload: WorkflowSubmitRequest, layer_id: str, descriptor
) -> WorkflowSubmitRequest:
    if not descriptor.workflow_definition:
        return payload

    weather_request = _normalize_request(payload.weather_request)
    if any(weather_request.get(key) for key in _WEATHER_ENTRY_KEYS):
        return payload

    weather_request.setdefault("workflow", descriptor.workflow_definition)
    weather_request.setdefault(
        "workflow_id", descriptor.workflow_id or descriptor.workflow_name or layer_id
    )
    weather_request.setdefault("layer_id", layer_id)
    return payload.model_copy(update={"weather_request": weather_request})


def _normalize_algorithm_request(value: Any) -> dict[str, Any]:
    return _normalize_request(value)


def _normalize_request(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return dict(value)
    return {}


def _build_default_data_access_requests(
    source_map: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    requests: dict[str, dict[str, Any]] = {}
    for dataset_name, candidates in source_map.items():
        uri = _resolve_data_access_candidates(candidates)["resolved_uri"]
        if uri:
            requests[dataset_name] = {"selector": {"uris": [uri]}}
    return requests


def _resolve_data_access_candidates(candidates: list[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    resolved_uri: str | None = None
    for candidate in candidates:
        uri = _resolve_data_access_source_uri(candidate)
        results.append(
            {
                "source": candidate,
                "resolved_uri": uri,
                "available": bool(uri),
            }
        )
        if resolved_uri is None and uri:
            resolved_uri = uri
    return {"resolved_uri": resolved_uri, "candidates": results}


def _resolve_first_existing_data_access_uri(candidates: list[str]) -> str | None:
    for candidate in candidates:
        uri = _resolve_data_access_source_uri(candidate)
        if uri:
            return uri
    return None


def _resolve_data_access_source_uri(source: str) -> str | None:
    candidate = str(source).strip()
    if not candidate:
        return None
    if "://" in candidate:
        return _resolve_scheme_uri(candidate)
    if Path(candidate).is_absolute():
        absolute_path = Path(candidate)
        return str(absolute_path) if absolute_path.exists() else None

    resolved_path = _resolve_provider_dataset_path(candidate)
    if resolved_path is not None:
        return str(resolved_path)

    # 路径别名：FY3D_TB / SMAP_ancillary 等 → 本地 catalog 目录
    normalized = _normalize_provider_relative_path(candidate)
    if normalized != candidate:
        alias_resolved = _resolve_provider_dataset_path(normalized)
        if alias_resolved is not None:
            return str(alias_resolved)
        alias_fallback = Path(settings.data_root) / Path(normalized)
        if alias_fallback.exists():
            return str(alias_fallback)

    fallback_path = Path(settings.data_root) / Path(candidate)
    return str(fallback_path) if fallback_path.exists() else None


def _normalize_provider_relative_path(path: str) -> str:
    """Normalize historical seed paths via provider dataset_config aliases."""
    try:
        import importlib

        # Ensure provider root is importable (helpers load already does this)
        _load_provider_dataset_helpers()
        mod = importlib.import_module("dataset_config")
        normalize = getattr(mod, "normalize_dataset_relative_path", None)
        if callable(normalize):
            return str(normalize(path))
    except Exception:
        return path
    return path


def _resolve_scheme_uri(uri: str) -> str | None:
    """Pass through http/minio/file; remote schemes require resolvable credentials."""
    from urllib.parse import urlparse

    from shared.remote_sources.uri import REMOTE_SCHEMES, parse_remote_uri

    scheme = (urlparse(uri).scheme or "").lower()
    if scheme == "gcs":
        scheme = "gs"
    if scheme not in REMOTE_SCHEMES:
        return uri

    try:
        parse_remote_uri(uri)
    except ValueError:
        return None

    try:
        from app.services.remote_auth_resolver import resolve_remote_auth

        auth = resolve_remote_auth(uri)
    except Exception:
        return None

    if settings.remote_readiness_probe:
        try:
            from shared.remote_sources.download import probe_remote_connectivity

            # Connectivity only — missing object must not block workflow readiness
            probe_remote_connectivity(uri, auth)
        except Exception:
            return None
    return uri


@lru_cache(maxsize=128)
def _resolve_provider_dataset_path(logical_name: str) -> Path | None:
    dataset_helpers = _load_provider_dataset_helpers()
    if dataset_helpers is None:
        return None

    resolve_dataset_path, get_dataset_info = dataset_helpers
    if callable(resolve_dataset_path):
        resolved = resolve_dataset_path(logical_name)
        if resolved is not None:
            return Path(str(resolved))

    if callable(get_dataset_info):
        info = get_dataset_info(logical_name)
        relative_path = (
            getattr(info, "relative_path", None) if info is not None else None
        )
        if relative_path:
            candidate = Path(settings.data_root) / Path(str(relative_path))
            if candidate.exists():
                return candidate

    return None


_provider_helpers_cache_lock = threading.Lock()


# 内部实现（无缓存）
def _load_provider_dataset_helpers_uncached() -> tuple[Any, Any] | None:
    import time

    start = time.time()
    logger = logging.getLogger(__name__)
    provider_root = Path(settings.python_provider_root)
    logger.info(
        f"[workflow_request_resolver] _load_provider_dataset_helpers start, root={provider_root}"
    )
    if not provider_root.exists():
        logger.info(
            "[workflow_request_resolver] _load_provider_dataset_helpers: root doesn't exist, returning None"
        )
        return None

    try:
        import concurrent.futures

        def _import_dataset_config() -> Any:
            with _python_provider_import_path(provider_root):
                return importlib.import_module("dataset_config")

        # 添加超时保护，避免 dataset_config 导入挂起导致 /layers 端点响应缓慢
        logger.info(
            "[workflow_request_resolver] _load_provider_dataset_helpers: starting import with timeout"
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_import_dataset_config)
            try:
                dataset_config = future.result(timeout=5.0)  # 5秒超时
                logger.info(
                    f"[workflow_request_resolver] _load_provider_dataset_helpers: import succeeded after {time.time() - start:.1f}s"
                )
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "[workflow_request_resolver] _load_provider_dataset_helpers timed out after 5s"
                )
                return None
    except Exception as e:
        logger.warning(
            f"[workflow_request_resolver] _load_provider_dataset_helpers exception: {e}"
        )
        return None

    result = (
        getattr(dataset_config, "resolve_dataset_path", None),
        getattr(dataset_config, "get_dataset_info", None),
    )
    logger.info(
        f"[workflow_request_resolver] _load_provider_dataset_helpers done in {time.time() - start:.1f}s"
    )
    return result


# 线程安全的缓存包装器
@lru_cache(maxsize=1)
def _load_provider_dataset_helpers() -> tuple[Any, Any] | None:
    with _provider_helpers_cache_lock:
        return _load_provider_dataset_helpers_uncached()


def warm_provider_helpers() -> bool:
    """在应用启动时预热 provider dataset helpers 缓存 + 各图层 readiness 检查。

    避免首次 /layers 请求时阻塞在 dataset_config 导入 + 数据源路径解析上。
    返回 True 表示成功加载，False 表示失败或跳过。
    """
    helpers = _load_provider_dataset_helpers()
    if helpers is None:
        return False

    # 预解析所有图层的 readiness，填充 _resolve_provider_dataset_path 的 lru_cache
    # 避免首次 /layers 的 8 并发 readiness 检查串行等待
    try:
        from app.services.layer_catalog import get_layer_catalog

        catalog = get_layer_catalog()
        for descriptor in catalog.items:
            with suppress(Exception):
                describe_layer_run_readiness(
                    descriptor.layer_id
                )  # 个别图层 readiness 失败不影响整体预热
    except Exception:
        pass  # catalog 加载失败不影响 helpers 预热

    return True


@contextmanager
def _python_provider_import_path(provider_root: Path) -> Iterator[None]:
    provider_path = str(provider_root)
    inserted = False
    if provider_path not in sys.path:
        sys.path.insert(0, provider_path)
        inserted = True
    try:
        yield
    finally:
        if inserted:
            with suppress(ValueError):
                sys.path.remove(provider_path)


# ── Engine Request Populator 实现 ──────────────────────────────────────────


class _PythonProviderPopulator:
    """python_provider 引擎的请求填充器。"""

    @property
    def engine_name(self) -> str:
        return "python_provider"

    def populate(
        self,
        *,
        payload: WorkflowSubmitRequest,
        layer_id: str,
        descriptor: Any,
    ) -> WorkflowSubmitRequest:
        return _populate_python_provider_request(payload=payload, descriptor=descriptor)

    def describe_resolution(
        self, payload: WorkflowSubmitRequest
    ) -> dict[str, Any] | None:
        return _describe_python_provider_resolution_impl(payload)

    def describe_readiness(self, descriptor: Any) -> dict[str, Any] | None:
        if not descriptor.default_data_access_sources:
            return None
        unresolved: list[dict[str, Any]] = []
        for dataset_name, candidates in descriptor.default_data_access_sources.items():
            resolution = _resolve_data_access_candidates(candidates)
            if resolution["resolved_uri"] is not None:
                continue
            unresolved.append(
                {
                    "dataset_name": dataset_name,
                    "candidate_sources": [
                        item["source"] for item in resolution["candidates"]
                    ],
                }
            )
        return {"unresolved_default_datasets": unresolved} if unresolved else None


class _GeePopulator:
    """gee 引擎的请求填充器。"""

    @property
    def engine_name(self) -> str:
        return "gee"

    def populate(
        self,
        *,
        payload: WorkflowSubmitRequest,
        layer_id: str,
        descriptor: Any,
    ) -> WorkflowSubmitRequest:
        return _populate_gee_request(
            payload=payload, layer_id=layer_id, descriptor=descriptor
        )

    def describe_resolution(
        self, payload: WorkflowSubmitRequest
    ) -> dict[str, Any] | None:
        return None

    def describe_readiness(self, descriptor: Any) -> dict[str, Any] | None:
        return None


class _WeatherPopulator:
    """weather_workflow 引擎的请求填充器。"""

    @property
    def engine_name(self) -> str:
        return "weather_workflow"

    def populate(
        self,
        *,
        payload: WorkflowSubmitRequest,
        layer_id: str,
        descriptor: Any,
    ) -> WorkflowSubmitRequest:
        return _populate_weather_request(
            payload=payload, layer_id=layer_id, descriptor=descriptor
        )

    def describe_resolution(
        self, payload: WorkflowSubmitRequest
    ) -> dict[str, Any] | None:
        return None

    def describe_readiness(self, descriptor: Any) -> dict[str, Any] | None:
        return None


# 模块加载时注册所有 populator
register_engine_populator(_PythonProviderPopulator())
register_engine_populator(_GeePopulator())
register_engine_populator(_WeatherPopulator())
