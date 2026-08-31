"""workflow_engine 执行内核覆盖缺口补口（2026-08-23 机制核查 A1）。

背景：图层-工作流机制核查发现 app/workflow_engine/executor.py 是天气通道
生产执行内核（WeatherWorkflowService → weather_bridge 链第 2 位）。既有覆盖
（test_business_regression.test_workflow_engine_dag / optional_edge /
optional_output_flag、test_workflow_engine_disabled_node）已含 happy path、
全局输入>params、环检测、失败中断、可选边/输出、停用节点跳过。

本文件只补未覆盖行为：
- 三级输入优先级全链（上游边 > 全局输入 > params）
- continue_on_error=False 中断后续节点 / True 继续执行并收集 errors
- 上游成功但未产出边声明端口 → 下游节点失败（KeyError 捕获进 warnings）
- 未注册 node_type → 节点失败（registry KeyError 捕获路径）
- spec.input_ports 为空 + build_spec 缺失 → RuntimeError 失败节点
- duplicate node_id → WorkflowDefinition 校验拒绝
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.workflow_engine.base import BaseNode
from app.workflow_engine.enums import RunStatus
from app.workflow_engine.executor import WorkflowExecutor
from app.workflow_engine.models import (
    ExecutionContext,
    EdgeSpec,
    NodeExecutionResult,
    NodeSpec,
    PortSpec,
    RuntimePolicy,
    WorkflowDefinition,
)
from app.workflow_engine.registry import NodeRegistry


class _RecorderNode(BaseNode):
    """回显收到的 inputs，用于断言输入解析结果。"""

    node_type = "test_recorder"

    def execute(self, inputs):
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            status=RunStatus.completed,
            outputs={"received": dict(inputs)},
        )

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(node_id="recorder", node_type="test_recorder")


class _ValueNode(BaseNode):
    """从 params 读取 v 并产出同名输出端口。"""

    node_type = "test_value"

    def execute(self, inputs):
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            status=RunStatus.completed,
            outputs={"v": inputs.get("v")},
        )

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(node_id="value", node_type="test_value")


class _FailNode(BaseNode):
    node_type = "test_fail"

    def execute(self, inputs):
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            status=RunStatus.failed,
            warnings=["intentional failure"],
        )

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(node_id="fail", node_type="test_fail")


class _NoSpecNode:
    """故意不实现 build_spec 的节点类（非 BaseNode 子类）。"""

    node_type = "test_nospec"

    def __init__(self, spec, context) -> None:  # pragma: no cover - 执行前即失败
        self.spec = spec

    def execute(self, inputs):  # pragma: no cover - 执行前即失败
        raise AssertionError("unreachable")


def _executor() -> WorkflowExecutor:
    registry = NodeRegistry()
    registry.register(_RecorderNode)
    registry.register(_ValueNode)
    registry.register(_FailNode)
    return WorkflowExecutor(registry)


def test_input_priority_edge_over_global_over_params() -> None:
    """三级输入优先级：上游边 > 全局输入 > 节点 params。"""
    executor = _executor()
    wf = WorkflowDefinition(
        workflow_id="wf-priority",
        inputs={"x": 999, "y": 7},
        nodes=[
            NodeSpec(
                node_id="src",
                node_type="test_value",
                params={"v": 10},
                output_ports=[PortSpec(name="v")],
            ),
            NodeSpec(
                node_id="dst",
                node_type="test_recorder",
                params={"y": 1, "z": 5},
                input_ports=[PortSpec(name="x"), PortSpec(name="y")],
                output_ports=[PortSpec(name="received")],
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="src",
                source_port="v",
                target_node_id="dst",
                target_port="x",
            )
        ],
    )
    result = executor.execute(wf, ExecutionContext(workflow_id="wf-priority"))
    assert result.status == RunStatus.completed
    received = result.outputs["dst.received"]
    assert received["x"] == 10  # 上游边覆盖全局输入 x=999
    assert received["y"] == 7  # 全局输入覆盖 params y=1
    assert received["z"] == 5  # params 默认值兜底


def test_continue_on_error_false_breaks_execution() -> None:
    """节点失败 + continue_on_error=False → 后续节点不再执行。"""
    executor = _executor()
    wf = WorkflowDefinition(
        workflow_id="wf-break",
        nodes=[
            NodeSpec(node_id="bad", node_type="test_fail"),
            NodeSpec(
                node_id="good",
                node_type="test_recorder",
                output_ports=[PortSpec(name="received")],
            ),
        ],
    )
    result = executor.execute(wf, ExecutionContext(workflow_id="wf-break"))
    assert result.status == RunStatus.failed
    executed = {r.node_id for r in result.node_results}
    assert executed == {"bad"}, f"失败后仍执行了后续节点: {executed}"


def test_continue_on_error_true_continues() -> None:
    """节点失败 + continue_on_error=True → 后续节点继续执行，errors 收集。"""
    executor = _executor()
    wf = WorkflowDefinition(
        workflow_id="wf-continue",
        nodes=[
            NodeSpec(node_id="bad", node_type="test_fail"),
            NodeSpec(
                node_id="good",
                node_type="test_recorder",
                output_ports=[PortSpec(name="received")],
            ),
        ],
        runtime_policy=RuntimePolicy(continue_on_error=True),
    )
    result = executor.execute(wf, ExecutionContext(workflow_id="wf-continue"))
    assert result.status == RunStatus.failed
    assert len(result.errors) == 1
    executed = {r.node_id for r in result.node_results}
    assert executed == {"bad", "good"}, f"continue_on_error 下后续节点未执行: {executed}"
    assert "good.received" in result.outputs


def test_missing_required_upstream_output_fails_node() -> None:
    """上游成功但未产出边声明端口 → 下游节点失败（KeyError 捕获进 warnings）。"""
    executor = _executor()
    wf = WorkflowDefinition(
        workflow_id="wf-missing",
        nodes=[
            NodeSpec(
                node_id="src",
                node_type="test_value",
                params={"v": 1},
                output_ports=[PortSpec(name="v")],
            ),
            NodeSpec(
                node_id="dst",
                node_type="test_recorder",
                input_ports=[PortSpec(name="x")],
                output_ports=[PortSpec(name="received")],
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="src",
                source_port="nonexistent",
                target_node_id="dst",
                target_port="x",
            )
        ],
    )
    result = executor.execute(wf, ExecutionContext(workflow_id="wf-missing"))
    assert result.status == RunStatus.failed
    dst = next(r for r in result.node_results if r.node_id == "dst")
    assert dst.status == RunStatus.failed
    assert any("missing required upstream outputs" in w for w in dst.warnings)


def test_unregistered_node_type_fails_node() -> None:
    """registry 未注册的 node_type → KeyError 被捕获，节点失败。"""
    executor = _executor()  # 未注册 "ghost"
    wf = WorkflowDefinition(
        workflow_id="wf-ghost",
        nodes=[NodeSpec(node_id="g", node_type="ghost")],
    )
    result = executor.execute(wf, ExecutionContext(workflow_id="wf-ghost"))
    assert result.status == RunStatus.failed
    assert len(result.node_results) == 1
    assert any("not registered" in w for w in result.node_results[0].warnings)


def test_broken_build_spec_fails_node() -> None:
    """spec.input_ports 为空时回退 build_spec()；节点类缺失该静态方法时
    应以 RuntimeError 失败节点（暴露编程 bug，而非静默吞掉）。"""
    registry = NodeRegistry()
    registry.register("test_nospec", _NoSpecNode)
    executor = WorkflowExecutor(registry)
    wf = WorkflowDefinition(
        workflow_id="wf-nospec",
        nodes=[NodeSpec(node_id="n", node_type="test_nospec")],
    )
    result = executor.execute(wf, ExecutionContext(workflow_id="wf-nospec"))
    assert result.status == RunStatus.failed
    assert len(result.node_results) == 1
    assert any("build_spec" in w for w in result.node_results[0].warnings)


def test_duplicate_node_id_rejected() -> None:
    """WorkflowDefinition 校验：重复 node_id 必须在定义期拒绝。"""
    with pytest.raises(ValidationError):
        WorkflowDefinition(
            workflow_id="wf-dup",
            nodes=[
                NodeSpec(node_id="a", node_type="t"),
                NodeSpec(node_id="a", node_type="t"),
            ],
        )
