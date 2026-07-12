"""Engine request populator registry.

与 workflow_tasks.py 的 _BRIDGE_CHAIN 对齐的 request populator 注册表。
每个 engine（python_provider / gee / weather_workflow）注册一个 populator，
负责按 layer catalog 元数据补齐 bridge 所需请求字段。
"""

from __future__ import annotations

from typing import Any, Iterator, Protocol, runtime_checkable

from shared.contracts.api_contracts import WorkflowSubmitRequest


@runtime_checkable
class EngineRequestPopulator(Protocol):
    """Engine 请求填充器协议。

    实现要求：
    - engine_name: 与 LayerDescriptor.engine 字段对齐的引擎标识
    - populate(): 按 descriptor 元数据补齐 payload 中 engine-specific 请求字段
    - describe_resolution(): 返回该 payload 的解析诊断信息（用于 /layers 端点）
    - describe_readiness(): 返回该图层的就绪状态诊断（用于 /layers 端点）
    """

    @property
    def engine_name(self) -> str:
        """引擎标识，与 LayerDescriptor.engine 对齐。"""
        ...

    def populate(
        self,
        *,
        payload: WorkflowSubmitRequest,
        layer_id: str,
        descriptor: Any,
    ) -> WorkflowSubmitRequest:
        """按 descriptor 元数据补齐 payload 中 engine-specific 请求字段。"""
        ...

    def describe_resolution(self, payload: WorkflowSubmitRequest) -> dict[str, Any] | None:
        """返回该 payload 的解析诊断信息，不适用时返回 None。"""
        ...

    def describe_readiness(self, descriptor: Any) -> dict[str, Any] | None:
        """返回该图层的就绪状态诊断，不适用时返回 None。"""
        ...


_ENGINE_POPULATORS: dict[str, EngineRequestPopulator] = {}


def register_engine_populator(populator: EngineRequestPopulator) -> None:
    """注册一个 engine request populator。重复注册会覆盖。"""
    _ENGINE_POPULATORS[populator.engine_name] = populator


def get_engine_populator(engine_name: str) -> EngineRequestPopulator | None:
    """按 engine_name 查找 populator。"""
    return _ENGINE_POPULATORS.get(engine_name)


def iter_engine_populators() -> Iterator[EngineRequestPopulator]:
    """遍历所有已注册的 populator。"""
    return iter(_ENGINE_POPULATORS.values())
