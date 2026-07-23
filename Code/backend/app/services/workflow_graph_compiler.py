"""Compile LiteGraph editor graphs into Python provider WorkflowDefinition dicts."""

from __future__ import annotations

from typing import Any

from app.services.node_template_registry import (
    get_all_node_templates,
    get_node_template,
)

# Engines that execute as python_provider module nodes in this phase
_PYTHONISH_ENGINES = frozenset({"common", "python_provider"})


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
    return str(raw).strip()


def _port_name(ports: list[dict[str, Any]], slot: int, fallback_prefix: str) -> str:
    if 0 <= slot < len(ports):
        name = ports[slot].get("name")
        if name:
            return str(name)
    return f"{fallback_prefix}{slot}"


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

    Rules (Phase 1):
    - Only ``common`` + ``python_provider`` templates become ``node_type=module``
    - Cross-engine / weather / gee nodes raise :class:`WorkflowGraphCompileError`
    - Params come from node ``properties``; ``module_name`` is template ``node_class``
    - Links become ``edges`` using template port names by slot index
    """
    allow = allow_engines or _PYTHONISH_ENGINES
    raw_nodes = _as_list(nodes)
    raw_links = _as_list(links)
    if not raw_nodes:
        raise WorkflowGraphCompileError("画布为空：请先添加至少一个节点")

    # Ensure templates are loaded
    get_all_node_templates()

    compiled_nodes: list[dict[str, Any]] = []
    id_map: dict[int, str] = {}
    port_meta: dict[str, dict[str, list[dict[str, Any]]]] = {}

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

        engine = str(template.get("engine") or "common")
        if engine not in allow:
            raise WorkflowGraphCompileError(
                f"本轮画布执行仅支持 common/python_provider 节点，"
                f"不支持 engine={engine} 的节点「{template.get('title') or node_type}」"
            )

        node_class = str(template.get("node_class") or "").strip()
        if not node_class:
            raise WorkflowGraphCompileError(f"节点 {node_type} 未配置 node_class")

        node_id = f"n{lg_id_int}"
        id_map[lg_id_int] = node_id

        props = (
            node.get("properties") if isinstance(node.get("properties"), dict) else {}
        )
        params: dict[str, Any] = {str(k): v for k, v in props.items()}
        params["module_name"] = node_class

        inputs = list(template.get("inputs") or [])
        outputs = list(template.get("outputs") or [])
        # Include promoted params as optional input ports (same as LiteGraph registration)
        existing = {str(p.get("name")) for p in inputs}
        for param in template.get("params") or []:
            key = str(param.get("key") or "")
            if key and key not in existing:
                inputs.append({"name": key, "type": "value:any", "required": False})
                existing.add(key)

        port_meta[node_id] = {"inputs": inputs, "outputs": outputs}
        compiled_nodes.append(
            {
                "node_id": node_id,
                "node_type": "module",
                "version": "1.0",
                "label": str(node.get("title") or template.get("title") or node_type),
                "input_bindings": {},
                "params": params,
                "enabled": True,
            }
        )

    edges: list[dict[str, str]] = []
    for link in raw_links:
        # LiteGraph link formats:
        # - array: [link_id, from_id, from_slot, to_id, to_slot, type]
        # - object (frontend serialize): {"0": id, "1": from, "2": slot, "3": to, "4": slot, "5": type}
        # - object (native): {id, origin_id, origin_slot, target_id, target_slot, type}
        if isinstance(link, (list, tuple)) and len(link) >= 5:
            from_id, from_slot, to_id, to_slot = (
                int(link[1]),
                int(link[2]),
                int(link[3]),
                int(link[4]),
            )
        elif isinstance(link, dict):
            if "1" in link or 1 in link:
                from_id = int(link.get("1", link.get(1)))
                from_slot = int(link.get("2", link.get(2, 0)) or 0)
                to_id = int(link.get("3", link.get(3)))
                to_slot = int(link.get("4", link.get(4, 0)) or 0)
            else:
                from_raw = link.get("origin_id", link.get("from_node_id"))
                to_raw = link.get("target_id", link.get("to_node_id"))
                if from_raw is None or to_raw is None:
                    continue
                from_id = int(from_raw)
                to_id = int(to_raw)
                from_slot = int(link.get("origin_slot", link.get("from_slot", 0)) or 0)
                to_slot = int(link.get("target_slot", link.get("to_slot", 0)) or 0)
        else:
            continue

        from_nid = id_map.get(from_id)
        to_nid = id_map.get(to_id)
        if not from_nid or not to_nid:
            continue

        from_ports = port_meta[from_nid]["outputs"]
        to_ports = port_meta[to_nid]["inputs"]
        edges.append(
            {
                "from_node": from_nid,
                "from_port": _port_name(from_ports, from_slot, "out_"),
                "to_node": to_nid,
                "to_port": _port_name(to_ports, to_slot, "in_"),
            }
        )

    if not compiled_nodes:
        raise WorkflowGraphCompileError("没有可编译的节点")

    # Prefer last node that declares a "manifest" output; else last node first output
    output_specs: list[dict[str, str]] = []
    for node in reversed(compiled_nodes):
        nid = node["node_id"]
        outs = port_meta[nid]["outputs"]
        manifest_port = next((p for p in outs if p.get("name") == "manifest"), None)
        if manifest_port:
            output_specs.append({"name": "manifest", "source": f"node:{nid}.manifest"})
            break
        if outs:
            pname = str(outs[0].get("name") or "result")
            output_specs.append({"name": "manifest", "source": f"node:{nid}.{pname}"})
            break
    if not output_specs:
        # Force a path-style output from the last node
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
            "source_node_count": len(compiled_nodes),
            "source_edge_count": len(edges),
        },
    }
