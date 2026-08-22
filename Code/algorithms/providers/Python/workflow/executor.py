from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from contracts.job import JobRequest
from contracts.runtime import RuntimeContext
from workflow.artifact_store import ArtifactStore, InMemoryArtifactStore
from workflow.graph import WorkflowDefinition, WorkflowEdge
from workflow.registry import get_node_executor
from workflow.schemas import NodeExecutionContext


@dataclass(slots=True)
class WorkflowResult:
    workflow_id: str
    run_id: str
    node_outputs: dict[str, dict[str, object]] = field(default_factory=dict)
    outputs: dict[str, object] = field(default_factory=dict)
    execution_order: list[str] = field(default_factory=list)


class _ScopedProgressLogger:
    """节点内进度加权代理（需求3 批次2，2026-08-21）。

    节点执行中模块发出的 ``emit_progress``（stage 为模块自身名，如
    fy_download 的 day 级进度）原样转发保留节点详情视角；同时把
    ``[0,1]`` 节点内进度映射到该节点在整体 workflow.dispatch 的区间
    ``[base, base+span]`` 再发一条，长下载节点期间整体百分比持续更新
    而非纹丝不动。stage 以 ``workflow.`` 开头的内部事件不重复映射。
    """

    def __init__(self, inner, base: float, span: float) -> None:
        self._inner = inner
        self._base = base
        self._span = span

    def emit_progress(self, stage, progress, message, detail=None) -> None:
        if self._inner is None:
            return
        self._inner.emit_progress(stage, progress, message, detail)
        if str(stage).startswith("workflow."):
            return
        try:
            frac = max(0.0, min(1.0, float(progress)))
        except (TypeError, ValueError):
            return
        overall = min(0.999, self._base + frac * self._span)
        self._inner.emit_progress("workflow.dispatch", overall, message, detail)

    def __getattr__(self, name):  # 其余事件透传
        inner = object.__getattribute__(self, "_inner")
        if inner is None:
            # inner 为 None（纯进度包装场景）：其余事件静默 no-op
            def _noop(*args, **kwargs):
                return None

            return _noop
        return getattr(inner, name)


