from __future__ import annotations

import logging
from typing import Any

import networkx as nx

from app.workflow_engine.models import (
    ExecutionContext,
    NodeExecutionResult,
    RunResult,
    WorkflowDefinition,
)
from app.workflow_engine.enums import RunStatus
from app.workflow_engine.registry import NodeRegistry

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """负责工作流的拓扑排序与节点顺序执行。"""

    def __init__(self, registry: NodeRegistry) -> None:
        self._registry = registry

    def topological_sort(self, nodes, edges) -> list[str]:
        """对工作流节点进行拓扑排序，返回排序后的 node_id 列表。"""
        graph = nx.DiGraph()
        for node in nodes:
            graph.add_node(node.node_id)
        for edge in edges:
            graph.add_edge(edge.source_node_id, edge.target_node_id)
        # 检查是否存在环
        if not nx.is_directed_acyclic_graph(graph):
            raise ValueError("workflow contains cyclic dependencies")
        return list(nx.topological_sort(graph))

    def execute(
        self, workflow: WorkflowDefinition, context: ExecutionContext
    ) -> RunResult:
        """执行完整工作流，返回执行结果。"""
        node_map = {n.node_id: n for n in workflow.nodes}
        order = self.topological_sort(workflow.nodes, workflow.edges)
        node_outputs: dict[str, dict[str, Any]] = {}
        all_artifacts = []
        all_warnings = []
        all_errors = []
        node_results: list[NodeExecutionResult] = []

        for node_id in order:
            node_spec = node_map[node_id]
            try:
                node_cls = self._registry.get(node_spec.node_type)
                input_ports = self._resolve_input_ports(node_spec, node_cls)
                inputs = self._resolve_inputs(
                    node_spec,
                    input_ports,
                    workflow.inputs,
                    node_outputs,
                    workflow.edges,
                )
                node = node_cls(node_spec, context)
                result = node.execute(inputs)
            except Exception as exc:
                logger.exception(
                    "Node execution failed: %s (node_id=%s)",
                    node_spec.node_type,
                    node_id,
                )
                result = NodeExecutionResult(
                    node_id=node_id,
                    status=RunStatus.failed,
                    warnings=[str(exc)],
                )
            node_outputs[node_id] = result.outputs
            all_artifacts.extend(result.artifacts)
            all_warnings.extend(result.warnings)
            node_results.append(result)
            if (
                result.status == RunStatus.failed
                and not workflow.runtime_policy.continue_on_error
            ):
                all_errors.append(
                    f"Node {node_id} ({node_spec.node_type}) failed: {result.warnings}"
                )
                break
            if result.status == RunStatus.failed:
                all_errors.append(
                    f"Node {node_id} ({node_spec.node_type}) failed: {result.warnings}"
                )

        status = RunStatus.failed if all_errors else RunStatus.completed
        global_outputs = self._collect_global_outputs(node_outputs)
        return RunResult(
            run_id=context.run_id,
            workflow_id=workflow.workflow_id,
            status=status,
            node_results=node_results,
            outputs=global_outputs,
            artifacts=all_artifacts,
            warnings=all_warnings,
            errors=all_errors,
        )

    def _resolve_input_ports(self, node_spec, node_cls):
        """解析节点输入端口：优先使用 spec 中显式声明的端口，否则回退到节点类的规范规格。"""
        if node_spec.input_ports:
            return node_spec.input_ports
        try:
            canonical = node_cls.build_spec()
            return canonical.input_ports
        except (AttributeError, TypeError) as exc:
            # build_spec() 不存在或签名不匹配 — 编程 bug，应暴露而非静默吞掉
            raise RuntimeError(
                f"Node class {node_cls.__name__}.build_spec() failed: {exc}. "
                f"Ensure the node class implements a static build_spec() method."
            ) from exc

    def _resolve_inputs(
        self,
        node_spec,
        input_ports,
        global_inputs,
        node_outputs,
        edges,
    ):
        """根据边和全局输入，解析节点的输入值。

        优先级：上游边输出 > 全局输入 > 节点 params 默认值。
        """
        inputs: dict[str, Any] = {}
        # 处理从上游节点来的输入
        for edge in edges:
            if edge.target_node_id == node_spec.node_id:
                source_outputs = node_outputs.get(edge.source_node_id, {})
                if edge.source_port in source_outputs:
                    inputs[edge.target_port] = source_outputs[edge.source_port]
        # 处理全局输入覆盖（如果该端口未被上游赋值）
        for port in input_ports:
            if port.name in global_inputs and port.name not in inputs:
                inputs[port.name] = global_inputs[port.name]
        # 合并节点自身参数中的默认输入（最低优先级）
        inputs = {**node_spec.params, **inputs}
        return inputs

    def _collect_global_outputs(
        self, node_outputs: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """收集全局输出，扁平化为 {"node_id.port": value} 形式。"""
        result: dict[str, Any] = {}
        for node_id, outputs in node_outputs.items():
            for port_name, value in outputs.items():
                result[f"{node_id}.{port_name}"] = value
        return result
