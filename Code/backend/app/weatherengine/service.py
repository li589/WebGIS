from __future__ import annotations

from datetime import datetime, timezone
import importlib
import math
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.services.result_storage import result_storage_service
from app.services.workflow_execution import WorkflowExecutionResult
from app.weatherengine.client import OpenMeteoClient
from app.weatherengine.constants import DEFAULT_LAYER_ID, DEFAULT_POINT, WEATHER_LAYER_SPECS
from shared.contracts.api_contracts import (
    BoundingBox,
    ResultKind,
    WeatherLayerRenderHint,
    WeatherPointCurrent,
    WeatherPointHourlyEntry,
    WeatherPointResponse,
    WorkflowResultReference,
    WorkflowSubmitRequest,
)


class WeatherEngineService:
    """天气引擎服务 — 提供"渲染原语"与 REST 端点直查。

    M12 修复：明确与 WeatherWorkflowService 的职责边界。
    - 本类负责：API 调用（Open-Meteo）、forecast 解析、GeoJSON/COG 渲染原语。
    - 节点依赖：仅依赖本类的渲染原语方法（build_wind_geojson 等）与解析方法
      （parse_forecast_to_point），不依赖 workflow 编排逻辑。
    - workflow 编排由 WeatherWorkflowService 负责，节点之间通过 ExecutionContext 传递数据。
    - REST 端点 /weather/point 直接调用本类 get_point_weather。
    - workflow-runs 调度链中，本类仅作为 layer-based fallback（无 weather_request 字段时）。
    """

    def __init__(self, client: OpenMeteoClient | None = None) -> None:
        self._client = client or OpenMeteoClient()

    def supports(self, payload: WorkflowSubmitRequest) -> bool:
        layer_id = payload.layer_id or payload.map_context.active_layer_id
        return bool(layer_id and layer_id in WEATHER_LAYER_SPECS)

    def get_point_weather(
        self,
        *,
        layer_id: str,
        latitude: float,
        longitude: float,
        model: str | None = None,
        forecast_hours: int = 6,
        place_name: str | None = None,
        cache_ttl_seconds: int | None = None,
    ) -> WeatherPointResponse:
        spec = WEATHER_LAYER_SPECS.get(layer_id)
        if spec is None:
            raise ValueError(f"Unsupported weather layer: {layer_id}")

        resolved_model = model or settings.weather_default_model
        ttl_seconds = cache_ttl_seconds or settings.weather_cache_ttl_seconds
        payload, cache_status = self._client.fetch_point_forecast(
            latitude=latitude,
            longitude=longitude,
            layer_spec=spec,
            model=resolved_model,
            forecast_hours=forecast_hours,
            ttl_seconds=ttl_seconds,
        )

        return self.parse_forecast_to_point(
            payload=payload,
            cache_status=cache_status,
            layer_id=layer_id,
            latitude=latitude,
            longitude=longitude,
            resolved_model=resolved_model,
            forecast_hours=forecast_hours,
            place_name=place_name,
        )

    def parse_forecast_to_point(
        self,
        *,
        payload: dict[str, Any],
        cache_status: str,
        layer_id: str,
        latitude: float,
        longitude: float,
        resolved_model: str,
        forecast_hours: int = 6,
        place_name: str | None = None,
    ) -> WeatherPointResponse:
        """M11 修复：将 forecast payload 解析为 WeatherPointResponse，无需再次调用 API。

        从 get_point_weather 提取，供 PointParseNode 消费上游 ForecastFetchNode 输出时复用。
        """
        spec = WEATHER_LAYER_SPECS.get(layer_id)
        if spec is None:
            raise ValueError(f"Unsupported weather layer: {layer_id}")

        current = payload.get("current") or {}
        hourly = payload.get("hourly") or {}
        hourly_times = hourly.get("time") or []
        hourly_rows: list[WeatherPointHourlyEntry] = []
        for index, time_value in enumerate(hourly_times[: max(1, forecast_hours)]):
            hourly_rows.append(
                WeatherPointHourlyEntry(
                    time=self._coerce_datetime(time_value),
                    temperature_2m=self._pick_series_value(hourly, "temperature_2m", index),
                    precipitation=self._pick_series_value(hourly, "precipitation", index),
                    wind_speed_10m=self._pick_series_value(hourly, "wind_speed_10m", index),
                )
            )

        metric_value = current.get(spec.primary_metric)
        summary = spec.summary_template.format(value=metric_value if metric_value is not None else "--", unit=spec.unit_label)
        observation_time = self._coerce_datetime(current.get("time"))
        return WeatherPointResponse(
            provider="open-meteo",
            model=resolved_model,
            resolved_model=str(payload.get("model")) if payload.get("model") is not None else None,
            layer_id=layer_id,
            latitude=latitude,
            longitude=longitude,
            place_name=place_name,
            timezone=payload.get("timezone"),
            fetched_at=datetime.now(timezone.utc),
            observation_time=observation_time,
            cache_status=cache_status,
            summary=summary,
            current=WeatherPointCurrent(
                temperature_2m=current.get("temperature_2m"),
                apparent_temperature=current.get("apparent_temperature"),
                precipitation=current.get("precipitation"),
                rain=current.get("rain"),
                weather_code=current.get("weather_code"),
                cloud_cover=current.get("cloud_cover"),
                pressure_msl=current.get("pressure_msl"),
                wind_speed_10m=current.get("wind_speed_10m"),
                wind_direction_10m=current.get("wind_direction_10m"),
                wind_gusts_10m=current.get("wind_gusts_10m"),
            ),
            hourly=hourly_rows,
            render_hint=WeatherLayerRenderHint(
                layer_id=layer_id,
                paint_mode=spec.paint_mode,
                palette=spec.palette,
                primary_metric=spec.primary_metric,
                unit_label=spec.unit_label,
                opacity=spec.default_opacity,
                legend_ticks=list(spec.legend_ticks),
                notes=list(spec.notes),
            ),
            diagnostics=[
                f"provider=open-meteo",
                f"layer_id={layer_id}",
                f"model={resolved_model}",
                f"cache_status={cache_status}",
                f"render_mode={spec.paint_mode}",
            ],
        )

    def execute(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        event_factory,
    ) -> WorkflowExecutionResult:
        layer_id = payload.layer_id or payload.map_context.active_layer_id or DEFAULT_LAYER_ID
        latitude, longitude, place_name = self._resolve_point(payload)
        forecast_hours = self._resolve_forecast_hours(payload)
        weather = self.get_point_weather(
            layer_id=layer_id,
            latitude=latitude,
            longitude=longitude,
            model=self._as_string(payload.parameters.get("weather_model")),
            forecast_hours=forecast_hours,
            place_name=place_name,
            cache_ttl_seconds=self._as_int(payload.parameters.get("cache_ttl_seconds")),
        )
        spec = WEATHER_LAYER_SPECS[layer_id]
        metric_value = getattr(weather.current, spec.primary_metric, None)

        result_refs = [
            WorkflowResultReference(
                result_id=f"weather-json-{uuid4().hex[:10]}",
                result_kind=ResultKind.json,
                title=f"{spec.display_name} Point Weather",
                mime_type="application/json",
                inline_data=weather.model_dump(mode="json"),
                updated_at=requested_at,
            )
        ]

        requested_output_kinds = {
            item.value if isinstance(item, ResultKind) else str(item)
            for item in payload.requested_outputs
        }
        diagnostics = list(weather.diagnostics)

        if ResultKind.table.value in requested_output_kinds:
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"weather-table-{uuid4().hex[:10]}",
                    result_kind=ResultKind.table,
                    title=f"{spec.display_name} Hourly Series",
                    mime_type="application/json",
                    inline_data={
                        "columns": ["time", "temperature_2m", "precipitation", "wind_speed_10m"],
                        "rows": [row.model_dump(mode="json") for row in weather.hourly],
                    },
                    updated_at=requested_at,
                )
            )
        if ResultKind.text.value in requested_output_kinds:
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"weather-text-{uuid4().hex[:10]}",
                    result_kind=ResultKind.text,
                    title=f"{spec.display_name} Summary",
                    mime_type="text/plain",
                    inline_data={"text": weather.summary},
                    updated_at=requested_at,
                )
            )
        if ResultKind.map_layer.value in requested_output_kinds:
            layer_refs, layer_diagnostics = self._build_map_layer_outputs(
                run_id=run_id,
                payload=payload,
                requested_at=requested_at,
                weather=weather,
                spec=spec,
                metric_value=metric_value,
            )
            result_refs.extend(layer_refs)
            diagnostics.extend(layer_diagnostics)

        return WorkflowExecutionResult(
            message=f"{spec.display_name} point weather fetched from Open-Meteo.",
            result_refs=result_refs,
            result_dto={
                "workflow_entry_name": "weatherengine.open_meteo_point",
                "layer_id": layer_id,
                "summary": weather.summary,
                "metric_label": spec.primary_label,
                "metric_unit": spec.unit_label,
                "metric_value": metric_value,
                "status_label": f"Open-Meteo {weather.cache_status}",
                "confidence_label": weather.model,
                "series_point_count": len(weather.hourly),
                "result_category": "provider",
                "metadata": {
                    "provider": weather.provider,
                    "model": weather.model,
                    "resolved_model": weather.resolved_model,
                    "place_name": weather.place_name,
                    "latitude": weather.latitude,
                    "longitude": weather.longitude,
                    "render_hint": weather.render_hint.model_dump(mode="json"),
                },
            },
            diagnostics=diagnostics,
            events=[
                event_factory(
                    channel="log",
                    message="WeatherEngine fetched point weather from Open-Meteo.",
                    progress=70,
                    payload={
                        "layer_id": layer_id,
                        "latitude": latitude,
                        "longitude": longitude,
                        "model": weather.model,
                    },
                ),
                event_factory(
                    channel="data",
                    message="WeatherEngine prepared workflow outputs.",
                    progress=92,
                    payload={
                        "result_count": len(result_refs),
                        "cache_status": weather.cache_status,
                    },
                ),
            ],
        )

    def refresh_default_layers(self) -> list[dict[str, object]]:
        refreshed: list[dict[str, object]] = []
        for layer_id in WEATHER_LAYER_SPECS:
            weather = self.get_point_weather(
                layer_id=layer_id,
                latitude=settings.weather_default_latitude,
                longitude=settings.weather_default_longitude,
                place_name=settings.weather_default_place_name,
                model=settings.weather_default_model,
                forecast_hours=settings.weather_refresh_forecast_hours,
                cache_ttl_seconds=settings.weather_cache_ttl_seconds,
            )
            refreshed.append(
                {
                    "layer_id": layer_id,
                    "model": weather.model,
                    "cache_status": weather.cache_status,
                    "summary": weather.summary,
                }
            )
        return refreshed

    def _build_map_layer_outputs(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        weather: WeatherPointResponse,
        spec,
        metric_value: float | int | str | None,
    ) -> tuple[list[WorkflowResultReference], list[str]]:
        point_feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [weather.longitude, weather.latitude]},
            "properties": {
                "place_name": weather.place_name,
                "metric": spec.primary_metric,
                "value": metric_value,
                "unit": spec.unit_label,
            },
        }
        result_refs: list[WorkflowResultReference] = []
        diagnostics: list[str] = []
        geojson_ref: WorkflowResultReference | None = None
        cog_ref: WorkflowResultReference | None = None

        if spec.layer_id == "wind-field":
            bbox = self._resolve_render_bbox(payload, weather.latitude, weather.longitude)
            feature_collection = self.build_wind_geojson(weather, bbox)
            geojson_ref = result_storage_service.create_artifact_result_ref(
                run_id=run_id,
                result_id=f"wind-geojson-{uuid4().hex[:10]}",
                result_kind=ResultKind.file,
                title=f"{spec.display_name} GeoJSON Layer",
                mime_type="application/geo+json",
                updated_at=requested_at,
                payload=feature_collection,
            )
            result_refs.append(geojson_ref)
            diagnostics.append(f"wind_geojson_points={len(feature_collection['features'])}")
        elif spec.layer_id == "temperature":
            bbox = self._resolve_render_bbox(payload, weather.latitude, weather.longitude)
            feature_collection = self.build_temperature_geojson(weather, bbox)
            geojson_ref = result_storage_service.create_artifact_result_ref(
                run_id=run_id,
                result_id=f"temperature-geojson-{uuid4().hex[:10]}",
                result_kind=ResultKind.file,
                title=f"{spec.display_name} GeoJSON Layer",
                mime_type="application/geo+json",
                updated_at=requested_at,
                payload=feature_collection,
            )
            result_refs.append(geojson_ref)
            diagnostics.append(f"temperature_geojson_cells={len(feature_collection['features'])}")

            cog_ref, cog_diagnostics = self._build_temperature_cog_artifact(
                run_id=run_id,
                requested_at=requested_at,
                weather=weather,
                bbox=bbox,
                spec=spec,
            )
            if cog_ref is not None:
                result_refs.append(cog_ref)
            diagnostics.extend(cog_diagnostics)
        elif spec.layer_id == "precipitation":
            bbox = self._resolve_render_bbox(payload, weather.latitude, weather.longitude)
            feature_collection = self.build_precipitation_geojson(weather, bbox)
            geojson_ref = result_storage_service.create_artifact_result_ref(
                run_id=run_id,
                result_id=f"precipitation-geojson-{uuid4().hex[:10]}",
                result_kind=ResultKind.file,
                title=f"{spec.display_name} GeoJSON Layer",
                mime_type="application/geo+json",
                updated_at=requested_at,
                payload=feature_collection,
            )
            result_refs.append(geojson_ref)
            diagnostics.append(f"precipitation_geojson_cells={len(feature_collection['features'])}")

            cog_ref, cog_diagnostics = self._build_precipitation_cog_artifact(
                run_id=run_id,
                requested_at=requested_at,
                weather=weather,
                bbox=bbox,
                spec=spec,
            )
            if cog_ref is not None:
                result_refs.append(cog_ref)
            diagnostics.extend(cog_diagnostics)

        result_refs.append(
            WorkflowResultReference(
                result_id=f"weather-layer-{uuid4().hex[:10]}",
                result_kind=ResultKind.map_layer,
                title=f"{spec.display_name} Render Hint",
                mime_type="application/json",
                inline_data={
                    "render_hint": weather.render_hint.model_dump(mode="json"),
                    "point_feature": point_feature,
                    "layer_assets": {
                        "geojson_url": geojson_ref.resource_url if geojson_ref else None,
                        "cog_url": cog_ref.resource_url if cog_ref else None,
                    },
                },
                updated_at=requested_at,
            )
        )
        return result_refs, diagnostics

    def build_wind_geojson(
        self,
        weather: WeatherPointResponse,
        bbox: BoundingBox,
        rows: int = 9,
        cols: int = 11,
    ) -> dict[str, object]:
        features: list[dict[str, object]] = []
        lat_step = (bbox.north - bbox.south) / rows
        lon_step = (bbox.east - bbox.west) / cols
        base_speed = weather.current.wind_speed_10m or 0.0
        base_direction = weather.current.wind_direction_10m or 0.0
        for row in range(rows):
            for col in range(cols):
                lat = bbox.south + (row + 0.5) * lat_step
                lon = bbox.west + (col + 0.5) * lon_step
                speed, direction = self._wind_value_for_location(
                    base_speed=base_speed,
                    base_direction=base_direction,
                    center_lat=weather.latitude,
                    center_lon=weather.longitude,
                    lat=lat,
                    lon=lon,
                    lat_span=max(0.1, bbox.north - bbox.south),
                    lon_span=max(0.1, bbox.east - bbox.west),
                )
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": {
                            "wind_speed_10m": round(speed, 2),
                            "wind_direction_10m": round(direction, 1),
                            "unit": "m/s",
                            "row": row,
                            "col": col,
                        },
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    def build_temperature_geojson(
        self,
        weather: WeatherPointResponse,
        bbox: BoundingBox,
        rows: int = 18,
        cols: int = 18,
    ) -> dict[str, object]:
        features: list[dict[str, object]] = []
        lat_step = (bbox.north - bbox.south) / rows
        lon_step = (bbox.east - bbox.west) / cols
        base_temp = weather.current.temperature_2m or 0.0
        for row in range(rows):
            for col in range(cols):
                south = bbox.south + row * lat_step
                north = south + lat_step
                west = bbox.west + col * lon_step
                east = west + lon_step
                cell_lat = south + lat_step / 2
                cell_lon = west + lon_step / 2
                value = self._temperature_value_for_location(
                    base_temp=base_temp,
                    center_lat=weather.latitude,
                    center_lon=weather.longitude,
                    lat=cell_lat,
                    lon=cell_lon,
                    lat_span=max(0.1, bbox.north - bbox.south),
                    lon_span=max(0.1, bbox.east - bbox.west),
                )
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[
                                [west, south],
                                [east, south],
                                [east, north],
                                [west, north],
                                [west, south],
                            ]],
                        },
                        "properties": {
                            "temperature_2m": round(value, 2),
                            "unit": "C",
                            "row": row,
                            "col": col,
                        },
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    def _build_temperature_cog_artifact(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        weather: WeatherPointResponse,
        bbox: BoundingBox,
        spec,
    ) -> tuple[WorkflowResultReference | None, list[str]]:
        diagnostics: list[str] = []
        try:
            numpy = importlib.import_module("numpy")
            transform_module = importlib.import_module("rasterio.transform")
            raster_writer_module = importlib.import_module("algorithms.providers.Python.publish.raster_writer")
        except Exception as exc:
            diagnostics.append(f"temperature_cog_skipped={exc.__class__.__name__}")
            return None, diagnostics

        rows = 96
        cols = 96
        array = numpy.zeros((rows, cols), dtype="float32")
        base_temp = weather.current.temperature_2m or 0.0
        for row in range(rows):
            lat = bbox.north - ((row + 0.5) / rows) * (bbox.north - bbox.south)
            for col in range(cols):
                lon = bbox.west + ((col + 0.5) / cols) * (bbox.east - bbox.west)
                array[row, col] = self._temperature_value_for_location(
                    base_temp=base_temp,
                    center_lat=weather.latitude,
                    center_lon=weather.longitude,
                    lat=lat,
                    lon=lon,
                    lat_span=max(0.1, bbox.north - bbox.south),
                    lon_span=max(0.1, bbox.east - bbox.west),
                )

        writer_cls = getattr(raster_writer_module, "COGWriter", None)
        if writer_cls is None:
            diagnostics.append("temperature_cog_skipped=missing_cog_writer")
            return None, diagnostics

        job_dir = Path(settings.cache_dir) / "weatherengine" / run_id
        writer = writer_cls(output_dir=job_dir, overwrite=True)
        transform = transform_module.from_bounds(bbox.west, bbox.south, bbox.east, bbox.north, cols, rows)
        output_name = f"temperature_{run_id}"
        result = writer.write(
            array,
            output_name,
            crs="EPSG:4326",
            transform=transform,
            unit=spec.unit_label,
            description="WeatherEngine temperature raster preview",
        )
        cog_path = job_dir / result["path"]
        cog_ref = result_storage_service.create_artifact_result_ref(
            run_id=run_id,
            result_id=f"temperature-cog-{uuid4().hex[:10]}",
            result_kind=ResultKind.file,
            title=f"{spec.display_name} COG Layer",
            mime_type="image/tiff",
            updated_at=requested_at,
            payload=cog_path.read_bytes(),
        )
        diagnostics.append(f"temperature_cog_size_bytes={cog_ref.resource_size_bytes or 0}")
        return cog_ref, diagnostics

    def build_precipitation_geojson(
        self,
        weather: WeatherPointResponse,
        bbox: BoundingBox,
        rows: int = 18,
        cols: int = 18,
    ) -> dict[str, object]:
        features: list[dict[str, object]] = []
        lat_step = (bbox.north - bbox.south) / rows
        lon_step = (bbox.east - bbox.west) / cols
        base_precip = weather.current.precipitation or 0.0
        for row in range(rows):
            for col in range(cols):
                south = bbox.south + row * lat_step
                north = south + lat_step
                west = bbox.west + col * lon_step
                east = west + lon_step
                cell_lat = south + lat_step / 2
                cell_lon = west + lon_step / 2
                value = self._precipitation_value_for_location(
                    base_precip=base_precip,
                    center_lat=weather.latitude,
                    center_lon=weather.longitude,
                    lat=cell_lat,
                    lon=cell_lon,
                    lat_span=max(0.1, bbox.north - bbox.south),
                    lon_span=max(0.1, bbox.east - bbox.west),
                )
                if value < 0.1:
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[
                                [west, south],
                                [east, south],
                                [east, north],
                                [west, north],
                                [west, south],
                            ]],
                        },
                        "properties": {
                            "precipitation": round(value, 2),
                            "unit": "mm",
                            "row": row,
                            "col": col,
                        },
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    def _build_precipitation_cog_artifact(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        weather: WeatherPointResponse,
        bbox: BoundingBox,
        spec,
    ) -> tuple[WorkflowResultReference | None, list[str]]:
        diagnostics: list[str] = []
        try:
            numpy = importlib.import_module("numpy")
            transform_module = importlib.import_module("rasterio.transform")
            raster_writer_module = importlib.import_module("algorithms.providers.Python.publish.raster_writer")
        except Exception as exc:
            diagnostics.append(f"precipitation_cog_skipped={exc.__class__.__name__}")
            return None, diagnostics

        rows = 96
        cols = 96
        array = numpy.zeros((rows, cols), dtype="float32")
        base_precip = weather.current.precipitation or 0.0
        for row in range(rows):
            lat = bbox.north - ((row + 0.5) / rows) * (bbox.north - bbox.south)
            for col in range(cols):
                lon = bbox.west + ((col + 0.5) / cols) * (bbox.east - bbox.west)
                array[row, col] = self._precipitation_value_for_location(
                    base_precip=base_precip,
                    center_lat=weather.latitude,
                    center_lon=weather.longitude,
                    lat=lat,
                    lon=lon,
                    lat_span=max(0.1, bbox.north - bbox.south),
                    lon_span=max(0.1, bbox.east - bbox.west),
                )

        writer_cls = getattr(raster_writer_module, "COGWriter", None)
        if writer_cls is None:
            diagnostics.append("precipitation_cog_skipped=missing_cog_writer")
            return None, diagnostics

        job_dir = Path(settings.cache_dir) / "weatherengine" / run_id
        writer = writer_cls(output_dir=job_dir, overwrite=True)
        transform = transform_module.from_bounds(bbox.west, bbox.south, bbox.east, bbox.north, cols, rows)
        output_name = f"precipitation_{run_id}"
        result = writer.write(
            array,
            output_name,
            crs="EPSG:4326",
            transform=transform,
            unit=spec.unit_label,
            description="WeatherEngine precipitation raster preview",
        )
        cog_path = job_dir / result["path"]
        cog_ref = result_storage_service.create_artifact_result_ref(
            run_id=run_id,
            result_id=f"precipitation-cog-{uuid4().hex[:10]}",
            result_kind=ResultKind.file,
            title=f"{spec.display_name} COG Layer",
            mime_type="image/tiff",
            updated_at=requested_at,
            payload=cog_path.read_bytes(),
        )
        diagnostics.append(f"precipitation_cog_size_bytes={cog_ref.resource_size_bytes or 0}")
        return cog_ref, diagnostics

    def _resolve_render_bbox(
        self,
        payload: WorkflowSubmitRequest,
        latitude: float,
        longitude: float,
    ) -> BoundingBox:
        if payload.map_context.viewport_bbox is not None:
            return payload.map_context.viewport_bbox
        if payload.spatial_filter and payload.spatial_filter.bbox is not None:
            return payload.spatial_filter.bbox
        return BoundingBox(
            west=longitude - 1.6,
            south=latitude - 1.2,
            east=longitude + 1.6,
            north=latitude + 1.2,
            crs="EPSG:4326",
        )

    def _temperature_value_for_location(
        self,
        *,
        base_temp: float,
        center_lat: float,
        center_lon: float,
        lat: float,
        lon: float,
        lat_span: float,
        lon_span: float,
    ) -> float:
        lat_norm = (lat - center_lat) / lat_span
        lon_norm = (lon - center_lon) / lon_span
        radial = math.sqrt(lat_norm * lat_norm + lon_norm * lon_norm)
        return base_temp - lat_norm * 4.8 + lon_norm * 2.2 - radial * 5.5

    def _precipitation_value_for_location(
        self,
        *,
        base_precip: float,
        center_lat: float,
        center_lon: float,
        lat: float,
        lon: float,
        lat_span: float,
        lon_span: float,
    ) -> float:
        lat_norm = (lat - center_lat) / lat_span
        lon_norm = (lon - center_lon) / lon_span
        radial = math.sqrt(lat_norm * lat_norm + lon_norm * lon_norm)
        core = max(0.0, 1.28 - radial * 2.15)
        band = max(0.0, 0.72 - abs(lat_norm + lon_norm * 0.55) * 1.4)
        return max(0.0, base_precip + core * 8.5 + band * 4.2 - radial * 1.1)

    def _wind_value_for_location(
        self,
        *,
        base_speed: float,
        base_direction: float,
        center_lat: float,
        center_lon: float,
        lat: float,
        lon: float,
        lat_span: float,
        lon_span: float,
    ) -> tuple[float, float]:
        lat_norm = (lat - center_lat) / lat_span
        lon_norm = (lon - center_lon) / lon_span
        radial = math.sqrt(lat_norm * lat_norm + lon_norm * lon_norm)
        speed = max(0.0, base_speed + lon_norm * 3.2 - lat_norm * 1.4 + math.sin((lat_norm + lon_norm) * math.pi) * 1.2)
        direction = (base_direction + lon_norm * 36.0 - lat_norm * 24.0 + radial * 18.0) % 360
        return speed, direction

    def _resolve_point(self, payload: WorkflowSubmitRequest) -> tuple[float, float, str | None]:
        latitude = self._as_float(payload.parameters.get("latitude"))
        longitude = self._as_float(payload.parameters.get("longitude"))
        place_name = self._as_string(payload.parameters.get("place_name"))
        if latitude is not None and longitude is not None:
            return latitude, longitude, place_name
        if payload.spatial_filter and payload.spatial_filter.bbox:
            bbox = payload.spatial_filter.bbox
            return (bbox.south + bbox.north) / 2, (bbox.west + bbox.east) / 2, place_name
        return settings.weather_default_latitude, settings.weather_default_longitude, place_name or settings.weather_default_place_name

    def _resolve_forecast_hours(self, payload: WorkflowSubmitRequest) -> int:
        requested = self._as_int(payload.parameters.get("forecast_hours"))
        if requested is None:
            return settings.weather_refresh_forecast_hours
        return max(1, min(24, requested))

    def _pick_series_value(self, hourly: dict[str, object], key: str, index: int) -> float | None:
        values = hourly.get(key)
        if isinstance(values, list) and index < len(values):
            value = values[index]
            if isinstance(value, (int, float)):
                return float(value)
        return None

    def _coerce_datetime(self, value: object) -> datetime | None:
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return datetime.fromisoformat(text)
        return None

    def _as_float(self, value: object) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value)
            except ValueError:
                return None
        return None

    def _as_int(self, value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.strip():
            try:
                return int(float(value))
            except ValueError:
                return None
        return None

    def _as_string(self, value: object) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None


weather_engine_service = WeatherEngineService()
