from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from contracts.job import JobRequest
from contracts.runtime import RuntimeContext
from workflow.artifact_store import ArtifactStore, InMemoryArtifactStore
from workflow.graph import WorkflowDefinition, WorkflowEdge
from workflow.registry import get_node_executor, register_node_executor
from workflow.schemas import ArtifactRef, NodeExecutionContext


@dataclass(slots=True)
class WorkflowResult:
    workflow_id: str
    run_id: str
    node_outputs: dict[str, dict[str, object]] = field(default_factory=dict)
    outputs: dict[str, object] = field(default_factory=dict)
    execution_order: list[str] = field(default_factory=list)


class WorkflowRunner:
    def __init__(
        self,
        *,
        artifact_store: ArtifactStore | None = None,
        datasource_adapter=None,
        logger_adapter=None,
        product_sink=None,
    ) -> None:
        self.artifact_store = artifact_store or InMemoryArtifactStore()
        self.datasource_adapter = datasource_adapter
        self.logger_adapter = logger_adapter
        self.product_sink = product_sink

    def run(self, definition: WorkflowDefinition, request: JobRequest, runtime_context: RuntimeContext) -> WorkflowResult:
        from runner.call_guard import push_runtime_call

        with push_runtime_call(runtime_context, f"workflow:{definition.workflow_id}"):
            node_map = {node.node_id: node for node in definition.nodes if node.enabled}
            if len(node_map) != len([node for node in definition.nodes if node.enabled]):
                raise ValueError("Duplicate enabled node_id detected in workflow definition")

            execution_order = self._topological_sort(node_map, definition.edges)
            node_outputs: dict[str, dict[str, object]] = {}

            total_nodes = max(len(execution_order), 1)
            for index, node_id in enumerate(execution_order, start=1):
                node = node_map[node_id]
                executor_cls = get_node_executor(node.node_type)
                executor = executor_cls()
                inputs = self._resolve_node_inputs(
                    node,
                    input_ports=executor.get_input_ports(),
                    request=request,
                    node_outputs=node_outputs,
                    edges=definition.edges,
                )
                node_ctx = NodeExecutionContext(
                    workflow_id=definition.workflow_id,
                    node_id=node.node_id,
                    request=request,
                    runtime_context=runtime_context,
                    workspace=Path(runtime_context.workspace),
                    artifact_store=self.artifact_store,
                    datasource_adapter=self.datasource_adapter,
                    logger_adapter=self.logger_adapter,
                    product_sink=self.product_sink,
                )
                stage_name = f"workflow.node.{node.node_id}"
                if self.logger_adapter is not None:
                    self.logger_adapter.emit_stage_start(stage_name, f"Execute node {node.node_id} ({node.node_type})")
                try:
                    outputs = executor.execute(inputs, dict(node.params), node_ctx)
                except Exception as exc:
                    if self.logger_adapter is not None:
                        self.logger_adapter.emit_error(
                            stage_name,
                            str(exc),
                            extra={
                                "workflow_id": definition.workflow_id,
                                "node_id": node.node_id,
                                "node_type": node.node_type,
                                "exception_type": type(exc).__name__,
                            },
                        )
                    raise
                if self.logger_adapter is not None:
                    self.logger_adapter.emit_progress(
                        "workflow.dispatch",
                        index / total_nodes,
                        f"Completed node {node.node_id} ({index}/{total_nodes})",
                    )
                    self.logger_adapter.emit_stage_end(stage_name, f"Finished node {node.node_id}")
                node_outputs[node.node_id] = outputs

            resolved_outputs = {
                output_spec.name: self._resolve_binding(output_spec.source, request=request, node_outputs=node_outputs)
                for output_spec in definition.outputs
            }
            return WorkflowResult(
                workflow_id=definition.workflow_id,
                run_id=runtime_context.run_id,
                node_outputs=node_outputs,
                outputs=resolved_outputs,
                execution_order=execution_order,
            )

    def _resolve_node_inputs(
        self,
        node,
        *,
        input_ports,
        request: JobRequest,
        node_outputs: dict[str, dict[str, object]],
        edges: list[WorkflowEdge],
    ) -> dict[str, object]:
        port_specs = {port.name: port for port in input_ports}
        resolved: dict[str, object] = {}

        def bind_input(port_name: str, value: object) -> None:
            port_spec = port_specs.get(port_name)
            if port_name in resolved:
                if port_spec is not None and port_spec.multi_input:
                    existing_value = resolved[port_name]
                    if isinstance(existing_value, list):
                        existing_value.append(value)
                    else:
                        resolved[port_name] = [existing_value, value]
                    return
                raise ValueError(f"Workflow input port received multiple bindings: {node.node_id}.{port_name}")
            if port_spec is not None and port_spec.multi_input:
                resolved[port_name] = [value]
                return
            resolved[port_name] = value

        for port_name, binding in node.input_bindings.items():
            bind_input(port_name, self._resolve_binding(binding, request=request, node_outputs=node_outputs))
        for edge in edges:
            if edge.to_node != node.node_id:
                continue
            binding = f"node:{edge.from_node}.{edge.from_port}"
            bind_input(edge.to_port, self._resolve_binding(binding, request=request, node_outputs=node_outputs))
        for port_name, port_spec in port_specs.items():
            if port_spec.required and port_name not in resolved:
                raise ValueError(f"Workflow required input port not bound: {node.node_id}.{port_name}")
        return resolved

    def _resolve_binding(self, binding: str, *, request: JobRequest, node_outputs: dict[str, dict[str, object]]) -> object:
        if binding.startswith("input:"):
            input_name = binding.split(":", 1)[1]
            if input_name not in request.datasource_selection:
                raise KeyError(f"Workflow input not found: {input_name}")
            return request.datasource_selection[input_name]
        if binding.startswith("request:"):
            request_key = binding.split(":", 1)[1]
            if request_key == "datasource_selection":
                return dict(request.datasource_selection)
            if request_key == "algorithm_params":
                return dict(request.algorithm_params)
            if request_key == "output_spec_extra":
                return dict(request.output_spec.extra)
            if request_key == "time_range":
                return request.time_range
            if request_key == "region":
                return request.region
            if request_key == "tags":
                return dict(request.tags)
            raise KeyError(f"Workflow request binding not found: {request_key}")
        if binding.startswith("node:"):
            source = binding.split(":", 1)[1]
            node_id, port_name = source.split(".", 1)
            if node_id not in node_outputs:
                raise KeyError(f"Workflow node output not ready: {node_id}")
            if port_name not in node_outputs[node_id]:
                raise KeyError(f"Workflow node port not found: {node_id}.{port_name}")
            return node_outputs[node_id][port_name]
        raise ValueError(f"Unsupported binding syntax: {binding}")

    def _topological_sort(self, node_map: dict[str, object], edges: list[WorkflowEdge]) -> list[str]:
        indegree = {node_id: 0 for node_id in node_map}
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_map}
        for edge in edges:
            if edge.from_node not in node_map or edge.to_node not in node_map:
                raise KeyError(f"Workflow edge references unknown node: {edge.from_node} -> {edge.to_node}")
            adjacency[edge.from_node].append(edge.to_node)
            indegree[edge.to_node] += 1

        ready = sorted([node_id for node_id, degree in indegree.items() if degree == 0])
        ordered: list[str] = []
        while ready:
            node_id = ready.pop(0)
            ordered.append(node_id)
            for target in adjacency[node_id]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
            ready.sort()
        if len(ordered) != len(node_map):
            raise ValueError("Workflow contains a cycle")
        return ordered
