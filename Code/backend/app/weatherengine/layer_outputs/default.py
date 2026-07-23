"""Default layer output strategy (fallback placeholder).

不处理任何 layer_id，始终返回 None，让 service.py 走原 if/elif 链。

Sprint 3 已将 6 个分支全部迁移到具体策略类，此类保留作为类型示例与未注册 layer_id
的占位（service.py 在 registry 未命中时本就会跳过策略块）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.weatherengine.layer_outputs.base import LayerOutputResult, LayerOutputStrategy


class DefaultLayerOutput(LayerOutputStrategy):
    """默认占位策略：始终返回 None，触发调用方 fallback。

    作为策略模式骨架的示例实现。当前不注册到 registry。
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
    ) -> LayerOutputResult | None:
        return None
