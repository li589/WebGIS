"""课题组样板 provider（lab-output）。

此模块为过渡样板 provider，用于验证 provider bridge 链路完整性与界面验收，
不代表正式生产能力。正式课题组模型应通过 ``algorithm_entrypoint`` 字段
接入真实算法实现，否则将回退到内置合成数据。

状态：sample / compat — 不作为正式业务结果事实源。
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin
import os

from algorithms.adapters.provider_adapter import (
    adapt_algorithm_output,
    resolve_algorithm_callable,
)
from algorithms.providers.base import ProviderExecutionPayload, ProviderExecutionResult


@dataclass
class LabOutputProvider:
    provider_key: str = "lab_output_v1"
    supported_layers: tuple[str, ...] = ("lab-output",)

    def execute(self, payload: ProviderExecutionPayload) -> ProviderExecutionResult:
        algorithm_entrypoint = self._resolve_algorithm_entrypoint(payload)
        if algorithm_entrypoint:
            algorithm_callable = resolve_algorithm_callable(algorithm_entrypoint)
            raw_result = algorithm_callable(payload)
            if not isinstance(raw_result, dict):
                raise ValueError("Algorithm entrypoint must return a dict payload.")
            adapted = adapt_algorithm_output(
                raw_result,
                provider_key=self.provider_key,
                layer_id=payload.layer_id,
                default_title="课题组模型输出",
                default_summary="已通过动态算法入口接入真实课题组实现。",
                default_metric_label="综合风险评分",
                default_metric_unit="/ 100",
            )
            adapted.diagnostics.extend(
                [
                    f"algorithm_entrypoint={algorithm_entrypoint}",
                    "当前结果来自外部算法实现。",
                ]
            )
            return adapted

        center_lng, center_lat = self._resolve_center(payload.spatial_filter)
        hour = payload.requested_hour
        base_score = self._resolve_base_score(hour, center_lng, center_lat)
        hotspot_count = self._resolve_hotspot_count(payload)
        series_step_hours = self._resolve_series_step(payload)
        hotspots = self._build_hotspots(
            base_score, center_lng, center_lat, hotspot_count
        )
        series = self._build_series(base_score, hour, series_step_hours)
        max_hotspot = max((item["risk_score"] for item in hotspots), default=base_score)

        return ProviderExecutionResult(
            provider_key=self.provider_key,
            layer_id=payload.layer_id,
            title="课题组模型输出",
            summary="基于统一 provider 接口生成的首条真实工作流结果，可直接替换为课题组正式模型实现。",
            metric_label="综合风险评分",
            metric_unit="/ 100",
            metric_value=round(base_score, 1),
            status_label="Provider 已执行",
            confidence_label="接口联调阶段",
            hotspots=hotspots,
            series=series,
            diagnostics=[
                "已命中 algorithms/providers/lab_output.py。",
                "当前为 provider 统一接口适配版，可直接替换内部核心计算。",
                f"resolved_center=({center_lng:.4f},{center_lat:.4f})",
                f"requested_hour={hour}",
                f"hotspot_count={len(hotspots)}",
                f"series_points={len(series)}",
            ],
            metadata={
                "max_hotspot_score": max_hotspot,
                "spatial_filter_type": payload.spatial_filter.get("filter_type"),
            },
        )

    def _resolve_algorithm_entrypoint(
        self, payload: ProviderExecutionPayload
    ) -> str | None:
        env_entrypoint = os.getenv("LAB_OUTPUT_ALGORITHM_ENTRYPOINT", "").strip()
        return env_entrypoint or None

    def _resolve_center(self, spatial_filter: dict[str, object]) -> tuple[float, float]:
        bbox = spatial_filter.get("bbox") if isinstance(spatial_filter, dict) else None
        if isinstance(bbox, dict):
            west = float(bbox.get("west", 113.3))
            east = float(bbox.get("east", 113.9))
            south = float(bbox.get("south", 22.5))
            north = float(bbox.get("north", 23.3))
            return ((west + east) / 2, (south + north) / 2)
        return (113.52, 22.86)

    def _resolve_base_score(self, hour: float, lng: float, lat: float) -> float:
        diurnal = 78 + sin((hour / 24) * 6.28318 - 1.5708) * 6
        spatial_bias = cos(radians(lat * 3.2)) * 2.2 + sin(radians(lng * 2.1)) * 1.8
        return max(0, min(100, diurnal + spatial_bias))

    def _resolve_hotspot_count(self, payload: ProviderExecutionPayload) -> int:
        requested = payload.parameters.get("hotspot_count", 3)
        if not isinstance(requested, int):
            return 3
        return max(
            3, min(requested, int(payload.execution_limits.get("max_hotspots", 200)))
        )

    def _resolve_series_step(self, payload: ProviderExecutionPayload) -> int:
        requested = payload.parameters.get("series_step_hours", 6)
        if not isinstance(requested, int) or requested <= 0:
            return 6
        return max(1, min(requested, 12))

    def _build_hotspots(
        self,
        base_score: float,
        center_lng: float,
        center_lat: float,
        hotspot_count: int,
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        base_names = [
            "广州北部",
            "东莞中部",
            "深圳西部",
            "佛山南部",
            "珠海东侧",
            "中山东部",
        ]
        for index in range(hotspot_count):
            name = f"{base_names[index % len(base_names)]}-{index + 1:02d}"
            lng_offset = ((index % 10) - 5) * 0.041
            lat_offset = ((index % 7) - 3) * 0.036
            drift = ((index % 9) - 4) * 0.8
            value = round(max(0, min(100, base_score + drift)), 1)
            items.append(
                {
                    "name": name,
                    "lng": round(center_lng + lng_offset, 5),
                    "lat": round(center_lat + lat_offset, 5),
                    "risk_score": value,
                }
            )
        items.sort(key=lambda item: float(item["risk_score"]), reverse=True)
        return items

    def _build_series(
        self, base_score: float, hour: float, step_hours: int
    ) -> list[dict[str, object]]:
        series_points: list[dict[str, object]] = []
        for point_hour in range(0, 24, step_hours):
            phase_adjust = sin(((point_hour - hour + 24) % 24) / 24 * 6.28318) * 3.4
            series_points.append(
                {
                    "label": f"{point_hour:02d}:00",
                    "value": round(max(0, min(100, base_score + phase_adjust)), 1),
                }
            )
        return series_points


lab_output_provider = LabOutputProvider()
