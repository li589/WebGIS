"""Provider result builder: post-execution result shaping.

Extracted from the original ``provider_workflow_service.py`` god class.
Owns all "after provider.execute() returns" concerns:

- :meth:`apply_result_limits` truncates hotspots / series to configured
  limits and augments diagnostics with truncation notices.
- :meth:`build_result_refs_with_diagnostics` assembles the json / table /
  chart / text / map_layer result refs, delegating chunked spills to
  ``result_storage_service`` and heatmap geojson construction to
  :meth:`_build_map_layer_ref`.

The orchestration layer (:class:`ProviderWorkflowService`) calls these
helpers in order: ``apply_result_limits(provider.execute(...))`` then
``build_result_refs_with_diagnostics(...)``. Splitting them out keeps
``provider_workflow_service.py`` focused on bridge protocol plumbing
(payload validation, provider lookup, event/diagnostics assembly) while
this module owns the result-shaping state machine.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from algorithms.providers.base import ProviderExecutionResult
from app.core.config import settings
from app.services.layer_catalog import get_layer_descriptor
from app.services.result_storage import result_storage_service
from shared.contracts.api_contracts import (
    LayerRenderType,
    ResultKind,
    WeatherLayerRenderHint,
    WorkflowResultReference,
    WorkflowSubmitRequest,
)

logger = logging.getLogger(__name__)


class ProviderResultBuilder:
    """Shapes provider execution results into workflow result references."""

    # ------------------------------------------------------------------
    # Result limits
    # ------------------------------------------------------------------

    def apply_result_limits(
        self, provider_result: ProviderExecutionResult
    ) -> ProviderExecutionResult:
        """Truncate hotspots / series to configured limits in-place.

        Mutates ``provider_result`` (hotspots, series, diagnostics) and
        returns the same instance for fluent chaining. Logs a warning when
        any truncation occurred so operators can spot oversized providers.
        """
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

    # ------------------------------------------------------------------
    # Result ref assembly
    # ------------------------------------------------------------------

    def build_result_refs(
        self,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        provider_result: ProviderExecutionResult,
    ) -> list[WorkflowResultReference]:
        """Bridge protocol helper: return only result_refs (no diagnostics).

        Thin wrapper around :meth:`build_result_refs_with_diagnostics`
        for callers that don't need the diagnostics list.
        """
        refs, _ = self.build_result_refs_with_diagnostics(
            run_id, payload, requested_at, provider_result
        )
        return refs

    def build_result_refs_with_diagnostics(
        self,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        provider_result: ProviderExecutionResult,
    ) -> tuple[list[WorkflowResultReference], list[str]]:
        """Assemble result_refs for json / table / chart / text / map_layer kinds.

        Always emits a json result_ref (the canonical provider summary);
        table / chart / text / map_layer are emitted only when the
        corresponding :class:`ResultKind` is in ``payload.requested_outputs``.

        For oversized hotspots / series, delegates to
        ``result_storage_service.build_chunked_reference`` to spill the
        data to object storage and return a manifest-style ref.
        """
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
            self._maybe_append_table_ref(
                result_refs=result_refs,
                diagnostics=diagnostics,
                run_id=run_id,
                requested_at=requested_at,
                provider_result=provider_result,
            )

        if ResultKind.chart.value in requested_output_kinds:
            self._maybe_append_chart_ref(
                result_refs=result_refs,
                diagnostics=diagnostics,
                run_id=run_id,
                requested_at=requested_at,
                provider_result=provider_result,
            )

        if ResultKind.text.value in requested_output_kinds:
            result_refs.append(
                self._build_text_ref(
                    requested_at=requested_at,
                    provider_result=provider_result,
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

    # ------------------------------------------------------------------
    # Per-kind ref builders
    # ------------------------------------------------------------------

    def _maybe_append_table_ref(
        self,
        *,
        result_refs: list[WorkflowResultReference],
        diagnostics: list[str],
        run_id: str,
        requested_at: datetime,
        provider_result: ProviderExecutionResult,
    ) -> None:
        """Append a table result_ref, spilling to chunks if oversized.

        Chunk threshold is ``settings.provider_table_chunk_size``. When
        spilt, ``result_storage_service.build_chunked_reference`` returns
        a manifest-style ref + per-chunk diagnostics.
        """
        if len(provider_result.hotspots) > settings.provider_table_chunk_size:
            chunked_ref, chunked_diagnostics = (
                result_storage_service.build_chunked_reference(
                    run_id=run_id,
                    result_kind=ResultKind.table,
                    title=f"{provider_result.title} Hotspot Table",
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

    def _maybe_append_chart_ref(
        self,
        *,
        result_refs: list[WorkflowResultReference],
        diagnostics: list[str],
        run_id: str,
        requested_at: datetime,
        provider_result: ProviderExecutionResult,
    ) -> None:
        """Append a chart result_ref, spilling to chunks if oversized.

        Chart x-axis = series labels, y-axis = series values. Chunk
        threshold is ``settings.provider_series_chunk_size``.
        """
        if len(provider_result.series) > settings.provider_series_chunk_size:
            chunked_ref, chunked_diagnostics = (
                result_storage_service.build_chunked_reference(
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

    def _build_text_ref(
        self,
        *,
        requested_at: datetime,
        provider_result: ProviderExecutionResult,
    ) -> WorkflowResultReference:
        """Build the text summary result_ref (always inline, never chunked)."""
        return WorkflowResultReference(
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

    # ------------------------------------------------------------------
    # Map layer (heatmap GeoJSON) construction
    # ------------------------------------------------------------------

    def _build_map_layer_ref(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        provider_result: ProviderExecutionResult,
    ) -> tuple[WorkflowResultReference | None, list[str]]:
        """Build a heatmap map_layer result_ref from provider hotspots.

        Returns ``(None, [diagnostic])`` when:
        - The layer descriptor is missing (layer not in catalog).
        - The descriptor's ``render_type`` is not ``heatmap``.
        - No valid heatmap features could be derived (all hotspots
          missing lng/lat/risk_score).

        On success, spills the FeatureCollection to object storage via
        ``result_storage_service.create_artifact_result_ref`` and returns
        a map_layer ref whose ``inline_data`` carries the
        :class:`WeatherLayerRenderHint` + top feature + asset URLs.
        """
        descriptor = get_layer_descriptor(provider_result.layer_id)
        if descriptor is None:
            return None, [
                f"map_layer_skipped=descriptor_missing:{provider_result.layer_id}"
            ]

        if descriptor.render_type != LayerRenderType.heatmap:
            return None, [
                f"map_layer_skipped=unsupported_render_type:{descriptor.render_type.value}"
            ]

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
                risk_score = (
                    provider_result.metric_value
                    if isinstance(provider_result.metric_value, (int, float))
                    else 0
                )
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
                        "unit": descriptor.style.unit_label
                        or provider_result.metric_unit,
                        "provider_key": provider_result.provider_key,
                    },
                }
            )

        if not features:
            return None, [
                f"map_layer_skipped=no_heatmap_features:{provider_result.layer_id}"
            ]

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
            title=f"{provider_result.title} Heatmap Layer",
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


# Module-level singleton: result builder is stateless, so a single shared
# instance mirrors the original provider_workflow_service behaviour.
provider_result_builder = ProviderResultBuilder()
