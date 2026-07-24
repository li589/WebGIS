"""Layer output strategy base class.

策略模式基础设施：将 WeatherEngineService._build_map_layer_outputs 中的 if/elif 分支
抽取为可插拔策略。Sprint 3 将 6 个分支（wind-field/temperature/precipitation/
humidity/pressure/visibility）全部迁移到独立策略类。

接口契约：
- 策略 build() 返回 LayerOutputResult（中间产物），service.py 负责公共前部
  （point_feature 初始化）和公共后部（append weather-layer result_ref + log + return）。
- 返回 None 表示策略未处理（调用方 fallback）；当前 6 个 layer_id 均已注册，
  正常路径不会返回 None。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class LayerOutputResult:
    """策略构建结果（中间产物）。

    service.py 的 _build_map_layer_outputs 用这些字段填充公共 result_ref 和 log。
    所有字段均可选（geojson_ref 必填，其余可选），以适配不同 layer_id 的产出差异。

    量纲: diagnostics 为字符串列表（人类可读诊断信息），bbox 为 RenderBBox 对象。
    """

    geojson_ref: Any
    cog_ref: Any | None = None
    diagnostics: list[str] = field(default_factory=list)
    bbox: Any | None = None


class LayerOutputStrategy(ABC):
    """地图图层输出策略抽象基类。

    每个策略负责处理一种 layer_id 的分支特定逻辑（构建 GeoJSON + COG + 诊断）。
    返回 LayerOutputResult 或 None（fallback）。

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
    ) -> LayerOutputResult | None:
        """构建图层输出中间产物。

        参数与 WeatherEngineService._build_map_layer_outputs 一致（除 self 外多一个
        service 引用，用于访问 service 的辅助方法如 _resolve_render_bbox /
        _fetch_layer_grid_data / build_wind_geojson_from_grid / _build_temperature_cog_artifact 等）。

        返回 LayerOutputResult 或 None（fallback 到原 if/elif 链，当前不会发生）。
        """
        raise NotImplementedError
