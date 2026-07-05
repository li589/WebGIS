from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.workflow_engine.models import ExecutionContext, NodeExecutionResult, NodeSpec


class BaseNode(ABC):
    """所有节点执行器的基类。"""

    node_type: str

    def __init__(self, spec: NodeSpec, context: ExecutionContext) -> None:
        self.spec = spec
        self.context = context

    @abstractmethod
    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        """执行节点并返回结构化输出。"""

    @staticmethod
    @abstractmethod
    def build_spec() -> NodeSpec:
        """返回节点的规范规格，用于注册元数据。

        C4 修复：声明为 staticmethod，与所有子类实现一致。
        规格描述无需实例化即可用于注册元数据。
        """
