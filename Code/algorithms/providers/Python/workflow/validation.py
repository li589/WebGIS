from __future__ import annotations

import heapq
from dataclasses import dataclass, replace

from runner.registry import get_pipeline
from workflow.graph import WorkflowDefinition, WorkflowEdge, WorkflowNodeSpec
from workflow.registry import get_node_executor
from workflow.schemas import PortSpec


SUPPORTED_REQUEST_BINDINGS = {
    "datasource_selection",
    "algorithm_params",
    "output_spec_extra",
    "time_range",
    "region",
    "tags",
}


class WorkflowDefinitionValidationError(ValueError):
    """Raised when a workflow definition fails static validation."""


@dataclass(slots=True)
class _NodeSignature:
    input_ports: dict[str, PortSpec]
    output_ports: dict[str, PortSpec]


def validate_workflow_definition(definition: WorkflowDefinition) -> WorkflowDefinition:
    enabled_nodes = [node for node in definition.nodes if node.enabled]
    if not enabled_nodes:
        raise WorkflowDefinitionValidationError("workflow_definition must contain at least one enabled node")
    if not definition.outputs:
        raise WorkflowDefinitionValidationError("workflow_definition.outputs must not be empty")

    node_map: dict[str, WorkflowNodeSpec] = {}
    for node in enabled_nodes:
        if node.node_id in node_map:
            raise WorkflowDefinitionValidationError(
                f"Duplicate enabled node_id detected in workflow definition: {node.node_id}"
            )
        node_map[node.node_id] = node

    node_signatures = {node_id: _resolve_node_signature(node) for node_id, node in node_map.items()}

    _validate_edges(definition.edges, node_map=node_map, node_signatures=node_signatures)

    for node in enabled_nodes:
        _validate_node_inputs(
            node,
            node_signatures=node_signatures,
            node_map=node_map,
            edges=definition.edges,
        )
        _validate_mode_required_inputs(node, node_signatures=node_signatures, edges=definition.edges)

    output_names: set[str] = set()
    for index, output_spec in enumerate(definition.outputs):
        if output_spec.name in output_names:
            raise WorkflowDefinitionValidationError(
                f"Duplicate workflow output name detected: workflow_definition.outputs[{index}].name={output_spec.name}"
            )
        output_names.add(output_spec.name)
        _validate_binding(
            output_spec.source,
            node_map=node_map,
            node_signatures=node_signatures,
            path=f"workflow_definition.outputs[{index}].source",
        )

    _validate_acyclic_graph(node_map=node_map, edges=definition.edges)
    return definition


def _resolve_node_signature(node: WorkflowNodeSpec) -> _NodeSignature:
    try:
        if node.node_type == "module":
            module_name = str(node.params.get("module_name", "")).strip()
            if not module_name:
                raise WorkflowDefinitionValidationError(
                    f"workflow_definition.nodes[{node.node_id}] module node requires params.module_name"
                )
            from modules.registry import get_module

            module = get_module(module_name)
            spec = module.get_spec()
            signature = _NodeSignature(
                input_ports={port.name: port for port in spec.input_ports},
                output_ports={port.name: port for port in spec.output_ports},
            )
            return _extend_signature_with_param_bindings(signature, node)

        if node.node_type == "bridge.pipeline":
            pipeline_name = str(node.params.get("pipeline_name", "")).strip()
            if not pipeline_name:
                raise WorkflowDefinitionValidationError(
                    f"workflow_definition.nodes[{node.node_id}] bridge.pipeline node requires params.pipeline_name"
                )
            get_pipeline(pipeline_name)

        executor_cls = get_node_executor(node.node_type)
        executor = executor_cls()
        signature = _NodeSignature(
            input_ports={port.name: port for port in executor.get_input_ports()},
            output_ports={port.name: port for port in executor.get_output_ports()},
        )
        return _extend_signature_with_param_bindings(signature, node)
    except WorkflowDefinitionValidationError:
        raise
    except KeyError as exc:
        raise WorkflowDefinitionValidationError(str(exc)) from exc


