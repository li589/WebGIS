"""共享工作流引擎包。

为 weatherengine、GEE 等模块提供统一的节点/工作流/DAG 基础设施，
为后续 ComfyUI 风格的可视化工作流编辑器做准备。
"""

from app.workflow_engine.models import (
    ArtifactRecord,
    EdgeSpec,
    ExecutionContext,
    NodeExecutionResult,
    NodeSpec,
    PortSpec,
    RunResult,
    WorkflowDefinition,
)
from app.workflow_engine.base import BaseNode
from app.workflow_engine.registry import NodeRegistry
from app.workflow_engine.executor import WorkflowExecutor

__all__ = [
    "ArtifactRecord",
    "BaseNode",
    "EdgeSpec",
    "ExecutionContext",
    "NodeExecutionResult",
    "NodeRegistry",
    "NodeSpec",
    "PortSpec",
    "RunResult",
    "WorkflowDefinition",
    "WorkflowExecutor",
]
