from __future__ import annotations

from typing import Any

from app.workflow_engine.base import BaseNode
from app.workflow_engine.enums import PortKind, RunStatus
from app.workflow_engine.models import (
    ExecutionContext,
    NodeExecutionResult,
    NodeSpec,
    PortSpec,
)


class SummaryGenerateNode(BaseNode):
    """天气摘要生成节点，基于解析后的天气点位数据生成摘要文本与诊断信息。"""

    node_type: str = "weather_summary_generate"

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        try:
            weather_point = inputs.get("weather_point")
            if not isinstance(weather_point, dict):
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=["SummaryGenerateNode 缺少必需输入: weather_point"],
                )

            summary = self._build_summary(weather_point)
            diagnostics = self._build_diagnostics(weather_point)

            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.completed,
                outputs={
                    "summary": summary,
                    "diagnostics": diagnostics,
                },
            )
        except Exception as exc:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.failed,
                warnings=[f"SummaryGenerateNode failed: {exc}"],
            )

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id=SummaryGenerateNode.node_type,
            node_type=SummaryGenerateNode.node_type,
            input_ports=[
                PortSpec(name="weather_point", kind=PortKind.data, description="结构化天气点位数据"),
            ],
            output_ports=[
                PortSpec(name="summary", kind=PortKind.value, description="天气摘要文本"),
                PortSpec(name="diagnostics", kind=PortKind.diagnostic, description="诊断信息列表"),
            ],
        )

    @staticmethod
    def _build_summary(weather_point: dict[str, Any]) -> str:
        """基于天气点位数据生成摘要文本，优先复用已有 summary 字段。"""
        existing_summary = weather_point.get("summary")
        if isinstance(existing_summary, str) and existing_summary.strip():
            return existing_summary

        provider = weather_point.get("provider", "unknown")
        layer_id = weather_point.get("layer_id", "unknown")
        current = weather_point.get("current") or {}
        render_hint = weather_point.get("render_hint") or {}
        primary_metric = render_hint.get("primary_metric", "")
        unit_label = render_hint.get("unit_label", "")
        metric_value = current.get(primary_metric) if primary_metric else None

        if metric_value is None:
            value_text = "--"
        else:
            value_text = str(metric_value)

        return (
            f"[{provider}] layer={layer_id}, {primary_metric}={value_text} {unit_label}".strip()
        )

    @staticmethod
    def _build_diagnostics(weather_point: dict[str, Any]) -> list[str]:
        """基于天气点位数据生成诊断信息列表。"""
        diagnostics: list[str] = []
        current = weather_point.get("current") or {}

        diagnostics.append(f"provider={weather_point.get('provider', 'unknown')}")
        diagnostics.append(f"layer_id={weather_point.get('layer_id', 'unknown')}")
        diagnostics.append(f"model={weather_point.get('model', 'unknown')}")
        diagnostics.append(f"cache_status={weather_point.get('cache_status', 'unknown')}")
        diagnostics.append(f"latitude={weather_point.get('latitude', 'unknown')}")
        diagnostics.append(f"longitude={weather_point.get('longitude', 'unknown')}")

        hourly = weather_point.get("hourly") or []
        if isinstance(hourly, list):
            diagnostics.append(f"hourly_points={len(hourly)}")

        temperature = current.get("temperature_2m")
        if temperature is not None:
            diagnostics.append(f"temperature_2m={temperature}")
        wind_speed = current.get("wind_speed_10m")
        if wind_speed is not None:
            diagnostics.append(f"wind_speed_10m={wind_speed}")
        precipitation = current.get("precipitation")
        if precipitation is not None:
            diagnostics.append(f"precipitation={precipitation}")

        return diagnostics