def _extend_signature_with_param_bindings(signature: _NodeSignature, node: WorkflowNodeSpec) -> _NodeSignature:
    input_ports = dict(signature.input_ports)
    for input_name in _collect_param_binding_input_names(node):
        existing = input_ports.get(input_name)
        if existing is not None:
            input_ports[input_name] = replace(existing, required=True)
            continue
        input_ports[input_name] = PortSpec(
            name=input_name,
            kind="config",
            data_class="python_object",
            required=True,
        )
    return _NodeSignature(input_ports=input_ports, output_ports=signature.output_ports)


def _collect_param_binding_input_names(node: WorkflowNodeSpec) -> tuple[str, ...]:
    input_names: list[str] = []
    for field_name in ("datasource_bindings", "algorithm_param_bindings"):
        raw_value = node.params.get(field_name)
        if raw_value is None:
            continue
        if not isinstance(raw_value, dict):
            raise WorkflowDefinitionValidationError(
                f"workflow_definition.nodes[{node.node_id}].params.{field_name} must be an object mapping"
            )
        for target_key, input_name in raw_value.items():
            if not isinstance(target_key, str) or not target_key:
                raise WorkflowDefinitionValidationError(
                    f"workflow_definition.nodes[{node.node_id}].params.{field_name} must use non-empty string keys"
                )
            if not isinstance(input_name, str) or not input_name:
                raise WorkflowDefinitionValidationError(
                    f"workflow_definition.nodes[{node.node_id}].params.{field_name}.{target_key} "
                    "must reference a non-empty input port name"
                )
            input_names.append(input_name)
    return tuple(dict.fromkeys(input_names))


def _validate_edges(
    edges: list[WorkflowEdge],
    *,
    node_map: dict[str, WorkflowNodeSpec],
    node_signatures: dict[str, _NodeSignature],
) -> None:
    for index, edge in enumerate(edges):
        path = f"workflow_definition.edges[{index}]"
        if edge.from_node not in node_map:
            raise WorkflowDefinitionValidationError(f"{path}.from_node references unknown enabled node: {edge.from_node}")
        if edge.to_node not in node_map:
            raise WorkflowDefinitionValidationError(f"{path}.to_node references unknown enabled node: {edge.to_node}")

        source_ports = node_signatures[edge.from_node].output_ports
        if source_ports and edge.from_port not in source_ports:
            raise WorkflowDefinitionValidationError(
                f"{path}.from_port references unknown output port: {edge.from_node}.{edge.from_port}"
            )

        target_ports = node_signatures[edge.to_node].input_ports
        if target_ports and edge.to_port not in target_ports:
            raise WorkflowDefinitionValidationError(
                f"{path}.to_port references unknown input port: {edge.to_node}.{edge.to_port}"
            )


def _validate_node_inputs(
    node: WorkflowNodeSpec,
    *,
    node_signatures: dict[str, _NodeSignature],
    node_map: dict[str, WorkflowNodeSpec],
    edges: list[WorkflowEdge],
) -> None:
    signature = node_signatures[node.node_id]
    binding_counts: dict[str, int] = {}

    for port_name, binding in node.input_bindings.items():
        if signature.input_ports and port_name not in signature.input_ports:
            raise WorkflowDefinitionValidationError(
                f"workflow_definition.nodes[{node.node_id}].input_bindings references unknown input port: "
                f"{node.node_id}.{port_name}"
            )
        _validate_binding(
            binding,
            node_map=node_map,
            node_signatures=node_signatures,
            path=f"workflow_definition.nodes[{node.node_id}].input_bindings.{port_name}",
        )
        binding_counts[port_name] = binding_counts.get(port_name, 0) + 1

    for edge in edges:
        if edge.to_node != node.node_id:
            continue
        binding_counts[edge.to_port] = binding_counts.get(edge.to_port, 0) + 1

    for port_name, port_spec in signature.input_ports.items():
        count = binding_counts.get(port_name, 0)
        if port_spec.required and count == 0:
            raise WorkflowDefinitionValidationError(
                f"Workflow required input port not bound: {node.node_id}.{port_name}"
            )
        if count > 1 and not port_spec.multi_input:
            raise WorkflowDefinitionValidationError(
                f"Workflow input port received multiple bindings: {node.node_id}.{port_name}"
            )


