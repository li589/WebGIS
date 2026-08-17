"""Compile LiteGraph editor graphs into executable WorkflowDefinition dicts.

Supports:
- common / python_provider → node_type=module (python_provider bridge)
- weather → native weatherengine node_type (= template node_class)
Mixed engines raise WorkflowGraphCompileError.
"""

from __future__ import annotations

from typing import Any

from app.services.node_template_registry import (
    get_all_node_templates,
    get_node_template,
    resolve_node_type,
)

_PYTHONISH_ENGINES = frozenset({"common", "python_provider"})
_WEATHER_ENGINES = frozenset({"weather"})
_DEFAULT_ALLOW = _PYTHONISH_ENGINES | _WEATHER_ENGINES

# Config ports filled from JobRequest (not fan-in edges from data/source).
_REQUEST_CONFIG_PORTS: tuple[str, ...] = (
    "datasource_selection",
    "algorithm_params",
    "output_spec_extra",
)
# Legacy LiteGraph fan-in names that scrapes into request.datasource_selection.
# Do NOT include generic ``data`` — used by remote_fetch and other real edges.
_SCRAPED_FANIN_PORTS = frozenset({"datasource_selection", "daily_mat_sources"})
_PORT_ALIASES: dict[str, str] = {
    "timeseries_bundle_mat": "output_path",
    "omega_mat": "manifest",
}


class WorkflowGraphCompileError(ValueError):
    """Raised when a LiteGraph graph cannot be compiled."""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return list(value)


def _node_type_of(node: dict[str, Any]) -> str:
    raw = node.get("type") or node.get("node_type") or ""
    return resolve_node_type(str(raw).strip())


def _port_name(ports: list[dict[str, Any]], slot: int, fallback_prefix: str) -> str:
    if 0 <= slot < len(ports):
        name = ports[slot].get("name")
        if name:
            return str(name)
    return f"{fallback_prefix}{slot}"


def _parse_link(link: Any) -> tuple[int, int, int, int] | None:
    if isinstance(link, (list, tuple)) and len(link) >= 5:
        return int(link[1]), int(link[2]), int(link[3]), int(link[4])
    if isinstance(link, dict):
        if "1" in link or 1 in link:
            return (
                int(link.get("1", link.get(1))),
                int(link.get("2", link.get(2, 0)) or 0),
                int(link.get("3", link.get(3))),
                int(link.get("4", link.get(4, 0)) or 0),
            )
        from_raw = link.get("origin_id", link.get("from_node_id"))
        to_raw = link.get("target_id", link.get("to_node_id"))
        if from_raw is None or to_raw is None:
            return None
        return (
            int(from_raw),
            int(link.get("origin_slot", link.get("from_slot", 0)) or 0),
            int(to_raw),
            int(link.get("target_slot", link.get("to_slot", 0)) or 0),
        )
    return None


def _apply_port_alias(name: str) -> str:
    return _PORT_ALIASES.get(name, name)


def _inject_python_request_bindings(
    compiled_nodes: list[dict[str, Any]],
    port_meta: dict[str, dict[str, list[dict[str, Any]]]],
) -> None:
    """Bind PortSpec config ports to request:* for python_provider module nodes."""
    for node in compiled_nodes:
        if str(node.get("node_type") or "") != "module":
            continue
        nid = str(node.get("node_id") or "")
        inputs = port_meta.get(nid, {}).get("inputs") or []
        input_names = {str(p.get("name") or "") for p in inputs}
        bindings = dict(node.get("input_bindings") or {})
        for port_name in _REQUEST_CONFIG_PORTS:
            if port_name in input_names:
                bindings.setdefault(port_name, f"request:{port_name}")
        node["input_bindings"] = bindings


def _normalize_python_edges(edges: list[dict[str, str]]) -> list[dict[str, str]]:
    """Drop scraped fan-in edges; alias legacy port names for module→module links."""
    normalized: list[dict[str, str]] = []
    for edge in edges:
        from_port = _apply_port_alias(str(edge.get("from_port") or ""))
        to_port = _apply_port_alias(str(edge.get("to_port") or ""))
        if to_port in _SCRAPED_FANIN_PORTS:
            continue
        if to_port in {"time_range", "bbox", "region"}:
            continue
        normalized.append(
            {
                "from_node": str(edge.get("from_node") or ""),
                "from_port": from_port,
                "to_node": str(edge.get("to_node") or ""),
                "to_port": to_port,
            }
        )
    return normalized


