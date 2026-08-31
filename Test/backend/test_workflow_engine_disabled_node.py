"""批次5 C-6（2026-08-23）：workflow_engine 停用节点（enabled=false）执行跳过回归。

背景：NodeSpec 此前无 enabled 字段（pydantic 丢 extra），executor 照常执行
画布上已停用的节点。compiler 侧已完备（enabled 剥离/标记/输出过滤/悬挂边剔除），
缺执行侧跳过。修复 = NodeSpec.enabled + executor 循环跳过。
"""

from __future__ import annotations

from app.workflow_engine.enums import RunStatus
from app.workflow_engine.executor import WorkflowExecutor
from app.workflow_engine.models import (
    ExecutionContext,
    NodeSpec,
    RunResult,
    WorkflowDefinition,
)


class _FakeNode:
    def __init__(self, node_spec: NodeSpec, context: ExecutionContext) -> None:
        self.node_spec = node_spec
        self.executed = False

    def execute(self, inputs):
        from app.workflow_engine.models import NodeExecutionResult

        self.executed = True
        return NodeExecutionResult(
            node_id=self.node_spec.node_id,
            status=RunStatus.completed,
            outputs={"value": self.node_spec.node_id},
        )

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="canonical",
            node_type="canonical",
            input_ports=[],
            output_ports=[],
        )


class _FakeRegistry:
    def __init__(self) -> None:
        self.nodes: dict[str, _FakeNode] = {}

    def get(self, node_type: str) -> type[_FakeNode]:
        return _FakeNode


def _make_workflow(nodes: list[NodeSpec], edges=()) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id="wf-disabled-test",
        name="wf-disabled-test",
        nodes=nodes,
        edges=list(edges),
        inputs={},
    )


def _run(nodes, edges=()):
    registry = _FakeRegistry()
    executor = WorkflowExecutor(registry)  # type: ignore[arg-type]
    context = ExecutionContext(
        workflow_run_id="run-test",
        workflow_id="wf-disabled-test",
        variables={},
    )
    result = executor.execute(_make_workflow(nodes, edges), context)
    return result


def test_disabled_node_skipped() -> None:
    normal = NodeSpec(node_id="n1", node_type="t1")
    disabled = NodeSpec(node_id="n2", node_type="t2", enabled=False)
    result = _run([normal, disabled])
    assert result.status == RunStatus.completed
    executed_ids = {r.node_id for r in result.node_results}
    assert executed_ids == {"n1"}, f"disabled 节点被执行了: {executed_ids}"


def test_enabled_default_true() -> None:
    assert NodeSpec(node_id="a", node_type="t").enabled is True


def test_all_disabled_still_succeeds() -> None:
    disabled_a = NodeSpec(node_id="a", node_type="t", enabled=False)
    disabled_b = NodeSpec(node_id="b", node_type="t", enabled=False)
    result = _run([disabled_a, disabled_b])
    assert result.status == RunStatus.completed
    assert result.node_results == []


def test_disabled_node_type_spec_parse() -> None:
    """编译产物 dict 里的 enabled=false 必须能进 NodeSpec（此前被 extra 丢弃）。"""
    spec = NodeSpec.model_validate({"node_id": "x", "node_type": "t", "enabled": False})
    assert spec.enabled is False
