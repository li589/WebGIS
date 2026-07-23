from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

import networkx as nx

from webgis_gee.domain.models import (
    EdgeSpec,
    ExecutionContext,
    NodeExecutionResult,
    NodeSpec,
    PortSpec,
    RunResult,
    RunStatus,
    WorkflowDefinition,
)
from webgis_gee.nodes.base import BaseNode
from webgis_gee.nodes.registry import NodeRegistry
from webgis_gee.runtime.observability import (
    InMemoryMetricsCollector,
    StructuredEventSink,
    log_structured_event,
)

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """负责工作流的拓扑排序与节点顺序执行"""

    def __init__(
        self,
        node_registry: NodeRegistry,
    ) -> None:
        self._node_registry = node_registry

    def topological_sort(
        self, nodes: list[NodeSpec], edges: list[EdgeSpec]
    ) -> list[str]:
        """对工作流节点进行拓扑排序，返回排序后的 node_id 列表"""
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
        self,
        workflow: WorkflowDefinition,
        context: ExecutionContext,
    ) -> RunResult:
        """执行完整工作流，返回执行结果"""
        node_map = {node.node_id: node for node in workflow.nodes}
        sorted_node_ids = self.topological_sort(workflow.nodes, workflow.edges)
        metrics = self._resolve_metrics_collector(context)
        event_sink = self._resolve_event_sink(context)

        node_outputs: dict[str, dict[str, Any]] = {}  # node_id -> port name -> value
        node_results: list[NodeExecutionResult] = []
        all_artifacts: list[Any] = []
        all_warnings: list[str] = []
        all_errors: list[str] = []

        for node_id in sorted_node_ids:
            node_spec = node_map[node_id]
            node_cls = self._node_registry.get(node_spec.node_type)
            node_started_at = perf_counter()
            if metrics is not None:
                metrics.increment("node.execute.started")
            log_structured_event(
                logger,
                logging.INFO,
                "node.execute.started",
                sink=event_sink,
                run_id=context.run_id,
                workflow_id=workflow.workflow_id,
                account_id=context.account_id,
                node_id=node_id,
                node_type=node_spec.node_type,
            )

            try:
                # 准备节点输入
                inputs = self._resolve_inputs(
                    node_spec=node_spec,
                    input_ports=self._resolve_input_ports(node_spec, node_cls),
                    edges=workflow.edges,
                    node_outputs=node_outputs,
                    global_inputs=workflow.inputs,
                )

                # 执行节点
                node = node_cls(node_spec, context)
                result = node.execute(inputs)
                node_results.append(result)
                node_outputs[node_id] = result.outputs
                all_artifacts.extend(result.artifacts)
                all_warnings.extend(result.warnings)
                duration_ms = (perf_counter() - node_started_at) * 1000
                if metrics is not None:
                    metrics.observe_duration("node.execute.duration_ms", duration_ms)
                    if result.status == RunStatus.COMPLETED:
                        metrics.increment("node.execute.completed")
                    else:
                        metrics.increment("node.execute.failed")
                log_structured_event(
                    logger,
                    logging.INFO
                    if result.status == RunStatus.COMPLETED
                    else logging.WARNING,
                    "node.execute.finished",
                    sink=event_sink,
                    run_id=context.run_id,
                    workflow_id=workflow.workflow_id,
                    account_id=context.account_id,
                    node_id=node_id,
                    node_type=node_spec.node_type,
                    status=result.status.value,
                    warning_count=len(result.warnings),
                    artifact_count=len(result.artifacts),
                    duration_ms=round(duration_ms, 3),
                )
                if result.status == RunStatus.FAILED:
                    error_msg = self._failed_result_message(node_id, result)
                    all_errors.append(error_msg)
                    if not workflow.runtime_policy.continue_on_error:
                        break

            except Exception as e:
                duration_ms = (perf_counter() - node_started_at) * 1000
                if metrics is not None:
                    metrics.increment("node.execute.failed")
                    metrics.observe_duration("node.execute.duration_ms", duration_ms)
                error_msg = f"node {node_id} execution failed: {str(e)}"
                all_errors.append(error_msg)
                log_structured_event(
                    logger,
                    logging.ERROR,
                    "node.execute.failed",
                    sink=event_sink,
                    run_id=context.run_id,
                    workflow_id=workflow.workflow_id,
                    account_id=context.account_id,
                    node_id=node_id,
                    node_type=node_spec.node_type,
                    error=str(e),
                    duration_ms=round(duration_ms, 3),
                )
                node_results.append(
                    NodeExecutionResult(
                        node_id=node_id,
                        status=RunStatus.FAILED,
                        warnings=[error_msg],
                    )
                )
                if not workflow.runtime_policy.continue_on_error:
                    break

        overall_status = RunStatus.COMPLETED if not all_errors else RunStatus.FAILED

        return RunResult(
            run_id=context.run_id,
            workflow_id=workflow.workflow_id,
            status=overall_status,
            node_results=node_results,
            outputs=self._collect_global_outputs(node_results, workflow),
            artifacts=all_artifacts,
            warnings=all_warnings,
            errors=all_errors,
        )

    def _resolve_inputs(
        self,
        node_spec: NodeSpec,
        input_ports: list[PortSpec],
        edges: list[EdgeSpec],
        node_outputs: dict[str, dict[str, Any]],
        global_inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """根据边和全局输入，解析节点的输入值"""
        inputs: dict[str, Any] = {}

        # 处理从上游节点来的输入
        for edge in edges:
            if edge.target_node_id == node_spec.node_id:
                source_outputs = node_outputs.get(edge.source_node_id, {})
                if edge.source_port in source_outputs:
                    inputs[edge.target_port] = source_outputs[edge.source_port]

        # 处理全局输入覆盖（如果有的话）
        for port in input_ports:
            if port.name in global_inputs and port.name not in inputs:
                inputs[port.name] = global_inputs[port.name]

        # 合并节点自身参数中的默认输入（如果没有被覆盖）
        inputs = {**node_spec.params, **inputs}

        return inputs

    @staticmethod
    def _failed_result_message(node_id: str, result: NodeExecutionResult) -> str:
        detail = (
            "; ".join(result.warnings)
            if result.warnings
            else "node returned failed status"
        )
        return f"node {node_id} failed: {detail}"

    @staticmethod
    def _resolve_input_ports(
        node_spec: NodeSpec,
        node_cls: type[BaseNode],
    ) -> list[PortSpec]:
        if node_spec.input_ports:
            return node_spec.input_ports
        canonical_spec = node_cls.build_spec()
        return canonical_spec.input_ports

    def _collect_global_outputs(
        self,
        node_results: list[NodeExecutionResult],
        workflow: WorkflowDefinition,
    ) -> dict[str, Any]:
        """从最后一个或标记的输出节点收集全局输出（本阶段简化处理）"""
        outputs: dict[str, Any] = {}
        for result in node_results:
            for port_name, value in result.outputs.items():
                outputs[f"{result.node_id}.{port_name}"] = value
        return outputs

    @staticmethod
    def _resolve_metrics_collector(
        context: ExecutionContext,
    ) -> InMemoryMetricsCollector | None:
        collector = context.metadata.get("metrics_collector")
        if isinstance(collector, InMemoryMetricsCollector):
            return collector
        return None

    @staticmethod
    def _resolve_event_sink(context: ExecutionContext) -> StructuredEventSink | None:
        sink = context.metadata.get("event_sink")
        if isinstance(sink, StructuredEventSink):
            return sink
        return None