def compile_litegraph_to_workflow_definition(
    *,
    workflow_id: str,
    name: str | None = None,
    description: str | None = None,
    nodes: list[dict[str, Any]] | None = None,
    links: list[Any] | None = None,
    allow_engines: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Convert LiteGraph `{nodes, links}` into a coercible WorkflowDefinition dict.

    Returns metadata.engine = ``python_provider`` | ``weather``.
    """
    allow = allow_engines or _DEFAULT_ALLOW
    raw_nodes = _as_list(nodes)
    raw_links = _as_list(links)
    if not raw_nodes:
        raise WorkflowGraphCompileError("画布为空：请先添加至少一个节点")

    get_all_node_templates()

    compiled_nodes: list[dict[str, Any]] = []
    id_map: dict[int, str] = {}
    port_meta: dict[str, dict[str, list[dict[str, Any]]]] = {}
    engines_seen: set[str] = set()
    disabled_ids: set[str] = set()

    for node in raw_nodes:
        if not isinstance(node, dict):
            continue
        lg_id = node.get("id")
        if lg_id is None:
            raise WorkflowGraphCompileError("节点缺少 id")
        lg_id_int = int(lg_id)
        node_type = _node_type_of(node)
        if not node_type:
            raise WorkflowGraphCompileError(f"节点 {lg_id} 缺少 type")

        template = get_node_template(node_type)
        if template is None:
            raise WorkflowGraphCompileError(f"未知节点类型: {node_type}")

        if template.get("executable") is False:
            raise WorkflowGraphCompileError(
                f"节点「{template.get('title') or node_type}」尚未实现执行器（stub），"
                f"请从画布移除或改用已实现模块"
            )

        engine = str(template.get("engine") or "common")
        if engine not in allow:
            raise WorkflowGraphCompileError(
                f"不支持 engine={engine} 的节点「{template.get('title') or node_type}」"
            )
        engines_seen.add(engine)

        node_class = str(template.get("node_class") or "").strip()
        if not node_class:
            raise WorkflowGraphCompileError(f"节点 {node_type} 未配置 node_class")

        node_id = f"n{lg_id_int}"
        id_map[lg_id_int] = node_id

        props = (
            node.get("properties") if isinstance(node.get("properties"), dict) else {}
        )
        params: dict[str, Any] = {str(k): v for k, v in props.items()}
        # 种子可用 properties.enabled=false 停用节点（如现代日期无 FY3B 数据时
        # 禁用 FY3B 下载/转换支路）；enabled 不属于模块参数，须从 params 剥离。
        node_enabled = bool(params.pop("enabled", True))

        inputs = list(template.get("inputs") or [])
        outputs = list(template.get("outputs") or [])
        existing = {str(p.get("name")) for p in inputs}
        for param in template.get("params") or []:
            key = str(param.get("key") or "")
            if key and key not in existing:
                inputs.append({"name": key, "type": "value:any", "required": False})
                existing.add(key)

        port_meta[node_id] = {"inputs": inputs, "outputs": outputs}

        if engine in _WEATHER_ENGINES:
            # Native weatherengine executor node_type
            compiled_nodes.append(
                {
                    "node_id": node_id,
                    "node_type": node_class,
                    "version": "1.0",
                    "label": str(
                        node.get("title") or template.get("title") or node_type
                    ),
                    "input_bindings": {},
                    "params": params,
                    "enabled": node_enabled,
                }
            )
        else:
            params = {**params, "module_name": node_class}
            compiled_nodes.append(
                {
                    "node_id": node_id,
                    "node_type": "module",
                    "version": "1.0",
                    "label": str(
                        node.get("title") or template.get("title") or node_type
                    ),
                    "input_bindings": {},
                    "params": params,
                    "enabled": node_enabled,
                }
            )
        if not node_enabled:
            disabled_ids.add(node_id)

    has_weather = bool(engines_seen & _WEATHER_ENGINES)
    has_pythonish = bool(engines_seen & _PYTHONISH_ENGINES)
    if has_weather and has_pythonish:
        raise WorkflowGraphCompileError(
            "天气节点与 Python/common 节点不能混在同一画布中编译；请拆成两个工作流"
        )
    if has_weather and not (engines_seen <= _WEATHER_ENGINES):
        raise WorkflowGraphCompileError(
            f"天气工作流含不支持的引擎: {sorted(engines_seen - _WEATHER_ENGINES)}"
        )

    target_engine = "weather" if has_weather else "python_provider"

    edges: list[dict[str, str]] = []
    for link in raw_links:
        parsed = _parse_link(link)
        if not parsed:
            continue
        from_id, from_slot, to_id, to_slot = parsed
        from_nid = id_map.get(from_id)
        to_nid = id_map.get(to_id)
        if not from_nid or not to_nid:
            continue
        # 悬挂在停用节点上的边一并剔除：executor 拓扑分层对未知端点直接 KeyError。
        if from_nid in disabled_ids or to_nid in disabled_ids:
            continue
        from_ports = port_meta[from_nid]["outputs"]
        to_ports = port_meta[to_nid]["inputs"]
        from_port = _port_name(from_ports, from_slot, "out_")
        to_port = _port_name(to_ports, to_slot, "in_")
        # Weatherengine EdgeSpec: source_*/target_*; python provider: from_*/to_*.
        if target_engine == "weather":
            edges.append(
                {
                    "source_node_id": from_nid,
                    "source_port": from_port,
                    "target_node_id": to_nid,
                    "target_port": to_port,
                }
            )
        else:
            edges.append(
                {
                    "from_node": from_nid,
                    "from_port": from_port,
                    "to_node": to_nid,
                    "to_port": to_port,
                }
            )

    if not compiled_nodes:
        raise WorkflowGraphCompileError("没有可编译的节点")
    if len(compiled_nodes) == len(disabled_ids):
        raise WorkflowGraphCompileError("全部节点均已停用：请至少启用一个节点")

    if target_engine == "python_provider":
        _inject_python_request_bindings(compiled_nodes, port_meta)
        edges = _normalize_python_edges(edges)

    # Prefer product manifests over config-only sinks (e.g. data/time_range).
    # Scan all nodes for "manifest" first; only then fall back to other ports,
    # skipping pure helpers whose primary job is request shaping.
    _CONFIG_HELPER_MODULES = frozenset({"time_range", "data_source", "bbox"})
    output_specs: list[dict[str, str]] = []
    for node in reversed(compiled_nodes):
        nid = node["node_id"]
        outs = port_meta[nid]["outputs"]
        if any(p.get("name") == "manifest" for p in outs):
            output_specs.append({"name": "manifest", "source": f"node:{nid}.manifest"})
            break
    if not output_specs:
        for node in reversed(compiled_nodes):
            nid = node["node_id"]
            outs = port_meta[nid]["outputs"]
            if not outs:
                continue
            module_name = str((node.get("params") or {}).get("module_name") or "")
            if module_name in _CONFIG_HELPER_MODULES:
                continue
            pname = str(outs[0].get("name") or "result")
            # Weather graphs typically expose geojson as primary output
            out_name = "geojson" if pname == "geojson" else "manifest"
            output_specs.append({"name": out_name, "source": f"node:{nid}.{pname}"})
            break
    if not output_specs:
        last = compiled_nodes[-1]["node_id"]
        output_specs.append({"name": "manifest", "source": f"node:{last}.path"})

    return {
        "workflow_id": workflow_id or "canvas_workflow",
        "version": "1.0",
        "name": name,
        "description": description,
        "inputs": {},
        "nodes": compiled_nodes,
        "edges": edges,
        "outputs": output_specs,
        "defaults": {},
        "metadata": {
            "compiled_from": "litegraph",
            "engine": target_engine,
            "source_node_count": len(compiled_nodes),
            "source_edge_count": len(edges),
        },
    }
