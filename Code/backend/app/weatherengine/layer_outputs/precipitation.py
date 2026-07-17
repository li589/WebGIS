"""Precipitation layer output strategy.

处理 layer_id == "precipitation" 的图层输出。
从 service.py _build_map_layer_outputs L635-663 分支迁移而来，无行为变更。
"""
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


@register_strategy("precipitation")
class PrecipitationLayerOutput(LayerOutputStrategy):
    """降水图层输出策略：构建降水 GeoJSON + COG 栅格。

    量纲: metric_value 无量纲（降水量由 spec.unit_label 决定单位），bbox 为 RenderBBox。
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
        bbox = service._resolve_render_bbox(payload, weather.latitude, weather.longitude)
        try:
            grid_data, _, _ = service._fetch_layer_grid_data(bbox=bbox, spec=spec)
            feature_collection = service.build_precipitation_geojson_from_grid(grid_data, spec.layer_id)
        except (HTTPError, URLError, OSError, KeyError, ValueError):
            feature_collection = service.build_precipitation_geojson(weather, bbox)

        geojson_ref = result_storage_service.create_artifact_result_ref(
            run_id=run_id,
            result_id=f"precipitation-geojson-{uuid4().hex[:10]}",
            result_kind=ResultKind.file,
            title=f"{spec.display_name} GeoJSON Layer",
            mime_type="application/geo+json",
            updated_at=requested_at,
            payload=feature_collection,
        )
        diagnostics: list[str] = [
            f"precipitation_geojson_cells={len(feature_collection['features'])}",
        ]

        cog_ref, cog_diagnostics = service._build_precipitation_cog_artifact(
            run_id=run_id,
            requested_at=requested_at,
            weather=weather,
            bbox=bbox,
            spec=spec,
        )
        diagnostics.extend(cog_diagnostics)

        return LayerOutputResult(
            geojson_ref=geojson_ref,
            cog_ref=cog_ref,
            diagnostics=diagnostics,
            bbox=bbox,
        )
