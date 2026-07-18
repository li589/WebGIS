"""Wind field layer output strategy.

处理 layer_id == "wind-field" 或 layer_id.startswith("wind-field-") 的图层输出。
从 service.py _build_map_layer_outputs L577-604 分支迁移而来，无行为变更。
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


@register_strategy("wind-field", prefix=True)
class WindFieldLayerOutput(LayerOutputStrategy):
    """风场图层输出策略：构建风场 GeoJSON（含粒子流场特征）。

    量纲: metric_value 无量纲，bbox 为 RenderBBox（度为单位经纬度）。
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
            grid_data, cache_status, resolution = service._fetch_layer_grid_data(bbox=bbox, spec=spec)
            feature_collection = service.build_wind_geojson_from_grid(grid_data, spec.layer_id)
            logger.info(
                "[WindDebug] build_wind_geojson_from_grid: layer=%s bbox=%s features=%d cache=%s resolution=%s",
                spec.layer_id, bbox, len(feature_collection['features']), cache_status, resolution,
            )
        except (HTTPError, URLError, OSError, KeyError, ValueError) as exc:
            logger.warning("[WindDebug] Grid fetch failed, falling back to simulated data: %s", exc)
            feature_collection = service.build_wind_geojson(weather, bbox)

        geojson_ref = result_storage_service.create_artifact_result_ref(
            run_id=run_id,
            result_id=f"wind-geojson-{uuid4().hex[:10]}",
            result_kind=ResultKind.file,
            title=f"{spec.display_name} GeoJSON Layer",
            mime_type="application/geo+json",
            updated_at=requested_at,
            payload=feature_collection,
        )
        logger.info(
            "[WindDebug] artifact created: result_id=%s resource_url=%s resource_key=%s",
            geojson_ref.result_id, geojson_ref.resource_url, geojson_ref.resource_key,
        )
        features = feature_collection['features']
        diagnostics: list[str] = [
            f"wind_geojson_points={len(features)}",
            f"wind_height={features[0]['properties']['height'] if features else '10m'}",
        ]
        return LayerOutputResult(
            geojson_ref=geojson_ref,
            cog_ref=None,
            diagnostics=diagnostics,
            bbox=bbox,
        )
