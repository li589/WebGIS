from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from webgis_gee.domain.models import ExecutionContext, NodeExecutionResult, NodeSpec


class BaseNode(ABC):
    """Base class for all node executors."""

    node_type: str

    def __init__(self, spec: NodeSpec, context: ExecutionContext) -> None:
        self.spec = spec
        self.context = context

    @abstractmethod
    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        """Run a node and return structured outputs."""

    @abstractmethod
    def build_spec(self) -> NodeSpec:
        """Return the canonical node specification for registration metadata."""
