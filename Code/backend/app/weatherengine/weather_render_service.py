"""L3 抽取：天气渲染原语方法集合。

从 WeatherEngineService 中提取的 GeoJSON/COG 渲染方法。
作为 mixin 类，被 WeatherEngineService 继承以保持 API 兼容性。
"""

from __future__ import annotations

import importlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from uuid import uuid4

from app.core.config import settings
from app.services.geo_math import grid_size_from_span
from app.services.result_storage import result_storage_service
from app.weatherengine.weather_value_utils import (
    humidity_value_for_location,
    precipitation_value_for_location,
    pressure_value_for_location,
    temperature_value_for_location,
    visibility_value_for_location,
    wind_value_for_location,
)
from shared.contracts.api_contracts import (
    BoundingBox,
    ResultKind,
    WeatherPointResponse,
    WorkflowResultReference,
    WorkflowSubmitRequest,
)

logger = logging.getLogger(__name__)


class WeatherRenderMixin:
    """L3 抽取：天气渲染原语方法集合。

    从 WeatherEngineService 中提取的 GeoJSON/COG 渲染方法。
    作为 mixin 类，被 WeatherEngineService 继承以保持 API 兼容性。
    """

    def _build_geojson_from_grid(
        self, *, grid_data: dict[str, Any], layer_id: str
    ) -> dict[str, object]:
        if layer_id == "precipitation":
            return self.build_precipitation_geojson_from_grid(grid_data, layer_id)
        if layer_id == "humidity":
            return self.build_humidity_geojson_from_grid(grid_data, layer_id)
        if layer_id == "pressure":
            return self.build_pressure_geojson_from_grid(grid_data, layer_id)
        if layer_id == "visibility":
            return self.build_visibility_geojson_from_grid(grid_data, layer_id)
        if layer_id == "cloud-cover":
            return self.build_cloud_cover_geojson_from_grid(grid_data, layer_id)
        if layer_id == "dewpoint":
            return self.build_dewpoint_geojson_from_grid(grid_data, layer_id)
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
        from app.weatherengine.layer_outputs import (
            get_strategy as _get_layer_output_strategy,
        )

        point_feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [weather.longitude, weather.latitude],
            },
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
        bbox = None  # 由策略填充，公共尾部用于 cog_bbox 渲染

        # Sprint 3: 查询 layer_outputs 策略注册表（6 个 layer_id 均已注册）。
        # 策略返回 LayerOutputResult 中间产物，service 负责公共前后逻辑（无行为变更）。
        _strategy = _get_layer_output_strategy(spec.layer_id)
        if _strategy is not None:
            _result = _strategy.build(
                service=self,
                run_id=run_id,
                payload=payload,
                requested_at=requested_at,
                weather=weather,
                spec=spec,
                metric_value=metric_value,
            )
            if _result is not None:
                geojson_ref = _result.geojson_ref
                cog_ref = _result.cog_ref
                bbox = _result.bbox
                diagnostics.extend(_result.diagnostics)
                if geojson_ref is not None:
                    result_refs.append(geojson_ref)
                if cog_ref is not None:
                    result_refs.append(cog_ref)

        # Sprint 3: 原 6 个 if/elif 分支（wind-field/temperature/precipitation/
        # humidity/pressure/visibility）已迁移到 layer_outputs 策略类，由上方
        # _get_layer_output_strategy(spec.layer_id) 查询并构建。下方公共后部
        # （result_refs.append weather-layer render hint + log + return）保持不变。

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
                        "geojson_url": geojson_ref.resource_url
                        if geojson_ref
                        else None,
                        "cog_url": cog_ref.resource_url if cog_ref else None,
                        "cog_preview_url": f"/artifacts/{cog_ref.resource_key}/preview.png"
                        if cog_ref and cog_ref.resource_key
                        else None,
                        "cog_bbox": {
                            "west": bbox.west,
                            "south": bbox.south,
                            "east": bbox.east,
                            "north": bbox.north,
                            "crs": bbox.crs,
                        }
                        if (
                            cog_ref
                            and (
                                spec.layer_id.startswith("temperature")
                                or spec.layer_id == "precipitation"
                            )
                        )
                        else None,
                    },
                },
                updated_at=requested_at,
            )
        )
        logger.info(
            "[WindDebug] map_layer result_ref created: geojson_url=%s cog_url=%s cog_preview=%s",
            geojson_ref.resource_url if geojson_ref else None,
            cog_ref.resource_url if cog_ref else None,
            f"/artifacts/{cog_ref.resource_key}/preview.png"
            if cog_ref and cog_ref.resource_key
            else None,
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
        resolved_rows = (
            rows
            if rows is not None
            else max(24, min(180, grid_size_from_span(lat_span, 0.35)))
        )
        resolved_cols = (
            cols
            if cols is not None
            else max(32, min(360, grid_size_from_span(lon_span, 0.35)))
        )
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
        base_speed = (
            getattr(weather.current, speed_attr, None)
            or weather.current.wind_speed_10m
            or 0.0
        )
        base_direction = (
            getattr(weather.current, direction_attr, None)
            or weather.current.wind_direction_10m
            or 0.0
        )
        for row in range(resolved_rows):
            for col in range(resolved_cols):
                lat = bbox.south + (row + 0.5) * lat_step
                lon = bbox.west + (col + 0.5) * lon_step
                speed, direction = wind_value_for_location(
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
            height_suffix = layer_id.split("-", 2)[
                -1
            ]  # "80m" / "120m" / "180m" / "850hPa" 等

        speed_attr = f"wind_speed_{height_suffix}"
        direction_attr = f"wind_direction_{height_suffix}"

        # Open-Meteo API 字段名转换（API 使用下划线）
        api_speed_attr = speed_attr.replace("-", "_")
        api_direction_attr = direction_attr.replace("-", "_")

        # 从 API 响应中提取数据（数组格式，按索引对应）
        speed_values = list(current.get(api_speed_attr) or [])
        direction_values = list(current.get(api_direction_attr) or [])

        # 轮毂高度缺测：用 10m + Hellmann 幂律外推（与 field_mapping 网格补全一致）
        speed_valid = sum(1 for v in speed_values if v is not None)
        if speed_valid == 0 and height_suffix.endswith("m") and height_suffix != "10m":
            try:
                target_h = float(height_suffix.rstrip("m"))
            except ValueError:
                target_h = 0.0
            base_speed = current.get("wind_speed_10m") or []
            base_dir = current.get("wind_direction_10m") or []
            if target_h > 0 and any(v is not None for v in base_speed):
                from app.weatherengine.field_mapping import (
                    extrapolate_wind_speed_power_law,
                )

                speed_values = [
                    extrapolate_wind_speed_power_law(
                        base_speed[i] if i < len(base_speed) else None,
                        target_height_m=target_h,
                    )
                    for i in range(len(base_speed))
                ]
                if not any(v is not None for v in direction_values):
                    direction_values = list(base_dir)
                logger.info(
                    "[WeatherEngine] build_wind_geojson_from_grid: extrapolated %s from 10m layer=%s",
                    api_speed_attr,
                    layer_id,
                )

        if not speed_values:
            speed_values = list(current.get("wind_speed_10m") or [])
        if not direction_values:
            direction_values = list(current.get("wind_direction_10m") or [])

        speed_valid = sum(1 for v in speed_values if v is not None)
        dir_valid = sum(1 for v in direction_values if v is not None)
        if speed_valid == 0:
            # 禁止随机伪造气象场：无数据就返回空要素（与温度层跳过 null 一致）
            logger.warning(
                "[WeatherEngine] build_wind_geojson_from_grid: no usable wind speed "
                "layer=%s speed_values=%d dir_values=%d — empty FeatureCollection",
                layer_id,
                len(speed_values),
                len(direction_values),
            )
            return {"type": "FeatureCollection", "features": []}
        if dir_valid == 0:
            logger.warning(
                "[WeatherEngine] build_wind_geojson_from_grid: wind direction missing "
                "layer=%s — features will use direction=0 (no random fill)",
                layer_id,
            )

        # [WeatherEngine] 调试：打印网格数据概要
        speed_sample = [
            speed_values[i]
            for i in range(min(5, len(speed_values)))
            if speed_values[i] is not None
        ]
        dir_sample = [
            direction_values[i]
            for i in range(min(5, len(direction_values)))
            if direction_values[i] is not None
        ]
        logger.info(
            "[WeatherEngine] build_wind_geojson_from_grid: layer=%s rows=%d cols=%d total=%d speed_attr=%s(speed_values=%d, sample=%s) dir_attr=%s(dir_values=%d, sample=%s) lats=[%.4f..%.4f] lons=[%.4f..%.4f]",
            layer_id,
            rows,
            cols,
            rows * cols,
            api_speed_attr,
            len(speed_values),
            speed_sample,
            api_direction_attr,
            len(direction_values),
            dir_sample,
            lats[0] if lats else 0,
            lats[-1] if lats else 0,
            lons[0] if lons else 0,
            lons[-1] if lons else 0,
        )

        for i in range(rows):
            for j in range(cols):
                idx = i * cols + j
                lat = lats[i] if i < len(lats) else 0
                lon = lons[j] if j < len(lons) else 0

                speed = speed_values[idx] if idx < len(speed_values) else None
                if speed is None:
                    continue
                direction = (
                    direction_values[idx] if idx < len(direction_values) else None
                )
                if direction is None:
                    direction = 0.0

                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": {
                            speed_attr: round(float(speed), 2),
                            direction_attr: round(float(direction), 1),
                            "height": height_suffix,
                            "unit": "m/s",
                            "row": i,
                            "col": j,
                        },
                    }
                )

        logger.info(
            "[WeatherEngine] build_wind_geojson_from_grid: generated %d features, first=(%.4f,%.4f) last=(%.4f,%.4f)",
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
        resolved_rows = (
            rows
            if rows is not None
            else max(18, min(120, grid_size_from_span(lat_span, 0.4)))
        )
        resolved_cols = (
            cols
            if cols is not None
            else max(18, min(120, grid_size_from_span(lon_span, 0.4)))
        )
        lat_step = lat_span / resolved_rows
        lon_step = lon_span / resolved_cols
        # 根据 layer_id 高度后缀读取对应字段：temperature → 2m，temperature-80m → 80m，…
        # 回退到 temperature_2m，保证旧调用方兼容
        layer_id = weather.layer_id
        height_suffix = "2m"
        if layer_id and layer_id.startswith("temperature-"):
            height_suffix = layer_id.split("-", 1)[-1]  # "80m" / "120m" / "180m"
        temp_attr = f"temperature_{height_suffix}"
        base_temp = (
            getattr(weather.current, temp_attr, None)
            or weather.current.temperature_2m
            or 0.0
        )
        for row in range(resolved_rows):
            for col in range(resolved_cols):
                south = bbox.south + row * lat_step
                north = south + lat_step
                west = bbox.west + col * lon_step
                east = west + lon_step
                cell_lat = south + lat_step / 2
                cell_lon = west + lon_step / 2
                value = temperature_value_for_location(
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
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
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
            raster_writer_module = importlib.import_module(
                "algorithms.providers.Python.publish.raster_writer"
            )
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
            base_temp = (
                getattr(weather.current, temp_attr, None)
                or weather.current.temperature_2m
                or 0.0
            )
            for row in range(rows):
                lat = bbox.north - ((row + 0.5) / rows) * (bbox.north - bbox.south)
                for col in range(cols):
                    lon = bbox.west + ((col + 0.5) / cols) * (bbox.east - bbox.west)
                    array[row, col] = temperature_value_for_location(
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
        transform = transform_module.from_bounds(
            bbox.west, bbox.south, bbox.east, bbox.north, cols, rows
        )
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
        diagnostics.append(
            f"temperature_cog_size_bytes={cog_ref.resource_size_bytes or 0}"
        )
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
        resolved_rows = (
            rows
            if rows is not None
            else max(18, min(120, grid_size_from_span(lat_span, 0.4)))
        )
        resolved_cols = (
            cols
            if cols is not None
            else max(18, min(120, grid_size_from_span(lon_span, 0.4)))
        )
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
                value = precipitation_value_for_location(
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
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
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
            raster_writer_module = importlib.import_module(
                "algorithms.providers.Python.publish.raster_writer"
            )
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
                    array[row, col] = precipitation_value_for_location(
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
        transform = transform_module.from_bounds(
            bbox.west, bbox.south, bbox.east, bbox.north, cols, rows
        )
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
        diagnostics.append(
            f"precipitation_cog_size_bytes={cog_ref.resource_size_bytes or 0}"
        )
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
        resolved_rows = (
            rows
            if rows is not None
            else max(18, min(120, grid_size_from_span(lat_span, 0.4)))
        )
        resolved_cols = (
            cols
            if cols is not None
            else max(18, min(120, grid_size_from_span(lon_span, 0.4)))
        )
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
                value = humidity_value_for_location(
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
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
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
        resolved_rows = (
            rows
            if rows is not None
            else max(18, min(120, grid_size_from_span(lat_span, 0.4)))
        )
        resolved_cols = (
            cols
            if cols is not None
            else max(18, min(120, grid_size_from_span(lon_span, 0.4)))
        )
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
                value = pressure_value_for_location(
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
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
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
        resolved_rows = (
            rows
            if rows is not None
            else max(18, min(120, grid_size_from_span(lat_span, 0.4)))
        )
        resolved_cols = (
            cols
            if cols is not None
            else max(18, min(120, grid_size_from_span(lon_span, 0.4)))
        )
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
                value = visibility_value_for_location(
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
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
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
        features = []

        # 根据 layer_id 解析高度后缀
        height_suffix = "2m"
        if layer_id and layer_id.startswith("temperature-"):
            height_suffix = layer_id.split("-", 1)[-1]  # "80m" / "120m" / "180m"

        temp_attr = f"temperature_{height_suffix}"
        api_temp_attr = temp_attr.replace("-", "_")

        # 从 API 响应中提取数据
        temp_values = current.get(api_temp_attr, current.get("temperature_2m", []))
        if not isinstance(temp_values, list):
            temp_values = []

        lat_step = (grid["bbox"]["north"] - grid["bbox"]["south"]) / max(rows, 1)
        lon_step = (grid["bbox"]["east"] - grid["bbox"]["west"]) / max(cols, 1)

        for i in range(rows):
            for j in range(cols):
                idx = i * cols + j
                if idx >= len(temp_values):
                    continue

                value = temp_values[idx]
                if value is None:
                    continue
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue

                south = grid["bbox"]["south"] + i * lat_step
                north = south + lat_step
                west = grid["bbox"]["west"] + j * lon_step
                east = west + lon_step

                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
                        },
                        "properties": {
                            temp_attr: round(numeric, 2),
                            "height": height_suffix,
                            "unit": "C",
                            "row": i,
                            "col": j,
                        },
                    }
                )

        if not features:
            logger.warning(
                "[WeatherEngine] build_temperature_geojson_from_grid: empty features "
                "layer=%s rows=%d cols=%d temp_len=%d attr=%s",
                layer_id,
                rows,
                cols,
                len(temp_values),
                api_temp_attr,
            )

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

                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
                        },
                        "properties": {
                            "precipitation": round(value, 2),
                            "unit": "mm",
                            "row": i,
                            "col": j,
                        },
                    }
                )

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

                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
                        },
                        "properties": {
                            "relative_humidity_2m": round(value, 2)
                            if value is not None
                            else 0,
                            "unit": "%",
                            "row": i,
                            "col": j,
                        },
                    }
                )

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

                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
                        },
                        "properties": {
                            "pressure_msl": round(value, 2) if value is not None else 0,
                            "unit": "hPa",
                            "row": i,
                            "col": j,
                        },
                    }
                )

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

                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
                        },
                        "properties": {
                            "visibility": round(value, 2) if value is not None else 0,
                            "unit": "m",
                            "row": i,
                            "col": j,
                        },
                    }
                )

        return {"type": "FeatureCollection", "features": features}

    def build_cloud_cover_geojson_from_grid(
        self,
        grid_data: dict[str, Any],
        layer_id: str,
    ) -> dict[str, object]:
        """从真实网格数据构建云量 GeoJSON。

        Args:
            grid_data: fetch_grid_forecast() 返回的网格数据
            layer_id: 图层类型（cloud-cover）

        Returns:
            GeoJSON FeatureCollection（Polygon 网格，0~100%）
        """
        grid = grid_data["grid"]
        current = grid_data["data"]["current"]

        rows, cols = grid["rows"], grid["cols"]
        features = []

        # 从 API 响应中提取数据
        cloud_cover_values = current.get("cloud_cover", [])

        lat_step = (grid["bbox"]["north"] - grid["bbox"]["south"]) / rows
        lon_step = (grid["bbox"]["east"] - grid["bbox"]["west"]) / cols

        for i in range(rows):
            for j in range(cols):
                idx = i * cols + j
                if idx >= len(cloud_cover_values):
                    continue

                value = cloud_cover_values[idx]

                south = grid["bbox"]["south"] + i * lat_step
                north = south + lat_step
                west = grid["bbox"]["west"] + j * lon_step
                east = west + lon_step

                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
                        },
                        "properties": {
                            "cloud_cover": round(value, 2) if value is not None else 0,
                            "unit": "%",
                            "row": i,
                            "col": j,
                        },
                    }
                )

        return {"type": "FeatureCollection", "features": features}

    def build_dewpoint_geojson_from_grid(
        self,
        grid_data: dict[str, Any],
        layer_id: str,
    ) -> dict[str, object]:
        """从真实网格数据构建露点温度 GeoJSON。

        Args:
            grid_data: fetch_grid_forecast() 返回的网格数据
            layer_id: 图层类型（dewpoint）

        Returns:
            GeoJSON FeatureCollection（Polygon 网格）
        """
        grid = grid_data["grid"]
        current = grid_data["data"]["current"]

        rows, cols = grid["rows"], grid["cols"]
        features = []

        # 从 API 响应中提取数据
        dewpoint_values = current.get("dew_point_2m", [])

        lat_step = (grid["bbox"]["north"] - grid["bbox"]["south"]) / rows
        lon_step = (grid["bbox"]["east"] - grid["bbox"]["west"]) / cols

        for i in range(rows):
            for j in range(cols):
                idx = i * cols + j
                if idx >= len(dewpoint_values):
                    continue

                value = dewpoint_values[idx]
                if value is None:
                    continue

                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue

                south = grid["bbox"]["south"] + i * lat_step
                north = south + lat_step
                west = grid["bbox"]["west"] + j * lon_step
                east = west + lon_step

                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
                        },
                        "properties": {
                            "dew_point_2m": round(numeric, 2),
                            "unit": "C",
                            "row": i,
                            "col": j,
                        },
                    }
                )

        return {"type": "FeatureCollection", "features": features}

    def build_scalar_geojson_from_grid(
        self,
        grid_data: dict[str, Any],
        *,
        metric_key: str,
        unit: str,
    ) -> dict[str, object]:
        """Build polygon GeoJSON from a single current metric on an OM-style grid."""
        grid = grid_data["grid"]
        current = grid_data["data"]["current"]
        rows, cols = grid["rows"], grid["cols"]
        values = current.get(metric_key, [])
        features: list[dict[str, object]] = []
        lat_step = (grid["bbox"]["north"] - grid["bbox"]["south"]) / rows
        lon_step = (grid["bbox"]["east"] - grid["bbox"]["west"]) / cols
        for i in range(rows):
            for j in range(cols):
                idx = i * cols + j
                if idx >= len(values):
                    continue
                value = values[idx]
                south = grid["bbox"]["south"] + i * lat_step
                north = south + lat_step
                west = grid["bbox"]["west"] + j * lon_step
                east = west + lon_step
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
                        },
                        "properties": {
                            metric_key: round(value, 2) if value is not None else 0,
                            "unit": unit,
                            "row": i,
                            "col": j,
                        },
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    def build_scalar_geojson_from_point(
        self,
        weather: WeatherPointResponse,
        bbox: BoundingBox,
        *,
        metric_key: str,
        unit: str,
        base_value: float,
        rows: int | None = None,
        cols: int | None = None,
    ) -> dict[str, object]:
        """Fallback scalar field from a single point (gentle spatial variation)."""
        features: list[dict[str, object]] = []
        lat_span = max(0.1, bbox.north - bbox.south)
        lon_span = max(0.1, bbox.east - bbox.west)
        resolved_rows = (
            rows
            if rows is not None
            else max(18, min(120, grid_size_from_span(lat_span, 0.4)))
        )
        resolved_cols = (
            cols
            if cols is not None
            else max(18, min(120, grid_size_from_span(lon_span, 0.4)))
        )
        lat_step = lat_span / resolved_rows
        lon_step = lon_span / resolved_cols
        for row in range(resolved_rows):
            for col in range(resolved_cols):
                south = bbox.south + row * lat_step
                north = south + lat_step
                west = bbox.west + col * lon_step
                east = west + lon_step
                cell_lat = south + lat_step / 2
                cell_lon = west + lon_step / 2
                # Reuse humidity-style soft falloff for any scalar point fallback
                value = humidity_value_for_location(
                    base_humidity=base_value,
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
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
                        },
                        "properties": {
                            metric_key: round(value, 2),
                            "unit": unit,
                            "row": row,
                            "col": col,
                        },
                    }
                )
        return {"type": "FeatureCollection", "features": features}
