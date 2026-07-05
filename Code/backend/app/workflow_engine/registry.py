from __future__ import annotations

from app.workflow_engine.base import BaseNode


class NodeRegistry:
    """工作流节点执行器注册表。"""

    def __init__(self) -> None:
        self._node_classes: dict[str, type[BaseNode]] = {}

    def register(self, node_type=None, node_cls=None) -> None:
        if node_cls is None and node_type is not None:
            # 简化调用方式：register(MyNode)
            node_cls = node_type
            node_type = node_cls.node_type
        if node_type in self._node_classes:
            raise ValueError(f"node type already registered: {node_type}")
        self._node_classes[node_type] = node_cls

    def get(self, node_type: str) -> type[BaseNode]:
        if node_type not in self._node_classes:
            raise KeyError(f"node type not registered: {node_type}")
        return self._node_classes[node_type]

    def has(self, node_type: str) -> bool:
        return node_type in self._node_classes

    def supported_node_types(self) -> list[str]:
        return sorted(self._node_classes.keys())
