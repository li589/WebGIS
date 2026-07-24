"""Cloud cover / dewpoint layer output strategies."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from uuid import uuid4

from app.services.result_storage import result_storage_service
from app.weatherengine.layer_outputs.base import LayerOutputResult, LayerOutputStrategy
from app.weatherengine.layer_outputs.registry import register_strategy
from shared.contracts.api_contracts import ResultKind

logger = logging.getLogger(__name__)


def _build_scalar_layer(
    *,
    service: Any,
    run_id: str,
    payload: Any,
    requested_at: datetime,
    weather: Any,
    spec: Any,
    artifact_prefix: str,
) -> LayerOutputResult:
    metric_key = spec.primary_metric
    unit = spec.unit_label
    bbox = service._resolve_render_bbox(payload, weather.latitude, weather.longitude)
    try:
        grid_data, _, _ = service._fetch_layer_grid_data(bbox=bbox, spec=spec)
        feature_collection = service.build_scalar_geojson_from_grid(
            grid_data,
            metric_key=metric_key,
            unit=unit,
        )
    except (HTTPError, URLError, OSError, KeyError, ValueError):
        current = weather.current
        base = getattr(current, metric_key, None)
        if base is None and metric_key == "cloud_cover":
            base = getattr(current, "cloud_cover", None) or 0.0
        if base is None and metric_key == "dew_point_2m":
            base = getattr(current, "dew_point_2m", None) or 0.0
        feature_collection = service.build_scalar_geojson_from_point(
            weather,
            bbox,
            metric_key=metric_key,
            unit=unit,
            base_value=float(base or 0.0),
        )

    geojson_ref = result_storage_service.create_artifact_result_ref(
        run_id=run_id,
        result_id=f"{artifact_prefix}-geojson-{uuid4().hex[:10]}",
        result_kind=ResultKind.file,
        title=f"{spec.display_name} GeoJSON Layer",
        mime_type="application/geo+json",
        updated_at=requested_at,
        payload=feature_collection,
    )
    return LayerOutputResult(
        geojson_ref=geojson_ref,
        cog_ref=None,
        diagnostics=[
            f"{artifact_prefix}_geojson_cells={len(feature_collection['features'])}"
        ],
        bbox=bbox,
    )


@register_strategy("cloud-cover")
class CloudCoverLayerOutput(LayerOutputStrategy):
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
        return _build_scalar_layer(
            service=service,
            run_id=run_id,
            payload=payload,
            requested_at=requested_at,
            weather=weather,
            spec=spec,
            artifact_prefix="cloud-cover",
        )


@register_strategy("dewpoint")
class DewpointLayerOutput(LayerOutputStrategy):
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
        return _build_scalar_layer(
            service=service,
            run_id=run_id,
            payload=payload,
            requested_at=requested_at,
            weather=weather,
            spec=spec,
            artifact_prefix="dewpoint",
        )
