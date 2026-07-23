"""Layer output strategy registry.

提供策略注册与查找。支持精确匹配与前缀匹配（如 "wind-field-xxx" 匹配 "wind-field" 前缀策略）。

线程安全：注册与查找均通过 _REGISTRY_LOCK 串行化。
查找顺序：精确匹配优先，其次按注册顺序遍历前缀策略。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from app.weatherengine.layer_outputs.base import LayerOutputStrategy

logger = logging.getLogger(__name__)

_REGISTRY_LOCK = threading.Lock()
_REGISTRY: dict[str, type[LayerOutputStrategy]] = {}
# 前缀策略列表：(prefix, cls) 按注册顺序排列，查找时先注册先匹配
_PREFIX_STRATEGIES: list[tuple[str, type[LayerOutputStrategy]]] = []


def register_strategy(
    layer_id: str,
    *,
    prefix: bool = False,
) -> Callable[[type[LayerOutputStrategy]], type[LayerOutputStrategy]]:
    """策略注册装饰器。

    参数:
        layer_id: 精确匹配的 layer_id，或前缀匹配的前缀字符串
        prefix: True 时按前缀匹配（layer_id.startswith），False 时按精确匹配

    返回类装饰器。重复注册精确匹配会覆盖并告警；前缀注册允许多个（按注册顺序匹配）。
    """

    def decorator(cls: type[LayerOutputStrategy]) -> type[LayerOutputStrategy]:
        with _REGISTRY_LOCK:
            if prefix:
                _PREFIX_STRATEGIES.append((layer_id, cls))
                logger.debug(
                    "Registered prefix layer output strategy: %s -> %s",
                    layer_id,
                    cls.__name__,
                )
            else:
                if layer_id in _REGISTRY:
                    logger.warning(
                        "Overwriting registered layer output strategy: %s (old=%s new=%s)",
                        layer_id,
                        _REGISTRY[layer_id].__name__,
                        cls.__name__,
                    )
                _REGISTRY[layer_id] = cls
                logger.debug(
                    "Registered layer output strategy: %s -> %s", layer_id, cls.__name__
                )
        return cls

    return decorator


def get_strategy(layer_id: str) -> LayerOutputStrategy | None:
    """查找策略。优先精确匹配，其次前缀匹配（按注册顺序）。未命中返回 None。

    每次返回新实例：策略无状态，开销可忽略；避免共享实例带来的潜在并发问题。
    """
    with _REGISTRY_LOCK:
        cls = _REGISTRY.get(layer_id)
        if cls is None:
            for prefix, prefix_cls in _PREFIX_STRATEGIES:
                if layer_id.startswith(prefix):
                    cls = prefix_cls
                    break
    if cls is None:
        return None
    return cls()


def clear_registry() -> None:
    """清空注册表（仅用于测试隔离）。"""
    with _REGISTRY_LOCK:
        _REGISTRY.clear()
        _PREFIX_STRATEGIES.clear()


def list_registered() -> dict[str, list[str]]:
    """返回当前注册的策略快照（用于诊断/测试）。返回 {kind: [names]}。"""
    with _REGISTRY_LOCK:
        return {
            "exact": [f"{k} -> {v.__name__}" for k, v in _REGISTRY.items()],
            "prefix": [f"{p} -> {c.__name__}" for p, c in _PREFIX_STRATEGIES],
        }
