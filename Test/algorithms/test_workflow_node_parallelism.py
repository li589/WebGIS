"""工作流就绪节点并行执行测试。

验证 WorkflowRunner 的节点级并行能力：
- 拓扑分层正确（同层无依赖节点可并行）
- 并行 vs 串行结果一致（浮点精度不因并行改变）
- 并行实际并发执行（耗时显著短于串行）
- 节点异常快速传播（不死锁、不静默吞错）
- execution_order 在串行模式下与原行为一致
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path

from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
from workflow.executor import WorkflowRunner
from workflow.graph import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNodeSpec,
    WorkflowOutputSpec,
)
from workflow.registry import NODE_EXECUTOR_REGISTRY, register_node_executor
from workflow.schemas import NodeExecutionContext, PortSpec


class _AddNodeExecutor:
    """单输入加法节点：result = float(x) + float(params['offset'])。"""

    node_type = "test.add"

    def get_input_ports(self) -> list[PortSpec]:
        return [PortSpec(name="x", kind="scalar", data_class="python_object")]

    def get_output_ports(self) -> list[PortSpec]:
        return [PortSpec(name="result", kind="scalar", data_class="python_object")]

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = ctx
        x = float(inputs["x"])  # type: ignore[arg-type]
        offset = float(params["offset"])  # type: ignore[arg-type]
        return {"result": x + offset}


class _SlowAddNodeExecutor(_AddNodeExecutor):
    """带 sleep 的加法节点，用于验证并行实际并发。"""

    node_type = "test.slow_add"

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        time.sleep(float(params.get("delay", 0.2)))  # type: ignore[arg-type]
        return super().execute(inputs, params, ctx)


class _MergeNodeExecutor:
    """多输入求和节点：result = sum(values)。"""

    node_type = "test.merge"

    def get_input_ports(self) -> list[PortSpec]:
        return [
            PortSpec(
                name="values",
                kind="scalar",
                data_class="python_object",
                multi_input=True,
            )
        ]

    def get_output_ports(self) -> list[PortSpec]:
        return [PortSpec(name="result", kind="scalar", data_class="python_object")]

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = (params, ctx)
        values = inputs["values"]
        if not isinstance(values, list):
            values = [values]
        return {"result": sum(float(v) for v in values)}


class _FailingNodeExecutor:
    """始终抛异常的节点，验证异常快速传播。"""

    node_type = "test.failing"

    def get_input_ports(self) -> list[PortSpec]:
        return [PortSpec(name="x", kind="scalar", data_class="python_object")]

    def get_output_ports(self) -> list[PortSpec]:
        return [PortSpec(name="result", kind="scalar", data_class="python_object")]

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = (inputs, params, ctx)
        raise RuntimeError("intentional node failure for test")


def _build_diamond_definition(*, slow: bool = False) -> WorkflowDefinition:
    """Diamond DAG: A → {B, C} → D。B/C 同层可并行。

    A: test.literal value=1.0
    B: test.add/test.slow_add offset=0.1  ← A
    C: test.add/test.slow_add offset=0.2  ← A
    D: test.merge ← B, C
    """
    add_type = "test.slow_add" if slow else "test.add"
    return WorkflowDefinition(
        workflow_id="wf-diamond",
        nodes=[
            WorkflowNodeSpec(
                node_id="A", node_type="test.literal", params={"value": 1.0}
            ),
            WorkflowNodeSpec(
                node_id="B", node_type=add_type, params={"offset": 0.1, "delay": 0.2}
            ),
            WorkflowNodeSpec(
                node_id="C", node_type=add_type, params={"offset": 0.2, "delay": 0.2}
            ),
            WorkflowNodeSpec(node_id="D", node_type="test.merge"),
        ],
        edges=[
            WorkflowEdge(from_node="A", from_port="value", to_node="B", to_port="x"),
            WorkflowEdge(from_node="A", from_port="value", to_node="C", to_port="x"),
            WorkflowEdge(
                from_node="B", from_port="result", to_node="D", to_port="values"
            ),
            WorkflowEdge(
                from_node="C", from_port="result", to_node="D", to_port="values"
            ),
        ],
        outputs=[
            WorkflowOutputSpec(name="final", source="node:D.result"),
        ],
    )


def _make_request_and_context(tmp_dir: str, job_id: str = "job-diamond"):
    workspace = Path(tmp_dir)
    request = JobRequest(
        job_id=job_id,
        pipeline_name="workflow",
        task_type="workflow",
        time_range=TimeRange(start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)),
        region=RegionSpec(kind="global", value={}),
        datasource_selection={},
        algorithm_params={},
        output_spec=OutputSpec(),
    )
    runtime_context = RuntimeContext(
        job_id=request.job_id,
        run_id=f"run-{job_id}",
        workspace=workspace,
        tmp_dir=workspace / "tmp",
        cache_dir=workspace / "cache",
    )
    runtime_context.tmp_dir.mkdir(parents=True, exist_ok=True)
    runtime_context.cache_dir.mkdir(parents=True, exist_ok=True)
    return request, runtime_context


class WorkflowNodeParallelismTests(unittest.TestCase):
    """节点级并行执行测试。"""

    def setUp(self) -> None:
        # 保存原始注册表状态，测试后恢复（避免污染其他测试）
        self._saved: dict[str, object] = {}
        for cls in (
            _AddNodeExecutor,
            _SlowAddNodeExecutor,
            _MergeNodeExecutor,
            _FailingNodeExecutor,
        ):
            self._saved[cls.node_type] = NODE_EXECUTOR_REGISTRY.get(cls.node_type)
            register_node_executor(cls.node_type, cls)
        # test.literal 由 test_workflow_runner.py 注册；若未注册则注册一个本地版本
        if "test.literal" not in NODE_EXECUTOR_REGISTRY:

            class _Literal:
                node_type = "test.literal"

                def get_input_ports(self) -> list[PortSpec]:
                    return []

                def get_output_ports(self) -> list[PortSpec]:
                    return [
                        PortSpec(
                            name="value", kind="scalar", data_class="python_object"
                        )
                    ]

                def execute(self, inputs, params, ctx):  # type: ignore[no-untyped-def]
                    _ = (inputs, ctx)
                    return {"value": params["value"]}

            self._saved["test.literal"] = None
            register_node_executor("test.literal", _Literal)

    def tearDown(self) -> None:
        for node_type, original in self._saved.items():
            if original is None:
                NODE_EXECUTOR_REGISTRY.pop(node_type, None)
            else:
                NODE_EXECUTOR_REGISTRY[node_type] = original

    def test_topological_layers_groups_diamond(self) -> None:
        """拓扑分层：Diamond DAG 应分为 [A], [B, C], [D] 三层。"""
        definition = _build_diamond_definition()
        node_map = {n.node_id: n for n in definition.nodes if n.enabled}
        runner = WorkflowRunner()
        layers = runner._topological_layers(node_map, definition.edges)
        self.assertEqual(layers, [["A"], ["B", "C"], ["D"]])

    def test_parallel_matches_serial_results(self) -> None:
        """并行(parallelism=4)与串行(parallelism=1)结果完全一致（浮点精度不变）。"""
        definition = _build_diamond_definition()
        with tempfile.TemporaryDirectory() as tmp_dir:
            req, ctx = _make_request_and_context(tmp_dir, "job-precision")
            serial_runner = WorkflowRunner(node_parallelism=1)
            serial_result = serial_runner.run(definition, req, ctx)

            req2, ctx2 = _make_request_and_context(tmp_dir, "job-precision-parallel")
            parallel_runner = WorkflowRunner(node_parallelism=4)
            parallel_result = parallel_runner.run(definition, req2, ctx2)

            # 浮点精确相等：并行不改变数值计算路径（同输入同操作）
            self.assertEqual(
                serial_result.outputs["final"], parallel_result.outputs["final"]
            )
            # 期望值：(1.0 + 0.1) + (1.0 + 0.2) = 2.3
            self.assertAlmostEqual(
                float(parallel_result.outputs["final"]), 2.3, places=10
            )
            # 两个分支节点输出也应一致
            self.assertEqual(
                serial_result.node_outputs["B"]["result"],
                parallel_result.node_outputs["B"]["result"],
            )
            self.assertEqual(
                serial_result.node_outputs["C"]["result"],
                parallel_result.node_outputs["C"]["result"],
            )

    def test_parallel_executes_concurrently(self) -> None:
        """并行模式下同层 sleep 节点实际并发（耗时 << 串行）。"""
        definition = _build_diamond_definition(slow=True)
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 串行：B(0.2s) + C(0.2s) = ~0.4s
            req, ctx = _make_request_and_context(tmp_dir, "job-slow-serial")
            serial_runner = WorkflowRunner(node_parallelism=1)
            t0 = time.monotonic()
            serial_runner.run(definition, req, ctx)
            serial_elapsed = time.monotonic() - t0

            # 并行：B(0.2s) || C(0.2s) = ~0.2s
            req2, ctx2 = _make_request_and_context(tmp_dir, "job-slow-parallel")
            parallel_runner = WorkflowRunner(node_parallelism=4)
            t1 = time.monotonic()
            parallel_runner.run(definition, req2, ctx2)
            parallel_elapsed = time.monotonic() - t1

        # 并行应显著快于串行（至少快 30%）
        self.assertLess(
            parallel_elapsed,
            serial_elapsed * 0.7,
            f"parallel ({parallel_elapsed:.3f}s) not faster than serial "
            f"({serial_elapsed:.3f}s)",
        )

    def test_parallel_propagates_node_failure(self) -> None:
        """节点异常在并行模式下快速传播，不死锁。"""
        definition = WorkflowDefinition(
            workflow_id="wf-fail",
            nodes=[
                WorkflowNodeSpec(
                    node_id="A", node_type="test.literal", params={"value": 1.0}
                ),
                WorkflowNodeSpec(
                    node_id="B", node_type="test.failing", params={"offset": 0.1}
                ),
                WorkflowNodeSpec(
                    node_id="C", node_type="test.add", params={"offset": 0.2}
                ),
            ],
            edges=[
                WorkflowEdge(
                    from_node="A", from_port="value", to_node="B", to_port="x"
                ),
                WorkflowEdge(
                    from_node="A", from_port="value", to_node="C", to_port="x"
                ),
            ],
            outputs=[WorkflowOutputSpec(name="c", source="node:C.result")],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            req, ctx = _make_request_and_context(tmp_dir, "job-fail")
            runner = WorkflowRunner(node_parallelism=4)
            with self.assertRaisesRegex(RuntimeError, "intentional node failure"):
                runner.run(definition, req, ctx)

    def test_serial_execution_order_preserved(self) -> None:
        """串行模式(parallelism=1)下 execution_order 与原拓扑序一致。"""
        definition = _build_diamond_definition()
        with tempfile.TemporaryDirectory() as tmp_dir:
            req, ctx = _make_request_and_context(tmp_dir, "job-order")
            runner = WorkflowRunner(node_parallelism=1)
            result = runner.run(definition, req, ctx)
            # 串行按层序：A, B, C, D
            self.assertEqual(result.execution_order, ["A", "B", "C", "D"])

    def test_parallel_is_thread_safe_for_node_outputs(self) -> None:
        """并行模式下 node_outputs 不会因并发写而损坏（缓存隔离）。"""
        # 构造 5 个独立叶子节点（同层全并行），各自输出独立 key
        nodes = [
            WorkflowNodeSpec(
                node_id=f"N{i}", node_type="test.literal", params={"value": float(i)}
            )
            for i in range(5)
        ]
        definition = WorkflowDefinition(
            workflow_id="wf-fanout",
            nodes=nodes,
            edges=[],
            outputs=[
                WorkflowOutputSpec(name=f"out{i}", source=f"node:N{i}.value")
                for i in range(5)
            ],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            req, ctx = _make_request_and_context(tmp_dir, "job-fanout")
            runner = WorkflowRunner(node_parallelism=5)
            result = runner.run(definition, req, ctx)
            for i in range(5):
                self.assertEqual(result.outputs[f"out{i}"], float(i))

    def test_node_parallelism_clamped_to_minimum_one(self) -> None:
        """node_parallelism < 1 被钳制为 1（安全降级）。"""
        runner = WorkflowRunner(node_parallelism=0)
        self.assertEqual(runner.node_parallelism, 1)
        runner_neg = WorkflowRunner(node_parallelism=-3)
        self.assertEqual(runner_neg.node_parallelism, 1)


if __name__ == "__main__":
    unittest.main()
