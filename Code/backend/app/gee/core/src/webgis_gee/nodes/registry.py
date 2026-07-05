from __future__ import annotations

from typing import Type

from webgis_gee.nodes.base import BaseNode


class NodeRegistry:
    """Registry for workflow node executors."""

    def __init__(self) -> None:
        self._node_classes: dict[str, Type[BaseNode]] = {}

    def register(self, node_type: str | None = None, node_cls: Type[BaseNode] | None = None) -> None:
        if isinstance(node_type, type) and issubclass(node_type, BaseNode):
            # 简化调用方式：register(MyNode)
            node_cls = node_type
            node_type = node_cls.node_type
        if node_cls is None:
            raise ValueError("must provide node class")
        node_type = node_type or node_cls.node_type
        if node_type in self._node_classes:
            raise ValueError(f"node type already registered: {node_type}")
        self._node_classes[node_type] = node_cls

    def get(self, node_type: str) -> Type[BaseNode]:
        try:
            return self._node_classes[node_type]
        except KeyError as exc:
            raise KeyError(f"node type not registered: {node_type}") from exc

    def supported_node_types(self) -> list[str]:
        return sorted(self._node_classes.keys())

    def has(self, node_type: str) -> bool:
        return node_type in self._node_classes
