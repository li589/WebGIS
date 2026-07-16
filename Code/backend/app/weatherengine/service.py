from __future__ import annotations

from datetime import datetime, timezone
import importlib
import logging
import math
from pathlib import Path
from urllib.error import HTTPError, URLError
from uuid import uuid4

from app.core.config import settings
from app.services.api_config import api_config_manager, ApiProvider, DataType
from app.services.result_storage import result_storage_service
from app.services.workflow_execution import WorkflowExecutionResult
from app.weatherengine.constants import DEFAULT_LAYER_ID, DEFAULT_POINT, WEATHER_LAYER_SPECS
from app.weatherengine.nodes._utils import compute_dynamic_resolution
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

logger = logging.getLogger(__name__)


class WeatherEngineService:
    """天气引擎服务 — 提供"渲染原语"与 REST 端点直查。

    M12 修复：明确与 WeatherWorkflowService 的职责边界。
    - 本类负责：API 调用（Open-Meteo/GEE/百度/高德/天地图）、forecast 解析、GeoJSON/COG 渲染原语。
    - 节点依赖：仅依赖本类的渲染原语方法（build_wind_geojson 等）与解析方法
      （parse_forecast_to_point），不依赖 workflow 编排逻辑。
    - workflow 编排由 WeatherWorkflowService 负责，节点之间通过 ExecutionContext 传递数据。
    - REST 端点 /weather/point 直接调用本类 get_point_weather。
    - workflow-runs 调度链中，本类仅作为 layer-based fallback（无 weather_request 字段时）。

    M15 增强：集成 api_config_manager，支持多数据源切换（Gee、百度、高德、天地图等）。
    """

    def __init__(self) -> None:
        self._active_provider = ApiProvider.OPEN_METEO

    def get_active_provider(self) -> ApiProvider:
        """获取当前活跃的天气数据 Provider。"""
        # 优先使用 api_config_manager 中配置的天气 Provider
        # M15 兼容：get_best_available 返回 ApiConfig 对象，不是字典
        best = api_config_manager.get_best_available(required_capabilities={DataType.WEATHER})
        if best:
            return best.provider
        return self._active_provider

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
        from app.weatherengine.fetch_gateway import fetch_point_forecast

        payload, cache_status, provider_label = fetch_point_forecast(
            layer_id=layer_id,
            latitude=latitude,
            longitude=longitude,
            model=resolved_model,
            forecast_hours=forecast_hours,
            ttl_seconds=cache_ttl_seconds,
            layer_spec=spec,
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
            provider=provider_label,
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
        provider: str = "open-meteo",
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
            primary_value = self._pick_series_value(hourly, spec.primary_metric, index)
            hourly_rows.append(
                WeatherPointHourlyEntry(
                    time=self._coerce_datetime(time_value),
                    temperature_2m=self._pick_series_value(hourly, "temperature_2m", index),
                    precipitation=self._pick_series_value(hourly, "precipitation", index),
                    wind_speed_10m=self._pick_series_value(hourly, "wind_speed_10m", index),
                    primary_metric=spec.primary_metric,
                    primary_value=primary_value,
                )
            )
        # 气压层变量仅出现在 hourly 段，取首小时作为当前值
        # 当 spec 未请求气压层时这些字段保持 None
        pl_wind_speed_850 = self._pick_series_value(hourly, "wind_speed_850hPa", 0)
        pl_wind_direction_850 = self._pick_series_value(hourly, "wind_direction_850hPa", 0)
        pl_temperature_850 = self._pick_series_value(hourly, "temperature_850hPa", 0)
        pl_wind_speed_500 = self._pick_series_value(hourly, "wind_speed_500hPa", 0)
        pl_wind_direction_500 = self._pick_series_value(hourly, "wind_direction_500hPa", 0)
        pl_temperature_500 = self._pick_series_value(hourly, "temperature_500hPa", 0)
        pl_wind_speed_200 = self._pick_series_value(hourly, "wind_speed_200hPa", 0)
        pl_wind_direction_200 = self._pick_series_value(hourly, "wind_direction_200hPa", 0)
        pl_temperature_200 = self._pick_series_value(hourly, "temperature_200hPa", 0)

        # metric_value 优先从 current 取；气压层变量不在 current 段，回退到 hourly 首小时
        metric_value = current.get(spec.primary_metric)
        if metric_value is None and spec.pressure_levels:
            metric_value = self._pick_series_value(hourly, spec.primary_metric, 0)
        summary = spec.summary_template.format(value=metric_value if metric_value is not None else "--", unit=spec.unit_label)
        observation_time = self._coerce_datetime(current.get("time"))
        return WeatherPointResponse(
            provider=provider,
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
                surface_pressure=current.get("surface_pressure"),
                wind_speed_10m=current.get("wind_speed_10m"),
                wind_direction_10m=current.get("wind_direction_10m"),
                wind_gusts_10m=current.get("wind_gusts_10m"),
                wind_speed_80m=current.get("wind_speed_80m"),
                wind_direction_80m=current.get("wind_direction_80m"),
                wind_speed_120m=current.get("wind_speed_120m"),
                wind_direction_120m=current.get("wind_direction_120m"),
                wind_speed_180m=current.get("wind_speed_180m"),
                wind_direction_180m=current.get("wind_direction_180m"),
                temperature_80m=current.get("temperature_80m"),
                temperature_120m=current.get("temperature_120m"),
                temperature_180m=current.get("temperature_180m"),
                relative_humidity_2m=current.get("relative_humidity_2m"),
                dew_point_2m=current.get("dew_point_2m"),
                visibility=current.get("visibility"),
                # 气压层变量（仅在 spec 请求 pressure_levels 时有值）
                wind_speed_850hPa=pl_wind_speed_850,
                wind_direction_850hPa=pl_wind_direction_850,
                temperature_850hPa=pl_temperature_850,
                wind_speed_500hPa=pl_wind_speed_500,
                wind_direction_500hPa=pl_wind_direction_500,
                temperature_500hPa=pl_temperature_500,
                wind_speed_200hPa=pl_wind_speed_200,
                wind_direction_200hPa=pl_wind_direction_200,
                temperature_200hPa=pl_temperature_200,
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
                f"provider={provider}",
                f"layer_id={layer_id}",
                f"model={resolved_model}",
                f"cache_status={cache_status}",
                f"render_mode={spec.paint_mode}",
            ],
        )

    def _build_fallback_weather(
        self,
        *,
        layer_id: str,
        latitude: float,
        longitude: float,
        place_name: str | None,
        spec,
        error_message: str,
    ) -> WeatherPointResponse:
        """当 Open-Meteo API 不可用时构建降级 WeatherPointResponse，保证网格渲染工作流可继续。"""
        logger.info("[WeatherEngine] building fallback weather for layer=%s lat=%.4f lon=%.4f", layer_id, latitude, longitude)
        return WeatherPointResponse(
            provider="open-meteo",
            model=spec.default_model if hasattr(spec, 'default_model') else "icon_seamless",
            resolved_model=None,
            layer_id=layer_id,
            latitude=latitude,
            longitude=longitude,
            place_name=place_name,
            timezone=None,
            fetched_at=datetime.now(timezone.utc),
            observation_time=None,
            cache_status="fallback",
            summary=f"{spec.display_name} 点位数据暂不可用（API 限流），网格渲染仍可继续。",
            current=WeatherPointCurrent(
                temperature_2m=None,
                apparent_temperature=None,
                precipitation=None,
                rain=None,
                weather_code=None,
                cloud_cover=None,
                pressure_msl=None,
                surface_pressure=None,
                wind_speed_10m=None,
                wind_direction_10m=None,
                wind_gusts_10m=None,
                wind_speed_80m=None,
                wind_direction_80m=None,
                wind_speed_120m=None,
                wind_direction_120m=None,
                wind_speed_180m=None,
                wind_direction_180m=None,
                temperature_80m=None,
                temperature_120m=None,
                temperature_180m=None,
                relative_humidity_2m=None,
                dew_point_2m=None,
                visibility=None,
                wind_speed_850hPa=None,
                wind_direction_850hPa=None,
                temperature_850hPa=None,
                wind_speed_500hPa=None,
                wind_direction_500hPa=None,
                temperature_500hPa=None,
                wind_speed_200hPa=None,
                wind_direction_200hPa=None,
                temperature_200hPa=None,
            ),
            hourly=[],
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
                f"cache_status=fallback",
                f"render_mode={spec.paint_mode}",
                f"point_weather_error={error_message}",
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
        # [WeatherEngine] 调试：打印工作流入参
        vp_bbox = payload.map_context.viewport_bbox
        logger.info(
            "[WeatherEngine] execute: run_id=%s layer_id=%s lat=%s lon=%s place=%s forecast_hours=%s viewport_bbox=%s params=%s",
            run_id, layer_id, latitude, longitude, place_name, forecast_hours,
            f"({vp_bbox.west},{vp_bbox.south},{vp_bbox.east},{vp_bbox.north})" if vp_bbox else "None",
            {k: v for k, v in payload.parameters.items() if k in ('hour', 'latitude', 'longitude', 'weather_model')},
        )
        spec = WEATHER_LAYER_SPECS[layer_id]
        try:
            weather = self.get_point_weather(
                layer_id=layer_id,
                latitude=latitude,
                longitude=longitude,
                model=self._as_string(payload.parameters.get("weather_model")),
                forecast_hours=forecast_hours,
                place_name=place_name,
                cache_ttl_seconds=self._as_int(payload.parameters.get("cache_ttl_seconds")),
            )
        except (HTTPError, URLError, OSError) as exc:
            # 点位天气 API 失败（如 429 限流）不应阻断网格渲染工作流
            logger.warning("[WeatherEngine] point weather failed, continuing with fallback: %s", exc)
            weather = self._build_fallback_weather(
                layer_id=layer_id,
                latitude=latitude,
                longitude=longitude,
                place_name=place_name,
                spec=spec,
                error_message=str(exc),
            )
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

    def _fetch_layer_grid_data(self, *, bbox: BoundingBox, spec) -> tuple[dict[str, Any], str, float]:
        from app.weatherengine.fetch_gateway import fetch_grid_forecast

        resolution = compute_dynamic_resolution(bbox)
        grid_data, cache_status, _provider_id = fetch_grid_forecast(
            layer_id=spec.layer_id,
            bbox=bbox,
            resolution=resolution,
            layer_spec=spec,
        )
        return grid_data, cache_status, resolution

    def _build_geojson_from_grid(self, *, grid_data: dict[str, Any], layer_id: str) -> dict[str, object]:
        if layer_id == "precipitation":
            return self.build_precipitation_geojson_from_grid(grid_data, layer_id)
        if layer_id == "humidity":
            return self.build_humidity_geojson_from_grid(grid_data, layer_id)
        if layer_id == "pressure":
            return self.build_pressure_geojson_from_grid(grid_data, layer_id)
        if layer_id == "visibility":
            return self.build_visibility_geojson_from_grid(grid_data, layer_id)
        if layer_id == "temperature" or layer_id.startswith("temperature-"):
            return self.build_temperature_geojson_from_grid(grid_data, layer_id)
        return self.build_wind_geojson_from_grid(grid_data, layer_id)

    def _build_scalar_array_from_grid(
        self,
        *,
        numpy,
        grid_data: dict[str, Any],
        field_name: str,
        rows: int,
        cols: int,
        fallback_field: str | None = None,
    ):
        array = numpy.zeros((rows, cols), dtype="float32")
        grid = grid_data.get("grid") or {}
        current = (grid_data.get("data") or {}).get("current") or {}
        values = current.get(field_name)
        if not isinstance(values, list) and fallback_field:
            values = current.get(fallback_field)
        if not isinstance(values, list):
            return array

        src_rows = max(1, int(grid.get("rows") or 1))
        src_cols = max(1, int(grid.get("cols") or 1))
        for row in range(rows):
            src_row = min(src_rows - 1, int(row * src_rows / rows))
            for col in range(cols):
                src_col = min(src_cols - 1, int(col * src_cols / cols))
                src_idx = src_row * src_cols + src_col
                if src_idx >= len(values):
                    continue
                value = values[src_idx]
                if value is None:
                    continue
                array[row, col] = float(value)
        return array

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

        if spec.layer_id == "wind-field" or spec.layer_id.startswith("wind-field-"):
            bbox = self._resolve_render_bbox(payload, weather.latitude, weather.longitude)
            try:
                grid_data, cache_status, resolution = self._fetch_layer_grid_data(bbox=bbox, spec=spec)
                feature_collection = self.build_wind_geojson_from_grid(grid_data, spec.layer_id)
                logger.info(
                    "[WindDebug] build_wind_geojson_from_grid: layer=%s bbox=%s features=%d cache=%s resolution=%s",
                    spec.layer_id, bbox, len(feature_collection['features']), cache_status, resolution,
                )
            except (HTTPError, URLError, OSError, KeyError, ValueError) as exc:
                logger.warning("[WindDebug] Grid fetch failed, falling back to simulated data: %s", exc)
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
            logger.info(
                "[WindDebug] artifact created: result_id=%s resource_url=%s resource_key=%s",
                geojson_ref.result_id, geojson_ref.resource_url, geojson_ref.resource_key,
            )
            result_refs.append(geojson_ref)
            diagnostics.append(f"wind_geojson_points={len(feature_collection['features'])}")
            diagnostics.append(f"wind_height={feature_collection['features'][0]['properties']['height'] if feature_collection['features'] else '10m'}")
        elif spec.layer_id == "temperature" or spec.layer_id.startswith("temperature-"):
            bbox = self._resolve_render_bbox(payload, weather.latitude, weather.longitude)
            try:
                grid_data, _, _ = self._fetch_layer_grid_data(bbox=bbox, spec=spec)
                feature_collection = self.build_temperature_geojson_from_grid(grid_data, spec.layer_id)
            except (HTTPError, URLError, OSError, KeyError, ValueError):
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
            diagnostics.append(f"temperature_height={feature_collection['features'][0]['properties'].get('height', '2m') if feature_collection['features'] else '2m'}")

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
            try:
                grid_data, _, _ = self._fetch_layer_grid_data(bbox=bbox, spec=spec)
                feature_collection = self.build_precipitation_geojson_from_grid(grid_data, spec.layer_id)
            except (HTTPError, URLError, OSError, KeyError, ValueError):
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
        elif spec.layer_id == "humidity":
            bbox = self._resolve_render_bbox(payload, weather.latitude, weather.longitude)
            try:
                grid_data, _, _ = self._fetch_layer_grid_data(bbox=bbox, spec=spec)
                feature_collection = self.build_humidity_geojson_from_grid(grid_data, spec.layer_id)
            except (HTTPError, URLError, OSError, KeyError, ValueError):
                feature_collection = self.build_humidity_geojson(weather, bbox)
            geojson_ref = result_storage_service.create_artifact_result_ref(
                run_id=run_id,
                result_id=f"humidity-geojson-{uuid4().hex[:10]}",
                result_kind=ResultKind.file,
                title=f"{spec.display_name} GeoJSON Layer",
                mime_type="application/geo+json",
                updated_at=requested_at,
                payload=feature_collection,
            )
            result_refs.append(geojson_ref)
            diagnostics.append(f"humidity_geojson_cells={len(feature_collection['features'])}")
        elif spec.layer_id == "pressure":
            bbox = self._resolve_render_bbox(payload, weather.latitude, weather.longitude)
            try:
                grid_data, _, _ = self._fetch_layer_grid_data(bbox=bbox, spec=spec)
                feature_collection = self.build_pressure_geojson_from_grid(grid_data, spec.layer_id)
            except (HTTPError, URLError, OSError, KeyError, ValueError):
                feature_collection = self.build_pressure_geojson(weather, bbox)
            geojson_ref = result_storage_service.create_artifact_result_ref(
                run_id=run_id,
                result_id=f"pressure-geojson-{uuid4().hex[:10]}",
                result_kind=ResultKind.file,
                title=f"{spec.display_name} GeoJSON Layer",
                mime_type="application/geo+json",
                updated_at=requested_at,
                payload=feature_collection,
            )
            result_refs.append(geojson_ref)
            diagnostics.append(f"pressure_geojson_cells={len(feature_collection['features'])}")
        elif spec.layer_id == "visibility":
            bbox = self._resolve_render_bbox(payload, weather.latitude, weather.longitude)
            try:
                grid_data, _, _ = self._fetch_layer_grid_data(bbox=bbox, spec=spec)
                feature_collection = self.build_visibility_geojson_from_grid(grid_data, spec.layer_id)
            except (HTTPError, URLError, OSError, KeyError, ValueError):
                feature_collection = self.build_visibility_geojson(weather, bbox)
            geojson_ref = result_storage_service.create_artifact_result_ref(
                run_id=run_id,
                result_id=f"visibility-geojson-{uuid4().hex[:10]}",
                result_kind=ResultKind.file,
                title=f"{spec.display_name} GeoJSON Layer",
                mime_type="application/geo+json",
                updated_at=requested_at,
                payload=feature_collection,
            )
            result_refs.append(geojson_ref)
            diagnostics.append(f"visibility_geojson_cells={len(feature_collection['features'])}")

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
                        "cog_preview_url": f"/artifacts/{cog_ref.resource_key}/preview.png" if cog_ref and cog_ref.resource_key else None,
                        "cog_bbox": {
                            "west": bbox.west,
                            "south": bbox.south,
                            "east": bbox.east,
                            "north": bbox.north,
                            "crs": bbox.crs,
                        } if (cog_ref and (spec.layer_id.startswith("temperature") or spec.layer_id == "precipitation")) else None,
                    },
                },
                updated_at=requested_at,
            )
        )
        logger.info(
            "[WindDebug] map_layer result_ref created: geojson_url=%s cog_url=%s cog_preview=%s",
            geojson_ref.resource_url if geojson_ref else None,
            cog_ref.resource_url if cog_ref else None,
            f"/artifacts/{cog_ref.resource_key}/preview.png" if cog_ref and cog_ref.resource_key else None,
        )
        return result_refs, diagnostics

    def build_wind_geojson(
        self,
        weather: WeatherPointResponse,
        bbox: BoundingBox,
        rows: int | None = None,
        cols: int | None = None,
    ) -> dict[str, object]:
        features: list[dict[str, object]] = []
        # 根据 bbox 范围动态计算网格点数，保持约 0.3-0.4 度间隔
        # 最小 24×32（对应小视口），最大 180×360（全球约 1 度间隔）
        lat_span = max(0.1, bbox.north - bbox.south)
        lon_span = max(0.1, bbox.east - bbox.west)
        resolved_rows = rows if rows is not None else max(24, min(180, int(lat_span / 0.35)))
        resolved_cols = cols if cols is not None else max(32, min(360, int(lon_span / 0.35)))
        lat_step = lat_span / resolved_rows
        lon_step = lon_span / resolved_cols
        # 根据 layer_id 高度后缀读取对应字段：wind-field → 10m，wind-field-80m → 80m，…
        # 回退到 10m 字段，保证旧调用方兼容
        layer_id = weather.layer_id
        height_suffix = "10m"
        if layer_id and layer_id.startswith("wind-field-"):
            height_suffix = layer_id.split("-", 2)[-1]  # "80m" / "120m" / "180m"
        speed_attr = f"wind_speed_{height_suffix}"
        direction_attr = f"wind_direction_{height_suffix}"
        base_speed = getattr(weather.current, speed_attr, None) or weather.current.wind_speed_10m or 0.0
        base_direction = getattr(weather.current, direction_attr, None) or weather.current.wind_direction_10m or 0.0
        for row in range(resolved_rows):
            for col in range(resolved_cols):
                lat = bbox.south + (row + 0.5) * lat_step
                lon = bbox.west + (col + 0.5) * lon_step
                speed, direction = self._wind_value_for_location(
                    base_speed=base_speed,
                    base_direction=base_direction,
                    center_lat=weather.latitude,
                    center_lon=weather.longitude,
                    lat=lat,
                    lon=lon,
                    lat_span=lat_span,
                    lon_span=lon_span,
                )
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": {
                            speed_attr: round(speed, 2),
                            direction_attr: round(direction, 1),
                            "height": height_suffix,
                            "unit": "m/s",
                            "row": row,
                            "col": col,
                        },
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    def build_wind_geojson_from_grid(
        self,
        grid_data: dict[str, Any],
        layer_id: str,
    ) -> dict[str, object]:
        """从真实网格数据构建风场 GeoJSON。

        Args:
            grid_data: fetch_grid_forecast() 返回的网格数据
            layer_id: 图层类型（如 wind-field, wind-field-80m 等）

        Returns:
            GeoJSON FeatureCollection
        """
        grid = grid_data["grid"]
        current = grid_data["data"]["current"]

        rows, cols = grid["rows"], grid["cols"]
        lats = grid["lats"]
        lons = grid["lons"]
        features = []

        # 根据 layer_id 解析高度后缀
        height_suffix = "10m"
        if layer_id and layer_id.startswith("wind-field-"):
            height_suffix = layer_id.split("-", 2)[-1]  # "80m" / "120m" / "180m" / "850hPa" 等

        speed_attr = f"wind_speed_{height_suffix}"
        direction_attr = f"wind_direction_{height_suffix}"

        # Open-Meteo API 字段名转换（API 使用下划线）
        api_speed_attr = speed_attr.replace("-", "_")
        api_direction_attr = direction_attr.replace("-", "_")

        # 从 API 响应中提取数据（数组格式，按索引对应）
        speed_values = current.get(api_speed_attr, current.get("wind_speed_10m", []))
        direction_values = current.get(api_direction_attr, current.get("wind_direction_10m", []))

        # 风向数据缺失时的 fallback：使用随机方向避免所有粒子同向
        # 触发条件：列表为空，或所有值均为 None（缓存过期/字段缺失时可能出现）
        _dir_valid_count = sum(1 for v in direction_values if v is not None)
        if _dir_valid_count == 0:
            import random
            random.seed(42)  # 固定种子保证可复现
            total_points = rows * cols
            if len(speed_values) > 0:
                direction_values = [random.uniform(0, 360) for _ in range(len(speed_values))]
            else:
                # 风速和风向都缺失：生成完整的模拟数据，避免所有点 speed=0 direction=0
                # 导致前端所有粒子静止（竖直线条）
                speed_values = [random.uniform(3, 15) for _ in range(total_points)]
                direction_values = [random.uniform(0, 360) for _ in range(total_points)]
            logger.warning(
                "[WeatherEngine] build_wind_geojson_from_grid: wind data missing or incomplete "
                "(speed_values=%d direction_values=%d), using random fallback",
                len(speed_values), len(direction_values),
            )

        # [WeatherEngine] 调试：打印网格数据概要
        speed_sample = [speed_values[i] for i in range(min(5, len(speed_values))) if speed_values[i] is not None]
        dir_sample = [direction_values[i] for i in range(min(5, len(direction_values))) if direction_values[i] is not None]
        logger.info(
            "[WeatherEngine] build_wind_geojson_from_grid: layer=%s rows=%d cols=%d total=%d speed_attr=%s(speed_values=%d, sample=%s) dir_attr=%s(dir_values=%d, sample=%s) lats=[%.4f..%.4f] lons=[%.4f..%.4f]",
            layer_id, rows, cols, rows * cols,
            api_speed_attr, len(speed_values), speed_sample,
            api_direction_attr, len(direction_values), dir_sample,
            lats[0] if lats else 0, lats[-1] if lats else 0,
            lons[0] if lons else 0, lons[-1] if lons else 0,
        )

        for i in range(rows):
            for j in range(cols):
                idx = i * cols + j
                lat = lats[i] if i < len(lats) else 0
                lon = lons[j] if j < len(lons) else 0

                speed = speed_values[idx] if idx < len(speed_values) else 0
                direction = direction_values[idx] if idx < len(direction_values) else 0

                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        speed_attr: round(speed, 2) if speed is not None else 0,
                        direction_attr: round(direction, 1) if direction is not None else 0,
                        "height": height_suffix,
                        "unit": "m/s",
                        "row": i,
                        "col": j,
                    }
                })

        logger.info("[WeatherEngine] build_wind_geojson_from_grid: generated %d features, first=(%.4f,%.4f) last=(%.4f,%.4f)",
            len(features),
            features[0]["geometry"]["coordinates"][0] if features else 0,
            features[0]["geometry"]["coordinates"][1] if features else 0,
            features[-1]["geometry"]["coordinates"][0] if features else 0,
            features[-1]["geometry"]["coordinates"][1] if features else 0,
        )
        return {"type": "FeatureCollection", "features": features}

    def build_temperature_geojson(
        self,
        weather: WeatherPointResponse,
        bbox: BoundingBox,
        rows: int | None = None,
        cols: int | None = None,
    ) -> dict[str, object]:
        features: list[dict[str, object]] = []
        # 根据 bbox 范围动态计算网格点数
        lat_span = max(0.1, bbox.north - bbox.south)
        lon_span = max(0.1, bbox.east - bbox.west)
        resolved_rows = rows if rows is not None else max(18, min(120, int(lat_span / 0.4)))
        resolved_cols = cols if cols is not None else max(18, min(120, int(lon_span / 0.4)))
        lat_step = lat_span / resolved_rows
        lon_step = lon_span / resolved_cols
        # 根据 layer_id 高度后缀读取对应字段：temperature → 2m，temperature-80m → 80m，…
        # 回退到 temperature_2m，保证旧调用方兼容
        layer_id = weather.layer_id
        height_suffix = "2m"
        if layer_id and layer_id.startswith("temperature-"):
            height_suffix = layer_id.split("-", 1)[-1]  # "80m" / "120m" / "180m"
        temp_attr = f"temperature_{height_suffix}"
        base_temp = getattr(weather.current, temp_attr, None) or weather.current.temperature_2m or 0.0
        for row in range(resolved_rows):
            for col in range(resolved_cols):
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
                    lat_span=lat_span,
                    lon_span=lon_span,
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
                            temp_attr: round(value, 2),
                            "height": height_suffix,
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
        except ImportError as exc:
            diagnostics.append(f"temperature_cog_skipped={exc.__class__.__name__}")
            return None, diagnostics

        rows = 96
        cols = 96
        # 同步 build_temperature_geojson 的多高度字段读取逻辑
        layer_id = weather.layer_id
        height_suffix = "2m"
        if layer_id and layer_id.startswith("temperature-"):
            height_suffix = layer_id.split("-", 1)[-1]
        temp_attr = f"temperature_{height_suffix}"
        api_temp_attr = temp_attr.replace("-", "_")
        try:
            grid_data, _, _ = self._fetch_layer_grid_data(bbox=bbox, spec=spec)
            array = self._build_scalar_array_from_grid(
                numpy=numpy,
                grid_data=grid_data,
                field_name=api_temp_attr,
                fallback_field="temperature_2m",
                rows=rows,
                cols=cols,
            )
        except (HTTPError, URLError, OSError, KeyError, ValueError):
            array = numpy.zeros((rows, cols), dtype="float32")
            base_temp = getattr(weather.current, temp_attr, None) or weather.current.temperature_2m or 0.0
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
        output_name = f"temperature_{height_suffix}_{run_id}"
        result = writer.write(
            array,
            output_name,
            crs="EPSG:4326",
            transform=transform,
            unit=spec.unit_label,
            description=f"WeatherEngine temperature ({height_suffix}) raster preview",
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
        rows: int | None = None,
        cols: int | None = None,
    ) -> dict[str, object]:
        features: list[dict[str, object]] = []
        # 根据 bbox 范围动态计算网格点数
        lat_span = max(0.1, bbox.north - bbox.south)
        lon_span = max(0.1, bbox.east - bbox.west)
        resolved_rows = rows if rows is not None else max(18, min(120, int(lat_span / 0.4)))
        resolved_cols = cols if cols is not None else max(18, min(120, int(lon_span / 0.4)))
        lat_step = lat_span / resolved_rows
        lon_step = lon_span / resolved_cols
        base_precip = weather.current.precipitation or 0.0
        for row in range(resolved_rows):
            for col in range(resolved_cols):
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
                    lat_span=lat_span,
                    lon_span=lon_span,
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
        except ImportError as exc:
            diagnostics.append(f"precipitation_cog_skipped={exc.__class__.__name__}")
            return None, diagnostics

        rows = 96
        cols = 96
        try:
            grid_data, _, _ = self._fetch_layer_grid_data(bbox=bbox, spec=spec)
            array = self._build_scalar_array_from_grid(
                numpy=numpy,
                grid_data=grid_data,
                field_name="precipitation",
                rows=rows,
                cols=cols,
            )
        except (HTTPError, URLError, OSError, KeyError, ValueError):
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

    def build_humidity_geojson(
        self,
        weather: WeatherPointResponse,
        bbox: BoundingBox,
        rows: int | None = None,
        cols: int | None = None,
    ) -> dict[str, object]:
        features: list[dict[str, object]] = []
        # 根据 bbox 范围动态计算网格点数
        lat_span = max(0.1, bbox.north - bbox.south)
        lon_span = max(0.1, bbox.east - bbox.west)
        resolved_rows = rows if rows is not None else max(18, min(120, int(lat_span / 0.4)))
        resolved_cols = cols if cols is not None else max(18, min(120, int(lon_span / 0.4)))
        lat_step = lat_span / resolved_rows
        lon_step = lon_span / resolved_cols
        base_humidity = weather.current.relative_humidity_2m or 0.0
        for row in range(resolved_rows):
            for col in range(resolved_cols):
                south = bbox.south + row * lat_step
                north = south + lat_step
                west = bbox.west + col * lon_step
                east = west + lon_step
                cell_lat = south + lat_step / 2
                cell_lon = west + lon_step / 2
                value = self._humidity_value_for_location(
                    base_humidity=base_humidity,
                    center_lat=weather.latitude,
                    center_lon=weather.longitude,
                    lat=cell_lat,
                    lon=cell_lon,
                    lat_span=lat_span,
                    lon_span=lon_span,
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
                            "relative_humidity_2m": round(value, 2),
                            "unit": "%",
                            "row": row,
                            "col": col,
                        },
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    def build_pressure_geojson(
        self,
        weather: WeatherPointResponse,
        bbox: BoundingBox,
        rows: int | None = None,
        cols: int | None = None,
    ) -> dict[str, object]:
        features: list[dict[str, object]] = []
        # 根据 bbox 范围动态计算网格点数
        lat_span = max(0.1, bbox.north - bbox.south)
        lon_span = max(0.1, bbox.east - bbox.west)
        resolved_rows = rows if rows is not None else max(18, min(120, int(lat_span / 0.4)))
        resolved_cols = cols if cols is not None else max(18, min(120, int(lon_span / 0.4)))
        lat_step = lat_span / resolved_rows
        lon_step = lon_span / resolved_cols
        base_pressure = weather.current.pressure_msl or 0.0
        for row in range(resolved_rows):
            for col in range(resolved_cols):
                south = bbox.south + row * lat_step
                north = south + lat_step
                west = bbox.west + col * lon_step
                east = west + lon_step
                cell_lat = south + lat_step / 2
                cell_lon = west + lon_step / 2
                value = self._pressure_value_for_location(
                    base_pressure=base_pressure,
                    center_lat=weather.latitude,
                    center_lon=weather.longitude,
                    lat=cell_lat,
                    lon=cell_lon,
                    lat_span=lat_span,
                    lon_span=lon_span,
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
                            "pressure_msl": round(value, 2),
                            "unit": "hPa",
                            "row": row,
                            "col": col,
                        },
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    def build_visibility_geojson(
        self,
        weather: WeatherPointResponse,
        bbox: BoundingBox,
        rows: int | None = None,
        cols: int | None = None,
    ) -> dict[str, object]:
        features: list[dict[str, object]] = []
        # 根据 bbox 范围动态计算网格点数
        lat_span = max(0.1, bbox.north - bbox.south)
        lon_span = max(0.1, bbox.east - bbox.west)
        resolved_rows = rows if rows is not None else max(18, min(120, int(lat_span / 0.4)))
        resolved_cols = cols if cols is not None else max(18, min(120, int(lon_span / 0.4)))
        lat_step = lat_span / resolved_rows
        lon_step = lon_span / resolved_cols
        base_visibility = weather.current.visibility or 0.0
        for row in range(resolved_rows):
            for col in range(resolved_cols):
                south = bbox.south + row * lat_step
                north = south + lat_step
                west = bbox.west + col * lon_step
                east = west + lon_step
                cell_lat = south + lat_step / 2
                cell_lon = west + lon_step / 2
                value = self._visibility_value_for_location(
                    base_visibility=base_visibility,
                    center_lat=weather.latitude,
                    center_lon=weather.longitude,
                    lat=cell_lat,
                    lon=cell_lon,
                    lat_span=lat_span,
                    lon_span=lon_span,
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
                            "visibility": round(value, 2),
                            "unit": "m",
                            "row": row,
                            "col": col,
                        },
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    def build_temperature_geojson_from_grid(
        self,
        grid_data: dict[str, Any],
        layer_id: str,
    ) -> dict[str, object]:
        """从真实网格数据构建温度 GeoJSON。

        Args:
            grid_data: fetch_grid_forecast() 返回的网格数据
            layer_id: 图层类型（如 temperature, temperature-80m 等）

        Returns:
            GeoJSON FeatureCollection（Polygon 网格）
        """
        grid = grid_data["grid"]
        current = grid_data["data"]["current"]

        rows, cols = grid["rows"], grid["cols"]
        lats = grid["lats"]
        lons = grid["lons"]
        features = []

        # 根据 layer_id 解析高度后缀
        height_suffix = "2m"
        if layer_id and layer_id.startswith("temperature-"):
            height_suffix = layer_id.split("-", 1)[-1]  # "80m" / "120m" / "180m"

        temp_attr = f"temperature_{height_suffix}"
        api_temp_attr = temp_attr.replace("-", "_")

        # 从 API 响应中提取数据
        temp_values = current.get(api_temp_attr, current.get("temperature_2m", []))

        lat_step = (grid["bbox"]["north"] - grid["bbox"]["south"]) / rows
        lon_step = (grid["bbox"]["east"] - grid["bbox"]["west"]) / cols

        for i in range(rows):
            for j in range(cols):
                idx = i * cols + j
                if idx >= len(temp_values):
                    continue

                south = grid["bbox"]["south"] + i * lat_step
                north = south + lat_step
                west = grid["bbox"]["west"] + j * lon_step
                east = west + lon_step

                value = temp_values[idx]

                features.append({
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
                        temp_attr: round(value, 2) if value is not None else 0,
                        "height": height_suffix,
                        "unit": "C",
                        "row": i,
                        "col": j,
                    }
                })

        return {"type": "FeatureCollection", "features": features}

    def build_precipitation_geojson_from_grid(
        self,
        grid_data: dict[str, Any],
        layer_id: str,
    ) -> dict[str, object]:
        """从真实网格数据构建降水 GeoJSON。

        Args:
            grid_data: fetch_grid_forecast() 返回的网格数据
            layer_id: 图层类型（precipitation）

        Returns:
            GeoJSON FeatureCollection（Polygon 网格，仅降水 > 0.1mm 的区域）
        """
        grid = grid_data["grid"]
        current = grid_data["data"]["current"]

        rows, cols = grid["rows"], grid["cols"]
        lats = grid["lats"]
        lons = grid["lons"]
        features = []

        # 从 API 响应中提取数据
        precip_values = current.get("precipitation", [])

        lat_step = (grid["bbox"]["north"] - grid["bbox"]["south"]) / rows
        lon_step = (grid["bbox"]["east"] - grid["bbox"]["west"]) / cols

        for i in range(rows):
            for j in range(cols):
                idx = i * cols + j
                if idx >= len(precip_values):
                    continue

                value = precip_values[idx]
                if value is None or value < 0.1:
                    continue

                south = grid["bbox"]["south"] + i * lat_step
                north = south + lat_step
                west = grid["bbox"]["west"] + j * lon_step
                east = west + lon_step

                features.append({
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
                        "row": i,
                        "col": j,
                    }
                })

        return {"type": "FeatureCollection", "features": features}

    def build_humidity_geojson_from_grid(
        self,
        grid_data: dict[str, Any],
        layer_id: str,
    ) -> dict[str, object]:
        """从真实网格数据构建湿度 GeoJSON。

        Args:
            grid_data: fetch_grid_forecast() 返回的网格数据
            layer_id: 图层类型（humidity）

        Returns:
            GeoJSON FeatureCollection（Polygon 网格）
        """
        grid = grid_data["grid"]
        current = grid_data["data"]["current"]

        rows, cols = grid["rows"], grid["cols"]
        features = []

        # 从 API 响应中提取数据
        humidity_values = current.get("relative_humidity_2m", [])

        lat_step = (grid["bbox"]["north"] - grid["bbox"]["south"]) / rows
        lon_step = (grid["bbox"]["east"] - grid["bbox"]["west"]) / cols

        for i in range(rows):
            for j in range(cols):
                idx = i * cols + j
                if idx >= len(humidity_values):
                    continue

                value = humidity_values[idx]

                south = grid["bbox"]["south"] + i * lat_step
                north = south + lat_step
                west = grid["bbox"]["west"] + j * lon_step
                east = west + lon_step

                features.append({
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
                        "relative_humidity_2m": round(value, 2) if value is not None else 0,
                        "unit": "%",
                        "row": i,
                        "col": j,
                    }
                })

        return {"type": "FeatureCollection", "features": features}

    def build_pressure_geojson_from_grid(
        self,
        grid_data: dict[str, Any],
        layer_id: str,
    ) -> dict[str, object]:
        """从真实网格数据构建气压 GeoJSON。

        Args:
            grid_data: fetch_grid_forecast() 返回的网格数据
            layer_id: 图层类型（pressure）

        Returns:
            GeoJSON FeatureCollection（Polygon 网格）
        """
        grid = grid_data["grid"]
        current = grid_data["data"]["current"]

        rows, cols = grid["rows"], grid["cols"]
        features = []

        # 从 API 响应中提取数据
        pressure_values = current.get("pressure_msl", [])

        lat_step = (grid["bbox"]["north"] - grid["bbox"]["south"]) / rows
        lon_step = (grid["bbox"]["east"] - grid["bbox"]["west"]) / cols

        for i in range(rows):
            for j in range(cols):
                idx = i * cols + j
                if idx >= len(pressure_values):
                    continue

                value = pressure_values[idx]

                south = grid["bbox"]["south"] + i * lat_step
                north = south + lat_step
                west = grid["bbox"]["west"] + j * lon_step
                east = west + lon_step

                features.append({
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
                        "pressure_msl": round(value, 2) if value is not None else 0,
                        "unit": "hPa",
                        "row": i,
                        "col": j,
                    }
                })

        return {"type": "FeatureCollection", "features": features}

    def build_visibility_geojson_from_grid(
        self,
        grid_data: dict[str, Any],
        layer_id: str,
    ) -> dict[str, object]:
        """从真实网格数据构建能见度 GeoJSON。

        Args:
            grid_data: fetch_grid_forecast() 返回的网格数据
            layer_id: 图层类型（visibility）

        Returns:
            GeoJSON FeatureCollection（Polygon 网格）
        """
        grid = grid_data["grid"]
        current = grid_data["data"]["current"]

        rows, cols = grid["rows"], grid["cols"]
        features = []

        # 从 API 响应中提取数据
        visibility_values = current.get("visibility", [])

        lat_step = (grid["bbox"]["north"] - grid["bbox"]["south"]) / rows
        lon_step = (grid["bbox"]["east"] - grid["bbox"]["west"]) / cols

        for i in range(rows):
            for j in range(cols):
                idx = i * cols + j
                if idx >= len(visibility_values):
                    continue

                value = visibility_values[idx]

                south = grid["bbox"]["south"] + i * lat_step
                north = south + lat_step
                west = grid["bbox"]["west"] + j * lon_step
                east = west + lon_step

                features.append({
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
                        "visibility": round(value, 2) if value is not None else 0,
                        "unit": "m",
                        "row": i,
                        "col": j,
                    }
                })

        return {"type": "FeatureCollection", "features": features}

    def _resolve_render_bbox(
        self,
        payload: WorkflowSubmitRequest,
        latitude: float,
        longitude: float,
    ) -> BoundingBox:
        # [WeatherEngine] 调试：打印 bbox 解析过程
        vp_bbox = payload.map_context.viewport_bbox
        if vp_bbox is not None:
            logger.info(
                "[WeatherEngine] _resolve_render_bbox: source=viewport_bbox bbox=(%s,%s,%s,%s) span=%.2fx%.2f",
                vp_bbox.west, vp_bbox.south, vp_bbox.east, vp_bbox.north,
                vp_bbox.east - vp_bbox.west, vp_bbox.north - vp_bbox.south,
            )
            return vp_bbox
        if payload.spatial_filter and payload.spatial_filter.bbox is not None:
            bbox = payload.spatial_filter.bbox
            logger.info("[WeatherEngine] _resolve_render_bbox: source=spatial_filter bbox=(%s,%s,%s,%s)", bbox.west, bbox.south, bbox.east, bbox.north)
            return bbox
        west = longitude - 1.6
        east = longitude + 1.6
        south = latitude - 1.2
        north = latitude + 1.2
        # 日界线 wraparound：longitude≈180 时 east 会 >180，需折回 [-180, 180]
        while west < -180:
            west += 360
        while east > 180:
            east -= 360
        # 极地纬度 clamp：latitude≈90 时 north 会 >90，需限制到 [-90, 90]
        north = min(90, max(-90, north))
        south = min(90, max(-90, south))
        logger.info("[WeatherEngine] _resolve_render_bbox: source=fallback(center±1.6/1.2) bbox=(%s,%s,%s,%s) center=(%s,%s)", west, south, east, north, longitude, latitude)
        return BoundingBox(
            west=west,
            south=south,
            east=east,
            north=north,
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

    def _humidity_value_for_location(
        self,
        *,
        base_humidity: float,
        center_lat: float,
        center_lon: float,
        lat: float,
        lon: float,
        lat_span: float,
        lon_span: float,
    ) -> float:
        # 简单的经纬度扰动模型，相对湿度限制在 0~100%
        lat_norm = (lat - center_lat) / lat_span
        lon_norm = (lon - center_lon) / lon_span
        noise = (math.sin(lat_norm * math.pi) * 0.5 + math.cos(lon_norm * math.pi) * 0.5) * 5.0
        return max(0.0, min(100.0, base_humidity + noise))

    def _pressure_value_for_location(
        self,
        *,
        base_pressure: float,
        center_lat: float,
        center_lon: float,
        lat: float,
        lon: float,
        lat_span: float,
        lon_span: float,
    ) -> float:
        # 中心气压偏高、外围略低，模拟低压系统扰动
        lat_norm = (lat - center_lat) / lat_span
        lon_norm = (lon - center_lon) / lon_span
        radial = math.sqrt(lat_norm * lat_norm + lon_norm * lon_norm)
        noise = -radial * 3.2 + math.sin(lon_norm * math.pi) * 1.5 - math.cos(lat_norm * math.pi) * 1.2
        return base_pressure + noise

    def _visibility_value_for_location(
        self,
        *,
        base_visibility: float,
        center_lat: float,
        center_lon: float,
        lat: float,
        lon: float,
        lat_span: float,
        lon_span: float,
    ) -> float:
        # 能见度向边缘衰减，模拟局部能见度差异
        lat_norm = (lat - center_lat) / lat_span
        lon_norm = (lon - center_lon) / lon_span
        radial = math.sqrt(lat_norm * lat_norm + lon_norm * lon_norm)
        noise = -radial * 1200.0 + math.sin((lat_norm + lon_norm) * math.pi) * 600.0
        return max(0.0, base_visibility + noise)

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
