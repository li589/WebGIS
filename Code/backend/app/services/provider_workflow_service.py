from __future__ import annotations

from datetime import datetime
import logging
from uuid import uuid4

from algorithms.providers.base import ProviderExecutionPayload, ProviderExecutionResult
from algorithms.registry.provider_registry import get_provider_for_layer
from app.core.config import settings
from app.services.result_storage import result_storage_service
from app.services.workflow_execution import WorkflowExecutionResult
from shared.contracts.api_contracts import ResultKind, WorkflowResultReference, WorkflowSubmitRequest

logger = logging.getLogger(__name__)

# P0-5: Parameter whitelist — only these keys are permitted in workflow parameters.
_ALLOWED_PARAMETER_KEYS: frozenset[str] = frozenset({
    "hour",
    "hotspot_count",
    "series_step_hours",
    "cache_ttl_seconds",
    "max_attempts",
    "simulate_fail_attempts",
    "partial_failure_ref_ids",
})
_MAX_PARAMETER_KEYS = 64


class ProviderWorkflowService:
    def execute(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        event_factory,
    ) -> WorkflowExecutionResult:
        layer_id = payload.layer_id or payload.map_context.active_layer_id
        if layer_id is None:
            raise ValueError("Provider workflow requires layer_id.")

        provider = get_provider_for_layer(layer_id)
        if provider is None:
            raise ValueError(f"No provider registered for layer: {layer_id}")

        validated_params = self._validate_parameters(payload.parameters)

        provider_payload = ProviderExecutionPayload(
            layer_id=layer_id,
            requested_at=requested_at,
            requested_hour=self._resolve_requested_hour(payload),
            parameters=validated_params,
            requested_outputs=payload.requested_outputs,
            spatial_filter=payload.spatial_filter.model_dump(mode="json") if payload.spatial_filter else {},
            time_range=payload.time_range.model_dump(mode="json") if payload.time_range else {},
            client=payload.client.model_dump(mode="json"),
            map_context=payload.map_context.model_dump(mode="json"),
            config_overrides=payload.config_overrides,
            execution_limits={
                "max_hotspots": settings.provider_max_hotspots,
                "max_series_points": settings.provider_max_series_points,
                "max_inline_result_bytes": settings.result_inline_max_bytes,
            },
            correlation_id=payload.correlation_id,
        )
        provider_result = self._apply_result_limits(provider.execute(provider_payload))
        result_refs, chunk_diagnostics = self._build_result_refs(run_id, payload, requested_at, provider_result)

        events = [
            event_factory(
                channel="log",
                message="真实 provider 已完成执行。",
                progress=72,
                payload={
                    "provider_key": provider_result.provider_key,
                    "layer_id": layer_id,
                },
            ),
            event_factory(
                channel="data",
                message="provider 结果引用已完成组装。",
                progress=93,
                payload={
                    "result_count": len(result_refs),
                    "provider_key": provider_result.provider_key,
                    "priority": payload.priority.value,
                    "resource_profile": payload.resource_profile.value,
                },
            ),
        ]

        diagnostics = [
            f"provider_key={provider_result.provider_key}",
            f"resolved_layer_id={layer_id}",
            f"requested_hour={provider_payload.requested_hour}",
            f"priority={payload.priority.value}",
            f"resource_profile={payload.resource_profile.value}",
            f"realtime_preferred={payload.realtime_preferred}",
            *provider_result.diagnostics,
            *chunk_diagnostics,
        ]

        return WorkflowExecutionResult(
            message=f"{provider_result.title} 工作流执行完成，已生成 {len(result_refs)} 个结果引用。",
            result_refs=result_refs,
            result_dto={
                "workflow_entry_name": payload.workflow_name or payload.module_name or "provider_workflow",
                "layer_id": provider_result.layer_id,
                "provider_key": provider_result.provider_key,
                "summary": provider_result.summary,
                "metric_label": provider_result.metric_label,
                "metric_unit": provider_result.metric_unit,
                "metric_value": provider_result.metric_value,
                "status_label": provider_result.status_label,
                "confidence_label": provider_result.confidence_label,
                "hotspot_count": len(provider_result.hotspots),
                "series_point_count": len(provider_result.series),
                "result_category": "provider",
                "metadata": provider_result.metadata,
            },
            diagnostics=diagnostics,
            events=events,
        )

    def supports(self, payload: WorkflowSubmitRequest) -> bool:
        layer_id = payload.layer_id or payload.map_context.active_layer_id
        return bool(layer_id and get_provider_for_layer(layer_id) is not None)

    def _build_result_refs(
        self,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        provider_result: ProviderExecutionResult,
    ) -> tuple[list[WorkflowResultReference], list[str]]:
        result_refs = [
            WorkflowResultReference(
                result_id=f"result-{uuid4().hex[:10]}",
                result_kind=ResultKind.json,
                title=f"{provider_result.title} 工作流结果",
                mime_type="application/json",
                inline_data={
                    "workflow": {
                        "run_id": run_id,
                        "command_type": payload.command_type.value,
                        "layer_id": provider_result.layer_id,
                    },
                    "provider": {
                        "provider_key": provider_result.provider_key,
                        "summary": provider_result.summary,
                        "metric_label": provider_result.metric_label,
                        "metric_unit": provider_result.metric_unit,
                        "metric_value": provider_result.metric_value,
                        "status_label": provider_result.status_label,
                        "confidence_label": provider_result.confidence_label,
                        "metadata": provider_result.metadata,
                    },
                    "routing": {
                        "priority": payload.priority.value,
                        "resource_profile": payload.resource_profile.value,
                        "realtime_preferred": payload.realtime_preferred,
                        "queue_tag": payload.queue_tag,
                    },
                    "hotspots": provider_result.hotspots,
                    "series": provider_result.series,
                },
                updated_at=requested_at,
            )
        ]
        diagnostics: list[str] = []

        requested_output_kinds = {str(item) for item in payload.requested_outputs}
        requested_output_kinds.update(
            item.value for item in payload.requested_outputs if isinstance(item, ResultKind)
        )

        if ResultKind.table.value in requested_output_kinds:
            if len(provider_result.hotspots) > settings.provider_table_chunk_size:
                chunked_ref, chunked_diagnostics = result_storage_service.build_chunked_reference(
                    run_id=run_id,
                    result_kind=ResultKind.table,
                    title=f"{provider_result.title} 热点表",
                    mime_type="application/json",
                    updated_at=requested_at,
                    items=provider_result.hotspots,
                    chunk_size=settings.provider_table_chunk_size,
                    manifest_payload={
                        "columns": ["name", "lng", "lat", "risk_score"],
                        "row_count": len(provider_result.hotspots),
                        "provider_key": provider_result.provider_key,
                    },
                )
                result_refs.append(chunked_ref)
                diagnostics.extend(chunked_diagnostics)
            else:
                result_refs.append(
                    WorkflowResultReference(
                        result_id=f"table-{uuid4().hex[:10]}",
                        result_kind=ResultKind.table,
                        title=f"{provider_result.title} 热点表",
                        mime_type="application/json",
                        inline_data={
                            "columns": ["name", "lng", "lat", "risk_score"],
                            "rows": provider_result.hotspots,
                        },
                        updated_at=requested_at,
                    )
                )

        if ResultKind.chart.value in requested_output_kinds:
            if len(provider_result.series) > settings.provider_series_chunk_size:
                chunked_ref, chunked_diagnostics = result_storage_service.build_chunked_reference(
                    run_id=run_id,
                    result_kind=ResultKind.chart,
                    title=f"{provider_result.title} 时段趋势",
                    mime_type="application/json",
                    updated_at=requested_at,
                    items=provider_result.series,
                    chunk_size=settings.provider_series_chunk_size,
                    manifest_payload={
                        "chart_type": "line",
                        "series_name": provider_result.layer_id,
                        "point_count": len(provider_result.series),
                    },
                )
                result_refs.append(chunked_ref)
                diagnostics.extend(chunked_diagnostics)
            else:
                result_refs.append(
                    WorkflowResultReference(
                        result_id=f"chart-{uuid4().hex[:10]}",
                        result_kind=ResultKind.chart,
                        title=f"{provider_result.title} 时段趋势",
                        mime_type="application/json",
                        inline_data={
                            "chart_type": "line",
                            "x": [item["label"] for item in provider_result.series],
                            "y": [item["value"] for item in provider_result.series],
                            "series_name": provider_result.layer_id,
                        },
                        updated_at=requested_at,
                    )
                )

        if ResultKind.text.value in requested_output_kinds:
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"text-{uuid4().hex[:10]}",
                    result_kind=ResultKind.text,
                    title=f"{provider_result.title} 摘要",
                    mime_type="text/plain",
                    inline_data={
                        "text": (
                            f"{provider_result.title} 当前{provider_result.metric_label}为 "
                            f"{provider_result.metric_value}{provider_result.metric_unit}，"
                            f"状态 {provider_result.status_label}。"
                        )
                    },
                    updated_at=requested_at,
                )
            )

        return result_refs, diagnostics

    def _resolve_requested_hour(self, payload: WorkflowSubmitRequest) -> float:
        hour_override = payload.parameters.get("hour")
        if isinstance(hour_override, (int, float)):
            return float(hour_override)
        if payload.time_range is None:
            return 12.0
        return payload.time_range.start_at.hour + payload.time_range.start_at.minute / 60

    def _apply_result_limits(self, provider_result: ProviderExecutionResult) -> ProviderExecutionResult:
        diagnostics = list(provider_result.diagnostics)
        hotspots = provider_result.hotspots[: settings.provider_max_hotspots]
        series = provider_result.series[: settings.provider_max_series_points]

        if len(provider_result.hotspots) > len(hotspots):
            diagnostics.append(
                f"hotspots_truncated={len(provider_result.hotspots)}->{len(hotspots)}"
            )
        if len(provider_result.series) > len(series):
            diagnostics.append(
                f"series_truncated={len(provider_result.series)}->{len(series)}"
            )
        if diagnostics != provider_result.diagnostics:
            logger.warning("Provider result exceeded configured payload limits")

        provider_result.hotspots = hotspots
        provider_result.series = series
        provider_result.diagnostics = diagnostics
        return provider_result

    def _validate_parameters(self, parameters: dict[str, object]) -> dict[str, object]:
        """P0-5: Reject parameters with illegal keys or oversized dicts."""
        if len(parameters) > _MAX_PARAMETER_KEYS:
            raise ValueError(
                f"Too many parameter keys: {len(parameters)} > {_MAX_PARAMETER_KEYS}. "
                "Rejecting to prevent parameter DoS."
            )
        illegal_keys = set(parameters.keys()) - _ALLOWED_PARAMETER_KEYS
        if illegal_keys:
            raise ValueError(
                f"Illegal parameter keys: {sorted(illegal_keys)}. "
                f"Allowed keys: {sorted(_ALLOWED_PARAMETER_KEYS)}."
            )
        # Sanitise values — drop any non-JSON-serialisable objects that could cause
        # downstream crashes when the dict is json.dumps'd.
        sanitised: dict[str, object] = {}
        for k, v in parameters.items():
            if isinstance(v, (str, int, float, bool, type(None), list, dict)):
                sanitised[k] = v
            else:
                sanitised[k] = str(v)
        return sanitised


provider_workflow_service = ProviderWorkflowService()
