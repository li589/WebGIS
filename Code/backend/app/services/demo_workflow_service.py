from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from app.services.demo_snapshots import get_demo_layer_snapshot
from app.services.workflow_execution import WorkflowExecutionResult
from shared.contracts.api_contracts import ResultKind, WorkflowResultReference, WorkflowSubmitRequest


class DemoWorkflowService:
    def execute(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        event_factory,
    ) -> WorkflowExecutionResult:
        layer_id = payload.layer_id or payload.map_context.active_layer_id or "wind-field"
        requested_hour = self._resolve_requested_hour(payload)
        snapshot = get_demo_layer_snapshot(layer_id, requested_hour)
        if snapshot is None:
            raise ValueError(f"Unsupported legacy/demo workflow layer: {layer_id}")

        metric_value = self._extract_metric_value(snapshot.raw_payload, snapshot.field_aliases.metric_value)
        hotspot_rows = self._build_hotspot_rows(snapshot)

        result_refs = [
            WorkflowResultReference(
                result_id=f"result-{uuid4().hex[:10]}",
                result_kind=ResultKind.json,
                title=f"{snapshot.display_name} 工作流结果",
                mime_type="application/json",
                inline_data={
                    "workflow": {
                        "run_id": run_id,
                        "command_type": payload.command_type.value,
                        "layer_id": layer_id,
                        "requested_hour": snapshot.requested_hour,
                    },
                    "snapshot": snapshot.model_dump(mode="json"),
                    "analysis": {
                        "metric_value": metric_value,
                        "metric_label": snapshot.metric_label,
                        "metric_unit": snapshot.metric_unit,
                        "hotspot_count": len(hotspot_rows),
                        "top_hotspot": hotspot_rows[0] if hotspot_rows else None,
                    },
                },
                updated_at=requested_at,
            )
        ]

        requested_output_kinds = {str(item) for item in payload.requested_outputs}
        requested_output_kinds.update(
            item.value for item in payload.requested_outputs if isinstance(item, ResultKind)
        )

        if ResultKind.table.value in requested_output_kinds:
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"table-{uuid4().hex[:10]}",
                    result_kind=ResultKind.table,
                    title=f"{snapshot.display_name} 热点表",
                    mime_type="application/json",
                    inline_data={
                        "columns": ["name", "lng", "lat", "value"],
                        "rows": hotspot_rows,
                    },
                    updated_at=requested_at,
                )
            )

        if ResultKind.chart.value in requested_output_kinds:
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"chart-{uuid4().hex[:10]}",
                    result_kind=ResultKind.chart,
                    title=f"{snapshot.display_name} 时段趋势",
                    mime_type="application/json",
                    inline_data=self._build_chart_payload(layer_id),
                    updated_at=requested_at,
                )
            )

        if ResultKind.text.value in requested_output_kinds:
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"text-{uuid4().hex[:10]}",
                    result_kind=ResultKind.text,
                    title=f"{snapshot.display_name} 摘要",
                    mime_type="text/plain",
                    inline_data={
                        "text": (
                            f"{snapshot.display_name} 在 {snapshot.requested_hour:.2f} 时刻的"
                            f"{snapshot.metric_label}为 {metric_value}{snapshot.metric_unit}，"
                            f"当前状态为 {snapshot.status_label}，热点数量 {len(hotspot_rows)}。"
                        )
                    },
                    updated_at=requested_at,
                )
            )

        events = [
            event_factory(
                channel="log",
                message="兼容 Demo 工作流已完成快照提取与分析聚合。",
                progress=70,
                payload={
                    "service": "demo_workflow_service",
                    "compatibility_mode": "legacy-demo",
                    "layer_id": layer_id,
                    "requested_hour": snapshot.requested_hour,
                    "hotspot_count": len(hotspot_rows),
                },
            ),
            event_factory(
                channel="data",
                message="兼容 Demo 工作流结果已生成。",
                progress=92,
                payload={
                    "result_count": len(result_refs),
                    "availability_state": snapshot.availability_state.value,
                    "data_state_mode": snapshot.data_state_mode.value,
                },
            ),
        ]

        diagnostics = [
            "demo_workflow_service 属于 legacy/demo 兼容实现，不应视为 workflow-runs 主业务事实源。",
            "legacy_demo_service=true",
            f"resolved_layer_id={layer_id}",
            f"resolved_hour={snapshot.requested_hour}",
            f"result_count={len(result_refs)}",
        ]

        return WorkflowExecutionResult(
            message=f"兼容 Demo 工作流执行完成，已生成 {len(result_refs)} 个结果引用。",
            result_refs=result_refs,
            result_dto={
                "workflow_entry_name": "demo_workflow",
                "layer_id": layer_id,
                "requested_hour": snapshot.requested_hour,
                "compatibility_mode": "legacy-demo",
                "summary": snapshot.summary,
                "status_label": snapshot.status_label,
                "metric_label": snapshot.metric_label,
                "metric_value": metric_value,
                "metric_unit": snapshot.metric_unit,
                "availability_state": snapshot.availability_state.value,
                "data_state_mode": snapshot.data_state_mode.value,
                "hotspot_count": len(hotspot_rows),
                "result_category": "analysis",
                "results": {
                    "json_result_id": result_refs[0].result_id,
                    "table_result_id": next((item.result_id for item in result_refs if item.result_kind == ResultKind.table), None),
                    "chart_result_id": next((item.result_id for item in result_refs if item.result_kind == ResultKind.chart), None),
                    "text_result_id": next((item.result_id for item in result_refs if item.result_kind == ResultKind.text), None),
                },
            },
            diagnostics=diagnostics,
            events=events,
        )

    def _resolve_requested_hour(self, payload: WorkflowSubmitRequest) -> float:
        hour_override = payload.parameters.get("hour")
        if isinstance(hour_override, (int, float)):
            return float(hour_override)

        if payload.time_range is None:
            return 12.0

        start_at = payload.time_range.start_at
        return start_at.hour + start_at.minute / 60

    def _extract_metric_value(self, raw_payload: dict[str, Any], aliases: list[str]) -> float | int | str | None:
        for alias in aliases:
            if alias in raw_payload:
                return raw_payload[alias]
        return None

    def _build_hotspot_rows(self, snapshot) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        hotspot_aliases = snapshot.field_aliases.hotspot_value
        for hotspot in snapshot.raw_payload.get("hotspots", []):
            value = None
            for alias in hotspot_aliases:
                if alias in hotspot:
                    value = hotspot[alias]
                    break
            rows.append(
                {
                    "name": hotspot.get("name"),
                    "lng": hotspot.get("lng"),
                    "lat": hotspot.get("lat"),
                    "value": value,
                }
            )

        rows.sort(key=lambda item: item["value"] if item["value"] is not None else float("-inf"), reverse=True)
        return rows

    def _build_chart_payload(self, layer_id: str) -> dict[str, Any]:
        hours = [0, 6, 12, 18]
        labels: list[str] = []
        values: list[float | int | str | None] = []
        for hour in hours:
            snapshot = get_demo_layer_snapshot(layer_id, hour)
            if snapshot is None:
                continue
            labels.append(f"{hour:02d}:00")
            values.append(self._extract_metric_value(snapshot.raw_payload, snapshot.field_aliases.metric_value))

        return {
            "chart_type": "line",
            "x": labels,
            "y": values,
            "series_name": layer_id,
        }


demo_workflow_service = DemoWorkflowService()
