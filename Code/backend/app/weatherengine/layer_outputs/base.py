"""Layer output strategy base class.

策略模式基础设施：将 WeatherEngineService._build_map_layer_outputs 中的 if/elif 分支
抽取为可插拔策略。Sprint 2.3 仅引入基础设施，不迁移具体分支；具体分支迁移留到 Sprint 3
增量做。

无行为变更约束：当前 registry 为空，service.py 始终 fallback 到原 if/elif 链。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class LayerOutputStrategy(ABC):
    """地图图层输出策略抽象基类。

    每个策略负责处理一种 layer_id 的输出构建（GeoJSON + COG + result_refs）。
    返回 None 表示策略未处理该请求，调用方应 fallback 到默认 if/elif 链。

    量纲: metric_value 无量纲（气象指标值），requested_at 为 UTC ISO 时间戳。
    """

    @abstractmethod
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
        """构建图层输出。

        参数与 WeatherEngineService._build_map_layer_outputs 完全一致（除 self 外多一个
        service 引用，用于访问 service 的辅助方法如 _resolve_render_bbox /
        _fetch_layer_grid_data / build_wind_geojson_from_grid 等）。

        返回 (result_refs, diagnostics) 元组，或 None 表示未处理（调用方 fallback）。
        """
        raise NotImplementedError
