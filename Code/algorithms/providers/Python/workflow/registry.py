from __future__ import annotations

from typing import Any


NODE_EXECUTOR_REGISTRY: dict[str, type[Any]] = {}


def register_node_executor(node_type: str, executor_cls: type[Any]) -> None:
    NODE_EXECUTOR_REGISTRY[node_type] = executor_cls


def get_node_executor(node_type: str) -> type[Any]:
    if node_type not in NODE_EXECUTOR_REGISTRY:
        if node_type == "module":
            from workflow import module_executor  # noqa: F401
        elif node_type == "bridge.pipeline":
            from workflow import bridge  # noqa: F401
    if node_type not in NODE_EXECUTOR_REGISTRY:
        raise KeyError(f"Node executor not registered: {node_type}")
    return NODE_EXECUTOR_REGISTRY[node_type]
