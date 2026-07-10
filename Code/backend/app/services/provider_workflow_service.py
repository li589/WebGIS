from __future__ import annotations

from datetime import datetime
import logging
from uuid import uuid4

from algorithms.providers.base import ProviderExecutionPayload, ProviderExecutionResult
from algorithms.registry.provider_registry import get_provider_for_layer
from app.core.config import settings
from app.services.layer_catalog import get_layer_descriptor
from app.services.result_storage import result_storage_service
from app.services.workflow_execution import WorkflowExecutionResult
from shared.contracts.api_contracts import (
    LayerRenderType,
    ResultKind,
    WeatherLayerRenderHint,
    WorkflowResultReference,
    WorkflowSubmitRequest,
)

logger = logging.getLogger(__name__)

# P0-5: Parameter whitelist — only these keys are permitted in workflow parameters.
_ALLOWED_PARAMETER_KEYS: frozenset[str] = frozenset({
    "hour",
    "latitude",
    "longitude",
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
        # 修复：移除 try/except 包裹，让异常向上抛出至 interaction_hub.process_workflow_run
        # 的 except 块，由 _handle_workflow_failure 正确分类并标记 failed/retry_pending。
        # 此前捕获异常返回带 error 的 WorkflowExecutionResult 会被 hub 当作成功结果
        # 调用 _finalize_workflow_success，导致 provider 失败被隐藏在 succeeded 状态下。
        # 与 WeatherBridgeService 的失败传播行为保持一致（违反 BridgeProtocol）。
        return self._do_execute(
            run_id=run_id,
            payload=payload,
            requested_at=requested_at,
            event_factory=event_factory,
        )

    def _do_execute(
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
        # C5 修复：使用内部方法获取 refs + diagnostics，公开方法仅返回 refs
        result_refs, chunk_diagnostics = self._build_result_refs_with_diagnostics(
            run_id, payload, requested_at, provider_result,
        )

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

        algorithm_request = payload.algorithm_request if isinstance(payload.algorithm_request, dict) else payload.algorithm_request.model_dump(mode="json")
        workflow_entry_name = (
            str(algorithm_request.get("workflow_name") or algorithm_request.get("module_name") or "provider_workflow")
        )
        engine_run_id = (
            provider_result.metadata.get("engine_run_id")
            if isinstance(provider_result.metadata, dict)
            else None
        )

        return WorkflowExecutionResult(
            message=f"{provider_result.title} 工作流执行完成，已生成 {len(result_refs)} 个结果引用。",
            result_refs=result_refs,
            result_dto={
                "workflow_entry_name": workflow_entry_name,
                "run_id": run_id,
                "engine_run_id": engine_run_id,
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
        # C5 修复：与其他 bridge 对齐 enabled flag 检查
        if not settings.provider_workflow_enabled:
            return False
        layer_id = payload.layer_id or payload.map_context.active_layer_id
        return bool(layer_id and get_provider_for_layer(layer_id) is not None)

    # ------------------------------------------------------------------ 元数据接口（M6 修复：补齐 Bridge Protocol）

    def list_workflows_response(self) -> dict[str, Any]:
        """返回 provider 支持的 workflow 列表。

        Provider 无静态 workflow 注册表，通过 layer_id 反查 provider 元数据。
        """
        from algorithms.registry.provider_registry import list_registered_layers

        try:
            layer_ids = list(list_registered_layers())
        except Exception as exc:
            logger.exception("ProviderWorkflowService.list_workflows_response failed")
            return {
                "status_code": 500,
                "body": {
                    "error_type": "internal_error",
                    "error_code": "provider_list_failed",
                    "user_message": "无法获取 provider workflow 列表。",
                    "developer_message": str(exc),
                },
            }
        workflows = [
            {
                "name": layer_id,
                "node_type": layer_id,
                "category": "provider",
            }
            for layer_id in layer_ids
        ]
        return {
            "status_code": 200,
            "body": {
                "workflows": workflows,
                "workflow_count": len(workflows),
                "source": "provider",
            },
        }

    def describe_workflow_response(self, workflow_name: str) -> dict[str, Any]:
        """返回单个 provider workflow 详情。"""
        provider = get_provider_for_layer(workflow_name)
        if provider is None:
            return {
                "status_code": 404,
                "body": {
                    "error_type": "not_found",
                    "error_code": "provider_workflow_not_found",
                    "user_message": f"Provider 节点类型不存在: {workflow_name}",
                    "developer_message": f"workflow_name not in registered provider layers: {workflow_name}",
                },
            }
        return {
            "status_code": 200,
            "body": {
                "name": workflow_name,
                "node_type": workflow_name,
                "category": "provider",
                "source": "provider",
            },
        }

    def get_diagnostics_response(self) -> dict[str, Any]:
        """返回 provider 诊断信息。"""
        from algorithms.registry.provider_registry import list_registered_layers

        try:
            layer_ids = list(list_registered_layers())
        except Exception as exc:
            logger.exception("ProviderWorkflowService.get_diagnostics_response failed")
            return {
                "status_code": 500,
                "body": {
                    "error_type": "internal_error",
                    "error_code": "provider_diagnostics_failed",
                    "user_message": "无法获取 provider 诊断信息。",
                    "developer_message": str(exc),
                },
            }
        return {
            "status_code": 200,
            "body": {
                "source": "provider",
                "provider_workflow_enabled": settings.provider_workflow_enabled,
                "registered_layer_count": len(layer_ids),
                "registered_layers": layer_ids,
                "max_hotspots": settings.provider_max_hotspots,
                "max_series_points": settings.provider_max_series_points,
            },
        }

    def _build_result_refs(
        self,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        provider_result: ProviderExecutionResult,
    ) -> list[WorkflowResultReference]:
        """Bridge 协议：仅返回 result_refs 列表，与其他 bridge 一致。"""
        refs, _ = self._build_result_refs_with_diagnostics(run_id, payload, requested_at, provider_result)
        return refs

    def _build_result_refs_with_diagnostics(
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

        requested_output_kinds = {
            item.value if isinstance(item, ResultKind) else str(item)
            for item in payload.requested_outputs
        }

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

        if ResultKind.map_layer.value in requested_output_kinds:
            map_layer_ref, map_layer_diagnostics = self._build_map_layer_ref(
                run_id=run_id,
                requested_at=requested_at,
                provider_result=provider_result,
            )
            if map_layer_ref is not None:
                result_refs.append(map_layer_ref)
            diagnostics.extend(map_layer_diagnostics)

        return result_refs, diagnostics

    def _build_map_layer_ref(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        provider_result: ProviderExecutionResult,
    ) -> tuple[WorkflowResultReference | None, list[str]]:
        descriptor = get_layer_descriptor(provider_result.layer_id)
        if descriptor is None:
            return None, [f"map_layer_skipped=descriptor_missing:{provider_result.layer_id}"]

        if descriptor.render_type != LayerRenderType.heatmap:
            return None, [f"map_layer_skipped=unsupported_render_type:{descriptor.render_type.value}"]

        features: list[dict[str, object]] = []
        for index, hotspot in enumerate(provider_result.hotspots):
            if not isinstance(hotspot, dict):
                continue
            lng = hotspot.get("lng")
            lat = hotspot.get("lat")
            risk_score = hotspot.get("risk_score")
            if not isinstance(lng, (int, float)) or not isinstance(lat, (int, float)):
                continue
            if not isinstance(risk_score, (int, float)):
                risk_score = provider_result.metric_value if isinstance(provider_result.metric_value, (int, float)) else 0
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(lng), float(lat)],
                    },
                    "properties": {
                        "id": f"{provider_result.layer_id}-{index + 1}",
                        "name": str(hotspot.get("name", f"hotspot-{index + 1}")),
                        "risk_score": float(risk_score),
                        "metric": "risk_score",
                        "value": float(risk_score),
                        "unit": descriptor.style.unit_label or provider_result.metric_unit,
                        "provider_key": provider_result.provider_key,
                    },
                }
            )

        if not features:
            return None, [f"map_layer_skipped=no_heatmap_features:{provider_result.layer_id}"]

        feature_collection = {
            "type": "FeatureCollection",
            "features": features,
        }
        geojson_ref = result_storage_service.create_artifact_result_ref(
            run_id=run_id,
            result_id=f"heatmap-geojson-{uuid4().hex[:10]}",
            result_kind=ResultKind.file,
            title=f"{provider_result.layer_id} heatmap geojson",
            mime_type="application/geo+json",
            updated_at=requested_at,
            payload=feature_collection,
        )
        top_feature = features[0]
        render_hint = WeatherLayerRenderHint(
            layer_id=provider_result.layer_id,
            paint_mode="heatmap",
            palette=descriptor.style.palette or "magenta-yellow",
            primary_metric="risk_score",
            unit_label=descriptor.style.unit_label or provider_result.metric_unit,
            opacity=descriptor.style.opacity,
            legend_ticks=[0, 20, 40, 60, 80, 100],
            notes=[
                "provider_heatmap=true",
                f"provider_key={provider_result.provider_key}",
                "热力图由 provider hotspot 点集真实聚合生成。",
            ],
        )
        map_layer_ref = WorkflowResultReference(
            result_id=f"map-layer-{uuid4().hex[:10]}",
            result_kind=ResultKind.map_layer,
            title=f"{provider_result.title} 热力图图层",
            mime_type="application/json",
            inline_data={
                "render_hint": render_hint.model_dump(mode="json"),
                "point_feature": top_feature,
                "layer_assets": {
                    "geojson_url": geojson_ref.resource_url,
                    "cog_url": None,
                    "cog_preview_url": None,
                    "cog_bbox": None,
                },
            },
            updated_at=requested_at,
        )
        return map_layer_ref, [
            f"heatmap_geojson_points={len(features)}",
            f"heatmap_geojson_result_id={geojson_ref.result_id}",
        ]

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