def _validate_mode_required_inputs(
    node: WorkflowNodeSpec,
    *,
    node_signatures: dict[str, _NodeSignature],
    edges: list[WorkflowEdge],
) -> None:
    if node.node_type != "module":
        return
    module_name = str(node.params.get("module_name", "")).strip()
    mode = str(node.params.get("mode", "")).lower()
    required_inputs = tuple(getattr(_load_module_spec(module_name), "mode_required_inputs", {}).get(mode, ()))
    if not required_inputs:
        return
    signature = node_signatures[node.node_id].input_ports
    edge_bound_ports = {edge.to_port for edge in edges if edge.to_node == node.node_id}
    for input_name in required_inputs:
        if input_name not in signature:
            raise WorkflowDefinitionValidationError(
                f"workflow_definition.nodes[{node.node_id}] mode '{mode}' requires input port {input_name}, but the module does not expose it"
            )
        if input_name not in node.input_bindings and input_name not in edge_bound_ports:
            raise WorkflowDefinitionValidationError(
                f"workflow_definition.nodes[{node.node_id}] mode '{mode}' requires input_bindings.{input_name}"
            )


def _load_module_spec(module_name: str):
    from modules.registry import get_module

    module = get_module(module_name)
    return module.get_spec()


def _validate_binding(
    binding: str,
    *,
    node_map: dict[str, WorkflowNodeSpec],
    node_signatures: dict[str, _NodeSignature],
    path: str,
) -> None:
    if not isinstance(binding, str) or not binding:
        raise WorkflowDefinitionValidationError(f"{path} must be a non-empty binding string")

    if binding.startswith("input:"):
        input_name = binding.split(":", 1)[1]
        if not input_name:
            raise WorkflowDefinitionValidationError(f"{path} uses an empty input binding")
        return

    if binding.startswith("request:"):
        request_key = binding.split(":", 1)[1]
        if request_key not in SUPPORTED_REQUEST_BINDINGS:
            raise WorkflowDefinitionValidationError(
                f"{path} references unsupported request binding: request:{request_key}"
            )
        return

    if binding.startswith("node:"):
        source = binding.split(":", 1)[1]
        if "." not in source:
            raise WorkflowDefinitionValidationError(f"{path} must use node:<node_id>.<port_name> syntax")
        node_id, port_name = source.split(".", 1)
        if node_id not in node_map:
            raise WorkflowDefinitionValidationError(f"{path} references unknown enabled node: {node_id}")
        output_ports = node_signatures[node_id].output_ports
        if output_ports and port_name not in output_ports:
            raise WorkflowDefinitionValidationError(f"{path} references unknown node output port: {node_id}.{port_name}")
        return

    raise WorkflowDefinitionValidationError(f"{path} uses unsupported binding syntax: {binding}")


def _validate_acyclic_graph(
    *,
    node_map: dict[str, WorkflowNodeSpec],
    edges: list[WorkflowEdge],
) -> None:
    indegree = {node_id: 0 for node_id in node_map}
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_map}
    for edge in edges:
        adjacency[edge.from_node].append(edge.to_node)
        indegree[edge.to_node] += 1

    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        node_id = heapq.heappop(ready)
        ordered.append(node_id)
        for target in adjacency[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)

    if len(ordered) != len(node_map):
        raise WorkflowDefinitionValidationError("Workflow contains a cycle")
