from __future__ import annotations

import math
from datetime import datetime, UTC
from typing import Any
import logging
from urllib.error import HTTPError, URLError
from uuid import uuid4

from app.core.config import settings
from app.weatherengine.default_model import weather_default_model
from app.services.api_config import api_config_manager, ApiProvider, DataType
from app.services.effective_config import (
    get_weather_cache_ttl_seconds,
    get_weather_refresh_forecast_hours,
)
from app.services.workflow_execution import WorkflowExecutionResult
from app.weatherengine.constants import DEFAULT_LAYER_ID, WEATHER_LAYER_SPECS
from app.weatherengine.nodes._utils import compute_dynamic_resolution
from app.weatherengine.weather_render_service import WeatherRenderMixin
from app.weatherengine.weather_value_utils import (
    as_int,
    as_string,
    coerce_datetime,
    pick_series_value,
    resolve_forecast_hours,
    resolve_point,
    resolve_render_bbox,
)
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


class WeatherEngineService(WeatherRenderMixin):
    """天气引擎服务 — 提供点查询、工作流执行与渲染原语（via mixin）。

    L3 重构：渲染方法（build_*_geojson）已抽取到 WeatherRenderMixin，
    工具函数已抽取到 weather_value_utils。

    - 本类负责：点查询（get_point_weather）、forecast 解析、工作流执行。
    - 渲染原语：通过 WeatherRenderMixin 继承，外部调用方（tile_service、
      layer_outputs 策略）仍可通过 self.build_*_geojson 访问。
    - REST 端点 /weather/point 直接调用本类 get_point_weather。
    """

    def __init__(self) -> None:
        self._active_provider = ApiProvider.OPEN_METEO

    def get_active_provider(self) -> ApiProvider:
        """获取当前活跃的天气数据 Provider。"""
        # 优先使用 api_config_manager 中配置的天气 Provider
        # M15 兼容：get_best_available 返回 ApiConfig 对象，不是字典
        best = api_config_manager.get_best_available(
            required_capabilities={DataType.WEATHER}
        )
        if best:
            return best.provider
        return self._active_provider

    def supports(self, payload: WorkflowSubmitRequest) -> bool:
        # 与 weather_bridge / provider_workflow 对齐 enabled flag：
        # False 时不再作为 layer-based fallback 接管 workflow-runs
        # （收敛到 weather_bridge / 瓦片主路径，见工程决策纪要 §5）
        if not settings.weather_engine_fallback_enabled:
            return False
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
        provider_id: str | None = None,
    ) -> WeatherPointResponse:
        spec = WEATHER_LAYER_SPECS.get(layer_id)
        if spec is None:
            raise ValueError(f"Unsupported weather layer: {layer_id}")

        resolved_model = model or spec.preferred_model or weather_default_model()

        from app.weatherengine.fetch_gateway import (
            WeatherProviderUnavailableError,
            fetch_point_forecast,
        )

        try:
            payload, cache_status, provider_label = fetch_point_forecast(
                layer_id=layer_id,
                latitude=latitude,
                longitude=longitude,
                model=resolved_model,
                forecast_hours=forecast_hours,
                ttl_seconds=cache_ttl_seconds,
                layer_spec=spec,
                provider_id=provider_id,
            )
        except (HTTPError, URLError, WeatherProviderUnavailableError) as exc:
            sampled = self._try_point_from_tile_cache(
                layer_id=layer_id,
                latitude=latitude,
                longitude=longitude,
                resolved_model=resolved_model,
                forecast_hours=forecast_hours,
                place_name=place_name,
                provider_id=provider_id,
                spec=spec,
            )
            if sampled is not None:
                logger.warning(
                    "[WeatherEngine] point upstream unavailable (%s); using tile-cache sample",
                    exc,
                )
                return sampled
            raise

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

    def _try_point_from_tile_cache(
        self,
        *,
        layer_id: str,
        latitude: float,
        longitude: float,
        resolved_model: str,
        forecast_hours: int,
        place_name: str | None,
        provider_id: str | None,
        spec,
    ) -> WeatherPointResponse | None:
        """上游点查失败时，从已加载瓦片缓存采样最近格点，保证点击仍有可读结果。"""
        try:
            from app.weatherengine.tile_service import get_weather_tile_service

            tile_svc = get_weather_tile_service()
            props = None
            for pid in (provider_id, "auto", None):
                props = tile_svc.sample_nearest_feature(
                    layer_id=layer_id,
                    latitude=latitude,
                    longitude=longitude,
                    model=resolved_model,
                    provider_id=pid,
                )
                if props:
                    break
        except Exception as exc:  # noqa: BLE001 — 降级路径不可再抛
            logger.debug("[WeatherEngine] tile-cache sample failed: %s", exc)
            return None
        if not props:
            return None

        current_fields: dict[str, Any] = {}
        for key, value in props.items():
            if key.startswith("_"):
                continue
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                current_fields[key] = float(value)

        metric = spec.primary_metric
        if metric not in current_fields:
            # 风场 GeoJSON 可能用 wind_speed_120m 等；尝试 height 后缀拼装
            height = props.get("height")
            if isinstance(height, str):
                speed_key = f"wind_speed_{height}"
                dir_key = f"wind_direction_{height}"
                if speed_key in props:
                    current_fields[speed_key] = props[speed_key]
                    current_fields.setdefault(metric, props[speed_key])
                if dir_key in props:
                    current_fields[dir_key] = props[dir_key]

        metric_value = current_fields.get(metric)
        summary = spec.summary_template.format(
            value=metric_value if metric_value is not None else "--",
            unit=spec.unit_label,
        )
        sample_note = (
            f"tile-cache sample @ "
            f"{props.get('_sample_lat', latitude):.3f},"
            f"{props.get('_sample_lon', longitude):.3f}"
        )
        return self.parse_forecast_to_point(
            payload={
                "timezone": None,
                "current": {
                    "time": datetime.now(UTC).isoformat(),
                    **current_fields,
                },
                "hourly": {"time": []},
                "model": resolved_model,
            },
            cache_status="tile-cache-sample",
            layer_id=layer_id,
            latitude=latitude,
            longitude=longitude,
            resolved_model=resolved_model,
            forecast_hours=forecast_hours,
            place_name=place_name,
            provider="tile-cache",
        ).model_copy(
            update={
                "summary": f"{summary}（{sample_note}）",
                "diagnostics": [
                    "provider=tile-cache",
                    f"layer_id={layer_id}",
                    sample_note,
                    "upstream point temporarily unavailable",
                ],
            },
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
        provider: str = "open-meteo-online",
    ) -> WeatherPointResponse:
        """M11 修复：将 forecast payload 解析为 WeatherPointResponse，无需再次调用 API。

        从 get_point_weather 提取，供 PointParseNode 消费上游 ForecastFetchNode 输出时复用。
        """
        spec = WEATHER_LAYER_SPECS.get(layer_id)
        if spec is None:
            raise ValueError(f"Unsupported weather layer: {layer_id}")

        current = payload.get("current") or {}
        hourly = payload.get("hourly") or {}
        # 点查链路复用瓦片链路的轮毂高度外推：本地代理（gfs）无 80/120/180m 风/温度
        # 真值时，从 10m 风/温度按 Hellmann 指数 / 环境递减率外推填入 current/hourly，
        # 避免 summary 显示 "--" 且 hourly 折线有数值（与瓦片渲染行为一致）。
        _extrapolate_hub_height_point(current, hourly, layer_id)
        hourly_times = hourly.get("time") or []
        hourly_rows: list[WeatherPointHourlyEntry] = []
        for index, time_value in enumerate(hourly_times[: max(1, forecast_hours)]):
            primary_value = pick_series_value(hourly, spec.primary_metric, index)
            hourly_rows.append(
                WeatherPointHourlyEntry(
                    time=coerce_datetime(time_value),
                    temperature_2m=pick_series_value(hourly, "temperature_2m", index),
                    precipitation=pick_series_value(hourly, "precipitation", index),
                    wind_speed_10m=pick_series_value(hourly, "wind_speed_10m", index),
                    primary_metric=spec.primary_metric,
                    primary_value=primary_value,
                )
            )
        # 气压层变量仅出现在 hourly 段，取首小时作为当前值
        # 当 spec 未请求气压层时这些字段保持 None
        pl_wind_speed_850 = pick_series_value(hourly, "wind_speed_850hPa", 0)
        pl_wind_direction_850 = pick_series_value(hourly, "wind_direction_850hPa", 0)
        pl_temperature_850 = pick_series_value(hourly, "temperature_850hPa", 0)
        pl_wind_speed_500 = pick_series_value(hourly, "wind_speed_500hPa", 0)
        pl_wind_direction_500 = pick_series_value(hourly, "wind_direction_500hPa", 0)
        pl_temperature_500 = pick_series_value(hourly, "temperature_500hPa", 0)
        pl_wind_speed_200 = pick_series_value(hourly, "wind_speed_200hPa", 0)
        pl_wind_direction_200 = pick_series_value(hourly, "wind_direction_200hPa", 0)
        pl_temperature_200 = pick_series_value(hourly, "temperature_200hPa", 0)

        # metric_value 优先从 current 取；open-meteo 当前段仅含 2m/10m 部分变量，
        # 其余（如 wind_speed_80m/120m/180m、temperature_80m/120m/180m）只能从 hourly[0] 取。
        # 气压层变量同列，已默认走 hourly[0]，此处统一回退（不再受 pressure_levels 门控限制）。
        metric_value = current.get(spec.primary_metric)
        if metric_value is None:
            metric_value = pick_series_value(hourly, spec.primary_metric, 0)
        summary = spec.summary_template.format(
            value=metric_value if metric_value is not None else "--",
            unit=spec.unit_label,
        )
        observation_time = coerce_datetime(current.get("time"))
        return WeatherPointResponse(
            provider=provider,
            model=resolved_model,
            resolved_model=str(payload.get("model"))
            if payload.get("model") is not None
            else None,
            layer_id=layer_id,
            latitude=latitude,
            longitude=longitude,
            place_name=place_name,
            timezone=payload.get("timezone"),
            fetched_at=datetime.now(UTC),
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
        """当上游天气 API 不可用时构建降级 WeatherPointResponse，保证网格渲染工作流可继续。"""
        logger.info(
            "[WeatherEngine] building fallback weather for layer=%s lat=%.4f lon=%.4f",
            layer_id,
            latitude,
            longitude,
        )
        return WeatherPointResponse(
            provider="unavailable",
            model=spec.default_model
            if hasattr(spec, "default_model")
            else "icon_seamless",
            resolved_model=None,
            layer_id=layer_id,
            latitude=latitude,
            longitude=longitude,
            place_name=place_name,
            timezone=None,
            fetched_at=datetime.now(UTC),
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
                "provider=unavailable",
                f"layer_id={layer_id}",
                "cache_status=fallback",
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
        layer_id = (
            payload.layer_id or payload.map_context.active_layer_id or DEFAULT_LAYER_ID
        )
        latitude, longitude, place_name = resolve_point(payload)
        forecast_hours = resolve_forecast_hours(payload)
        # [WeatherEngine] 调试：打印工作流入参
        vp_bbox = payload.map_context.viewport_bbox
        logger.info(
            "[WeatherEngine] execute: run_id=%s layer_id=%s lat=%s lon=%s place=%s forecast_hours=%s viewport_bbox=%s params=%s",
            run_id,
            layer_id,
            latitude,
            longitude,
            place_name,
            forecast_hours,
            f"({vp_bbox.west},{vp_bbox.south},{vp_bbox.east},{vp_bbox.north})"
            if vp_bbox
            else "None",
            {
                k: v
                for k, v in payload.parameters.items()
                if k in ("hour", "latitude", "longitude", "weather_model")
            },
        )
        spec = WEATHER_LAYER_SPECS[layer_id]
        try:
            weather = self.get_point_weather(
                layer_id=layer_id,
                latitude=latitude,
                longitude=longitude,
                model=as_string(payload.parameters.get("weather_model")),
                forecast_hours=forecast_hours,
                place_name=place_name,
                cache_ttl_seconds=as_int(payload.parameters.get("cache_ttl_seconds")),
            )
        except (HTTPError, URLError, OSError) as exc:
            # 点位天气 API 失败（如 429 限流）不应阻断网格渲染工作流
            logger.warning(
                "[WeatherEngine] point weather failed, continuing with fallback: %s",
                exc,
            )
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
                        "columns": [
                            "time",
                            "temperature_2m",
                            "precipitation",
                            "wind_speed_10m",
                        ],
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
                model=weather_default_model(),
                forecast_hours=get_weather_refresh_forecast_hours(),
                cache_ttl_seconds=get_weather_cache_ttl_seconds(),
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

    def _fetch_layer_grid_data(
        self, *, bbox: BoundingBox, spec
    ) -> tuple[dict[str, Any], str, float]:
        from app.weatherengine.fetch_gateway import fetch_grid_forecast

        resolution = compute_dynamic_resolution(bbox)
        grid_data, cache_status, _provider_id = fetch_grid_forecast(
            layer_id=spec.layer_id,
            bbox=bbox,
            resolution=resolution,
            layer_spec=spec,
        )
        return grid_data, cache_status, resolution

    def _resolve_render_bbox(
        self,
        payload: WorkflowSubmitRequest,
        latitude: float,
        longitude: float,
    ) -> BoundingBox:
        """L3: 委托到 weather_value_utils.resolve_render_bbox（layer_outputs 策略兼容）。"""
        return resolve_render_bbox(payload, latitude, longitude)


weather_engine_service = WeatherEngineService()


# 点查链路：层 → (目标高度 m, 类型)
_POINT_LAYER_TO_HEIGHT_M: dict[str, tuple[int, str]] = {
    "wind-field-80m": (80, "wind"),
    "wind-field-120m": (120, "wind"),
    "wind-field-180m": (180, "wind"),
    "temperature-80m": (80, "temperature"),
    "temperature-120m": (120, "temperature"),
    "temperature-180m": (180, "temperature"),
}


def _extrapolate_hub_height_point(
    current: dict[str, Any],
    hourly: dict[str, Any],
    layer_id: str,
) -> None:
    """点查链路的轮毂高度外推：与瓦片链路 ``ensure_hub_height_*_in_grid_arrays`` 对齐。

    本地代理（gfs）通常不提供 ``wind_speed_80m/120m/180m`` 与
    ``temperature_80m/120m/180m`` 真值，但提供 10m 风/2m 温度。
    当前段单值按 Hellmann 指数/环境递减率外推填充；hourly 段按各时刻独立外推。
    所有写入就地修改，原值为 None 才覆盖（保留模型直供数据）。
    """
    try:
        from app.weatherengine.field_mapping import (
            extrapolate_temperature_lapse_rate,
            extrapolate_wind_speed_power_law,
        )
    except Exception:  # noqa: BLE001 — 模块缺失不应阻塞点查
        return

    height_spec = _POINT_LAYER_TO_HEIGHT_M.get(layer_id)
    if height_spec is None:
        return
    target_h, kind = height_spec  # kind: 'wind' | 'temperature'

    if kind == "wind":
        speed_key = f"wind_speed_{int(target_h)}m"
        dir_key = f"wind_direction_{int(target_h)}m"
        base_speed = current.get("wind_speed_10m")
        if current.get(speed_key) is None and base_speed is not None:
            current[speed_key] = extrapolate_wind_speed_power_law(
                base_speed, target_height_m=float(target_h)
            )
        if (
            current.get(dir_key) is None
            and current.get("wind_direction_10m") is not None
        ):
            current[dir_key] = current.get("wind_direction_10m")

        # hourly 段：基序列可能整列为 null（gfs 代理无 10m 真值）；
        # 用 current 首值（若已外推）作常数回退，避免 hourly 折线全空。
        hourly_base = hourly.get("wind_speed_10m")
        hourly_speed = hourly.get(speed_key)
        if (
            not isinstance(hourly_base, list)
            or not hourly_base
            or not any(v is not None for v in hourly_base)
        ) and current.get(speed_key) is not None:
            hourly_base = [current.get("wind_speed_10m")] * len(
                hourly.get("time") or []
            )
        if (
            isinstance(hourly_base, list)
            and hourly_base
            and (
                not isinstance(hourly_speed, list)
                or not any(v is not None for v in hourly_speed)
            )
        ):
            hourly[speed_key] = [
                extrapolate_wind_speed_power_law(v, target_height_m=float(target_h))
                for v in hourly_base
            ]
            base_dir = hourly.get("wind_direction_10m") or current.get(
                "wind_direction_10m"
            )
            if isinstance(base_dir, (int, float)):
                hourly[dir_key] = [base_dir] * len(hourly_base)
    elif kind == "temperature":
        temp_key = f"temperature_{int(target_h)}m"
        base_temp = current.get("temperature_2m")
        if current.get(temp_key) is None and base_temp is not None:
            current[temp_key] = extrapolate_temperature_lapse_rate(
                base_temp, target_height_m=float(target_h)
            )
        hourly_base = hourly.get("temperature_2m")
        hourly_temp = hourly.get(temp_key)
        if (
            not isinstance(hourly_base, list)
            or not hourly_base
            or not any(v is not None for v in hourly_base)
        ) and current.get("temperature_2m") is not None:
            hourly_base = [current.get("temperature_2m")] * len(
                hourly.get("time") or []
            )
        if (
            isinstance(hourly_base, list)
            and hourly_base
            and (
                not isinstance(hourly_temp, list)
                or not any(v is not None for v in hourly_temp)
            )
        ):
            hourly[temp_key] = [
                extrapolate_temperature_lapse_rate(v, target_height_m=float(target_h))
                for v in hourly_base
            ]