class WorkflowRunner:
    def __init__(
        self,
        *,
        artifact_store: ArtifactStore | None = None,
        datasource_adapter=None,
        logger_adapter=None,
        product_sink=None,
        node_parallelism: int = 1,
    ) -> None:
        self.artifact_store = artifact_store or InMemoryArtifactStore()
        self.datasource_adapter = datasource_adapter
        self.logger_adapter = logger_adapter
        self.product_sink = product_sink
        # 就绪节点并行度：1=串行（兼容旧行为）；>1 时同层无依赖节点用线程池并行。
        # 节点内算法若已用 ProcessPoolExecutor，实际进程数 = 节点并行度 × 每节点
        # 进程数，须与 CGDA_MAX_PARALLEL_WORKERS 协调避免过订阅。
        self.node_parallelism = max(1, int(node_parallelism))

    def run(
        self,
        definition: WorkflowDefinition,
        request: JobRequest,
        runtime_context: RuntimeContext,
    ) -> WorkflowResult:
        from runner.call_guard import push_runtime_call

        with push_runtime_call(runtime_context, f"workflow:{definition.workflow_id}"):
            node_map = {node.node_id: node for node in definition.nodes if node.enabled}
            if len(node_map) != len(
                [node for node in definition.nodes if node.enabled]
            ):
                raise ValueError(
                    "Duplicate enabled node_id detected in workflow definition"
                )

            layers = self._topological_layers(node_map, definition.edges)
            node_outputs: dict[str, dict[str, object]] = {}

            total_nodes = max(len(node_map), 1)
            completed = 0
            execution_order: list[str] = []

            for layer in layers:
                if self.node_parallelism <= 1 or len(layer) <= 1:
                    # 串行路径（兼容旧行为；单节点层）
                    for node_id in layer:
                        outputs = self._execute_single_node(
                            node_id,
                            node_map,
                            definition,
                            request,
                            runtime_context,
                            node_outputs,
                            progress_base=(completed / total_nodes, 1 / total_nodes),
                        )
                        node_outputs[node_id] = outputs
                        execution_order.append(node_id)
                        completed += 1
                        self._emit_node_progress(completed, total_nodes, node_id)
                else:
                    # 并行路径：同层就绪节点用线程池并行执行。
                    # node_outputs 快照只读——同层节点互不依赖，仅读之前层结果，
                    # 并行期不写 node_outputs，轮结束后批量合并（缓存隔离）。
                    snapshot = dict(node_outputs)
                    layer_results: dict[str, dict[str, object]] = {}
                    progress_lock = threading.Lock()
                    with ThreadPoolExecutor(
                        max_workers=min(self.node_parallelism, len(layer))
                    ) as pool:
                        futures = {
                            pool.submit(
                                self._execute_single_node,
                                node_id,
                                node_map,
                                definition,
                                request,
                                runtime_context,
                                snapshot,
                                progress_base=(
                                    completed / total_nodes,
                                    1 / total_nodes,
                                ),
                            ): node_id
                            for node_id in layer
                        }
                        try:
                            for fut in as_completed(futures):
                                node_id = futures[fut]
                                outputs = fut.result()  # 节点异常在此重新抛出
                                with progress_lock:
                                    layer_results[node_id] = outputs
                                    completed += 1
                                    self._emit_node_progress(
                                        completed, total_nodes, node_id
                                    )
                        except Exception:
                            # 快速失败：取消未开始 future，等待在途 future 完成后向上抛出。
                            # ThreadPoolExecutor 上下文退出时会 join 所有线程。
                            for fut in futures:
                                fut.cancel()
                            raise
                    node_outputs.update(layer_results)
                    execution_order.extend(layer)

            resolved_outputs = {
                output_spec.name: self._resolve_binding(
                    output_spec.source, request=request, node_outputs=node_outputs
                )
                for output_spec in definition.outputs
            }
            return WorkflowResult(
                workflow_id=definition.workflow_id,
                run_id=runtime_context.run_id,
                node_outputs=node_outputs,
                outputs=resolved_outputs,
                execution_order=execution_order,
            )

    def _execute_single_node(
        self,
        node_id: str,
        node_map: dict,
        definition: WorkflowDefinition,
        request: JobRequest,
        runtime_context: RuntimeContext,
        node_outputs: dict[str, dict[str, object]],
        progress_base: tuple[float, float] | None = None,
    ) -> dict[str, object]:
        """执行单个节点，返回其输出字典。

        ``node_outputs`` 为已完成节点的只读快照（并行模式下同层节点互不依赖，
        仅读之前层结果）。线程安全：本方法不写共享可变状态。

        安审 2026-08-21 H-3 更正：workspace 为 run 级共享（所有节点同一路径，
        artifact 才按 node_id 隔离）。同层并行（node_parallelism>1）时同型
        下载节点会写同一 ``data_access/*`` 子目录——现有系统种子每类下载
        节点仅一个，该约束暂由种子设计保证；若未来种子引入同层同型并行
        下载节点，须改为 workspace/node_id 派生。
        """
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
        # 需求3 批次2：节点内进度（如 fy_download 的 day 级）加权映射到整体
        # workflow.dispatch 区间，避免长下载节点期间整体百分比纹丝不动。
        node_logger = (
            _ScopedProgressLogger(
                self.logger_adapter,
                progress_base[0],
                progress_base[1],
            )
            if progress_base is not None and self.logger_adapter is not None
            else self.logger_adapter
        )
        node_ctx = NodeExecutionContext(
            workflow_id=definition.workflow_id,
            node_id=node.node_id,
            request=request,
            runtime_context=runtime_context,
            workspace=Path(runtime_context.workspace),
            artifact_store=self.artifact_store,
            datasource_adapter=self.datasource_adapter,
            logger_adapter=node_logger,
            product_sink=self.product_sink,
        )
        stage_name = f"workflow.node.{node.node_id}"
        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_start(
                stage_name, f"Execute node {node.node_id} ({node.node_type})"
            )
        try:
            outputs = executor.execute(inputs, dict(node.params), node_ctx)
        except Exception as exc:
            if self.logger_adapter is not None:
                import traceback as _tb

                self.logger_adapter.emit_error(
                    stage_name,
                    str(exc),
                    extra={
                        "workflow_id": definition.workflow_id,
                        "node_id": node.node_id,
                        "node_type": node.node_type,
                        "exception_type": type(exc).__name__,
                        "traceback": _tb.format_exc()[-1200:],
                    },
                )
            raise
        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_end(
                stage_name, f"Finished node {node.node_id}"
            )
        return outputs

    def _emit_node_progress(self, completed: int, total: int, node_id: str) -> None:
        """上报节点级进度。并行模式下由 progress_lock 保护，主线程发事件。"""
        if self.logger_adapter is not None:
            self.logger_adapter.emit_progress(
                "workflow.dispatch",
                completed / total,
                f"Completed node {node_id} ({completed}/{total})",
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
                raise ValueError(
                    f"Workflow input port received multiple bindings: {node.node_id}.{port_name}"
                )
            if port_spec is not None and port_spec.multi_input:
                resolved[port_name] = [value]
                return
            resolved[port_name] = value

        for port_name, binding in node.input_bindings.items():
            bind_input(
                port_name,
                self._resolve_binding(
                    binding, request=request, node_outputs=node_outputs
                ),
            )
        for edge in edges:
            if edge.to_node != node.node_id:
                continue
            binding = f"node:{edge.from_node}.{edge.from_port}"
            bind_input(
                edge.to_port,
                self._resolve_binding(
                    binding, request=request, node_outputs=node_outputs
                ),
            )
        for port_name, port_spec in port_specs.items():
            if port_spec.required and port_name not in resolved:
                raise ValueError(
                    f"Workflow required input port not bound: {node.node_id}.{port_name}"
                )
        # 多模块图：节点自身的 properties.algorithm_params 是该模块的参数基底；
        # 请求级 algorithm_params 仅承载用户/定时器覆盖（后端在图执行路径已
        # 剥离首模块提取，避免跨模块泄漏）。合并语义与 bridge.pipeline 一致：
        # 节点基底 + 请求级覆盖优先。ModuleNodeExecutor.get_input_ports() 恒为
        # 空，故以 resolved 中是否绑定该键（而非 port_specs）判断。
        node_algo = (
            node.params.get("algorithm_params")
            if isinstance(node.params, dict)
            else None
        )
        if isinstance(node_algo, dict) and node_algo:
            request_algo = resolved.get("algorithm_params")
            if isinstance(request_algo, dict):
                resolved["algorithm_params"] = {**node_algo, **request_algo}
            else:
                resolved["algorithm_params"] = dict(node_algo)
        return resolved

    def _resolve_binding(
        self,
        binding: str,
        *,
        request: JobRequest,
        node_outputs: dict[str, dict[str, object]],
    ) -> object:
        if binding.startswith("literal:"):
            return binding.split(":", 1)[1]
        if binding.startswith("input:"):
            input_name = binding.split(":", 1)[1]
            if input_name not in request.datasource_selection:
                # Return None for optional inputs not in datasource_selection.
                # This allows mode_required_inputs to be bound even when they
                # will be resolved from _prepared_inputs at runtime.
                return None
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

    def _topological_layers(
        self, node_map: dict[str, object], edges: list[WorkflowEdge]
    ) -> list[list[str]]:
        """拓扑分层：每层是互不依赖的就绪节点（可安全并行）。

        每轮取全部 indegree=0 节点产出分层，同层节点无边连接可并行；
        线性 DAG（每层 1 节点）退化为线性序。
        """
        indegree = {node_id: 0 for node_id in node_map}
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_map}
        for edge in edges:
            if edge.from_node not in node_map or edge.to_node not in node_map:
                raise KeyError(
                    f"Workflow edge references unknown node: {edge.from_node} -> {edge.to_node}"
                )
            adjacency[edge.from_node].append(edge.to_node)
            indegree[edge.to_node] += 1

        layers: list[list[str]] = []
        ready = sorted([node_id for node_id, degree in indegree.items() if degree == 0])
        processed = 0
        while ready:
            layers.append(ready)
            processed += len(ready)
            next_ready: list[str] = []
            for node_id in ready:
                for target in adjacency[node_id]:
                    indegree[target] -= 1
                    if indegree[target] == 0:
                        next_ready.append(target)
            next_ready.sort()
            ready = next_ready
        if processed != len(node_map):
            raise ValueError("Workflow contains a cycle")
        return layers
