"""Default layer output strategy (fallback placeholder).

不处理任何 layer_id，始终返回 None，让 service.py 走原 if/elif 链。

Sprint 2.3 阶段作为类型示例与未来迁移目标存在；Sprint 3 迁移具体分支后此占位类可移除。
此类不注册到 registry（service.py 在 registry 未命中时本就会走原 if/elif 链）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.weatherengine.layer_outputs.base import LayerOutputStrategy


class DefaultLayerOutput(LayerOutputStrategy):
    """默认占位策略：始终返回 None，触发调用方 fallback 到原 if/elif 链。

    作为策略模式骨架的示例实现，演示子类应如何重写 build()。当前不注册到 registry。
    """

    def build(
        self,
        *,
        service: Any,
        run_id: str,
        payload: Any,
        requested_at: datetime,
        weather: Any,
        spec: Any,
        metric_value: float | int | str | None,
    ) -> tuple[list[Any], list[str]] | None:
        return None