from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
import json
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
import logging

from app.core.config import settings
from app.weatherengine.constants import OPEN_METEO_BASE_URL, WeatherLayerSpec
from shared.contracts.api_contracts import BoundingBox

logger = logging.getLogger(__name__)


class OpenMeteoClient:
    def __init__(self, cache_root: str | Path | None = None) -> None:
        self._cache_root = Path(cache_root or settings.cache_dir) / "weatherengine"
        self._cache_root.mkdir(parents=True, exist_ok=True)

    def _read_cached_payload(
        self,
        cache_path: Path,
        *,
        now: datetime,
    ) -> tuple[dict[str, Any] | None, bool]:
        if not cache_path.exists():
            return None, False
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            expires_raw = cached.get("expires_at")
            if isinstance(expires_raw, (int, float)):
                expires_at = datetime.fromtimestamp(expires_raw, tz=timezone.utc)
            else:
                expires_at = datetime.fromisoformat(expires_raw)
            payload = cached.get("payload")
            if not isinstance(payload, dict):
                return None, False
            return payload, expires_at > now
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None, False

    def fetch_point_forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        layer_spec: WeatherLayerSpec,
        model: str,
        forecast_hours: int,
        ttl_seconds: int,
        pressure_levels: tuple[int, ...] | None = None,
    ) -> tuple[dict[str, Any], str]:
        cache_key = self._build_cache_key(
            latitude=latitude,
            longitude=longitude,
            layer_id=layer_spec.layer_id,
            model=model,
            forecast_hours=forecast_hours,
            pressure_levels=pressure_levels,
        )
        cache_path = self._cache_root / f"{cache_key}.json"
        now = datetime.now(timezone.utc)
        cached_payload, cache_is_fresh = self._read_cached_payload(cache_path, now=now)
        if cache_is_fresh and cached_payload is not None:
            return cached_payload, "hit"

        current_fields = sorted(set(layer_spec.current_fields))
        hourly_fields = sorted(set(layer_spec.hourly_fields))
        query_dict: dict[str, str] = {
            "latitude": f"{latitude:.4f}",
            "longitude": f"{longitude:.4f}",
            "timezone": "auto",
            "forecast_days": 2,
            "current": ",".join(current_fields),
            "hourly": ",".join(hourly_fields),
            "models": model,
        }
        # 气压层变量：layer_spec.notes 第三项可指定需要的气压层（如 850/700/500/200 hPa）
        if pressure_levels:
            query_dict["pressure_levels"] = ",".join(str(level) for level in pressure_levels)
        query = urlencode(query_dict)
        # HTTP 错误处理 + 瞬态失败重试：429/5xx 与 URLError 重试，4xx(非429) 立即抛出
        max_attempts = 5
        backoff = 2
        payload: dict[str, Any] | None = None
        for attempt in range(max_attempts):
            try:
                with urlopen(f"{OPEN_METEO_BASE_URL}?{query}", timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                if exc.code == 429:
                    # 限流：优先使用 stale cache，否则指数退避重试
                    if cached_payload is not None:
                        logger.warning(
                            "[OpenMeteoClient] point forecast 429 falling back to stale cache: lat=%.4f lon=%.4f layer=%s",
                            latitude, longitude, layer_spec.layer_id,
                        )
                        return cached_payload, "stale-hit"
                    retry_wait = max(backoff * 2, 5)
                    logger.info("[OpenMeteoClient] point forecast rate limited (429), waiting %ds... attempt=%d/%d", retry_wait, attempt + 1, max_attempts)
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(retry_wait)
                    backoff *= 2
                    continue
                if cached_payload is not None and exc.code >= 500:
                    logger.warning(
                        "[OpenMeteoClient] point forecast falling back to stale cache: code=%d lat=%.4f lon=%.4f layer=%s",
                        exc.code,
                        latitude,
                        longitude,
                        layer_spec.layer_id,
                    )
                    return cached_payload, "stale-hit"
                # 4xx 客户端错误（非 429）不重试，直接抛出
                if exc.code < 500 or attempt == max_attempts - 1:
                    raise
                time.sleep(backoff)
                backoff *= 2
            except URLError:
                if cached_payload is not None:
                    logger.warning(
                        "[OpenMeteoClient] point forecast falling back to stale cache after URL error: lat=%.4f lon=%.4f layer=%s",
                        latitude,
                        longitude,
                        layer_spec.layer_id,
                    )
                    return cached_payload, "stale-hit"
                if attempt == max_attempts - 1:
                    raise
                time.sleep(backoff)
                backoff *= 2
        # payload 在 break 后必已赋值；此处仅为类型检查兜底
        assert payload is not None

        # 原子写入缓存：先写临时文件再 rename，避免半写文件被并发读取
        cache_tmp_path = cache_path.with_suffix(".tmp")
        cache_tmp_path.parent.mkdir(parents=True, exist_ok=True)
        cache_tmp_path.write_text(
            json.dumps(
                {
                    "expires_at": datetime.fromtimestamp(now.timestamp() + max(60, ttl_seconds), tz=timezone.utc).isoformat(),
                    "payload": payload,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cache_tmp_path.replace(cache_path)
        return payload, "miss"

    def _build_cache_key(
        self,
        *,
        latitude: float,
        longitude: float,
        layer_id: str,
        model: str,
        forecast_hours: int,
        pressure_levels: tuple[int, ...] | None = None,
    ) -> str:
        lat_key = str(round(latitude, 3)).replace("-", "m").replace(".", "_")
        lon_key = str(round(longitude, 3)).replace("-", "m").replace(".", "_")
        model_key = model.replace("/", "_").replace(":", "_")
        pl_key = "-pl" + "_".join(str(p) for p in pressure_levels) if pressure_levels else ""
        return f"{layer_id}-{model_key}-{forecast_hours}-{lat_key}-{lon_key}{pl_key}"

    def fetch_grid_forecast(
        self,
        *,
        bbox: BoundingBox,
        resolution: float = 0.25,
        layer_spec: WeatherLayerSpec,
        model: str,
        ttl_seconds: int,
        pressure_levels: tuple[int, ...] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """
        批量获取网格化天气预报数据。

        Args:
            bbox: 地理边界框
            resolution: 网格分辨率（度），默认 0.25（约 25km）
            layer_spec: 图层规格定义
            model: 预报模型
            ttl_seconds: 缓存有效期（秒）
            pressure_levels: 气压层（hPa），如 (850, 500, 200)

        Returns:
            (grid_data, cache_status): 网格数据字典和缓存状态（"hit" 或 "miss"）

        返回格式:
            {
                "grid": {
                    "bbox": {"west": float, "south": float, "east": float, "north": float},
                    "rows": int,
                    "cols": int,
                    "resolution": float,
                    "lats": [float, ...],
                    "lons": [float, ...],
                },
                "data": {
                    "current": {
                        "windspeed_10m": [float, ...],
                        "winddirection_10m": [float, ...],
                        ...
                    },
                    "hourly": {...}
                }
            }
        """
        cache_key = self._build_grid_cache_key(
            bbox=bbox,
            resolution=resolution,
            layer_id=layer_spec.layer_id,
            model=model,
            pressure_levels=pressure_levels,
        )
        cache_path = self._cache_root / f"grid-{cache_key}.json"
        now = datetime.now(timezone.utc)

        # 检查缓存
        cached_payload, cache_is_fresh = self._read_cached_payload(cache_path, now=now)
        if cache_is_fresh and cached_payload is not None:
            return cached_payload, "hit"

        # 计算网格点数
        lat_span = bbox.north - bbox.south
        lon_span = bbox.east - bbox.west
        rows = max(1, ceil(lat_span / resolution))
        cols = max(1, ceil(lon_span / resolution))
        total_points = rows * cols

        # Open-Meteo 批量请求限制：单次最多 150 个点（URL 长度约 2500 字符，避免 414 错误）
        batch_limit = 150

        # [OpenMeteoClient] 调试：打印网格计算
        logger.info(
            "[OpenMeteoClient] fetch_grid_forecast: layer=%s bbox=(%.4f,%.4f,%.4f,%.4f) span=%.4fx%.4f resolution=%.2f rows=%d cols=%d total_points=%d batches=%d",
            layer_spec.layer_id, bbox.west, bbox.south, bbox.east, bbox.north,
            lon_span, lat_span, resolution, rows, cols, total_points,
            (total_points + batch_limit - 1) // batch_limit,
        )

        all_current_data: dict[str, list[float | None]] = {}
        all_hourly_data: dict[str, list[list[float | None]]] = {}

        # 构建经纬度数组（使用网格中心点）
        lat_step = lat_span / rows
        lon_step = lon_span / cols
        lats = [bbox.south + (i + 0.5) * lat_step for i in range(rows)]
        lons = [bbox.west + (j + 0.5) * lon_step for j in range(cols)]

        # 准备请求字段
        current_fields = sorted(set(layer_spec.current_fields))
        hourly_fields = sorted(set(layer_spec.hourly_fields))

        # 分批请求
        for batch_idx, batch_start in enumerate(range(0, total_points, batch_limit)):
            # 从第二批开始添加延迟，避免 Open-Meteo 免费 API 限流 (429)
            if batch_idx > 0:
                time.sleep(1.0)
            batch_end = min(batch_start + batch_limit, total_points)
            batch_lats = lats * cols  # 展平为 1D 数组
            batch_lons = lons * rows

            # 构建当前批次的经纬度数组
            batch_lats = []
            batch_lons = []
            for i in range(rows):
                for j in range(cols):
                    idx = i * cols + j
                    if batch_start <= idx < batch_end:
                        batch_lats.append(lats[i])
                        batch_lons.append(lons[j])

            query_dict: dict[str, str] = {
                "latitude": ",".join(f"{lat:.4f}" for lat in batch_lats),
                "longitude": ",".join(f"{lon:.4f}" for lon in batch_lons),
                "timezone": "auto",
                "forecast_days": "2",
                "current": ",".join(current_fields),
                "hourly": ",".join(hourly_fields),
                "models": model,
            }
            if pressure_levels:
                query_dict["pressure_levels"] = ",".join(str(level) for level in pressure_levels)

            query = urlencode(query_dict)

            # HTTP 请求（带重试，对 429 限流有更多容忍）
            max_attempts = 5
            backoff = 2
            batch_payload: dict[str, Any] | None = None
            for attempt in range(max_attempts):
                try:
                    # [OpenMeteoClient] 调试：打印请求信息
                    logger.info(
                        "[OpenMeteoClient] HTTP request: batch=%d-%d/%d points=%d url_len=%d attempt=%d",
                        batch_start, batch_end, total_points, len(batch_lats), len(query), attempt + 1,
                    )
                    with urlopen(f"{OPEN_METEO_BASE_URL}?{query}", timeout=30) as response:
                        raw_data = response.read().decode("utf-8")
                        batch_payload = json.loads(raw_data)
                    # [OpenMeteoClient] 调试：打印响应信息
                    resp_type = "list" if isinstance(batch_payload, list) else "dict"
                    resp_len = len(batch_payload) if isinstance(batch_payload, list) else 1
                    logger.info(
                        "[OpenMeteoClient] HTTP response: status=OK type=%s points=%d size=%d bytes",
                        resp_type, resp_len, len(raw_data),
                    )
                    break
                except HTTPError as exc:
                    logger.warning("[OpenMeteoClient] HTTP error: code=%d attempt=%d/%d", exc.code, attempt + 1, max_attempts)
                    if exc.code == 429:
                        # 限流：使用更长退避时间
                        retry_wait = max(backoff * 2, 5)
                        logger.info("[OpenMeteoClient] Rate limited (429), waiting %ds...", retry_wait)
                        if attempt == max_attempts - 1:
                            raise
                        time.sleep(retry_wait)
                        continue
                    if exc.code < 500 or attempt == max_attempts - 1:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
                except URLError:
                    logger.warning("[OpenMeteoClient] URL error: attempt=%d/%d", attempt + 1, max_attempts)
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(backoff)
                    backoff *= 2

            assert batch_payload is not None

            # Open-Meteo 多点请求返回 JSON 数组（每个元素对应一个点），
            # 单点请求返回字典。统一处理为列表。
            if isinstance(batch_payload, list):
                point_responses = batch_payload
            else:
                point_responses = [batch_payload]

            # 解析批量响应并重新组装到完整网格
            for idx_offset, point_resp in enumerate(point_responses):
                actual_idx = batch_start + idx_offset
                if actual_idx >= total_points:
                    break
                if not isinstance(point_resp, dict):
                    continue
                point_current = point_resp.get("current") or {}
                for field in current_fields:
                    if field not in all_current_data:
                        all_current_data[field] = [None] * total_points
                    val = point_current.get(field)
                    if val is not None:
                        all_current_data[field][actual_idx] = val

                point_hourly = point_resp.get("hourly") or {}
                hourly_times = point_hourly.get("time", [])
                for field in hourly_fields:
                    if field not in all_hourly_data:
                        all_hourly_data[field] = [[] for _ in range(total_points)]
                    field_values = point_hourly.get(field, [])
                    for time_idx in range(len(hourly_times)):
                        val = field_values[time_idx] if time_idx < len(field_values) else None
                        if len(all_hourly_data[field][actual_idx]) <= time_idx:
                            all_hourly_data[field][actual_idx].append(val)
                        else:
                            all_hourly_data[field][actual_idx][time_idx] = val

        # 构建返回数据
        grid_data = {
            "grid": {
                "bbox": {
                    "west": bbox.west,
                    "south": bbox.south,
                    "east": bbox.east,
                    "north": bbox.north,
                },
                "rows": rows,
                "cols": cols,
                "resolution": resolution,
                "lats": lats,
                "lons": lons,
            },
            "data": {
                "current": all_current_data,
                "hourly": all_hourly_data,
            },
        }

        # 写入缓存
        cache_tmp_path = cache_path.with_suffix(".tmp")
        cache_tmp_path.parent.mkdir(parents=True, exist_ok=True)
        cache_tmp_path.write_text(
            json.dumps(
                {
                    "expires_at": datetime.fromtimestamp(now.timestamp() + max(60, ttl_seconds), tz=timezone.utc).isoformat(),
                    "payload": grid_data,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cache_tmp_path.replace(cache_path)

        # [OpenMeteoClient] 调试：打印最终数据汇总
        current_fields_summary = {k: f"{len(v)} values, non_none={sum(1 for x in v if x is not None)}" for k, v in all_current_data.items()}
        logger.info(
            "[OpenMeteoClient] fetch_grid_forecast done: rows=%d cols=%d lats=[%.4f..%.4f] lons=[%.4f..%.4f] current_fields=%s",
            rows, cols, lats[0], lats[-1], lons[0], lons[-1], current_fields_summary,
        )

        return grid_data, "miss"

    def _build_grid_cache_key(
        self,
        *,
        bbox: BoundingBox,
        resolution: float,
        layer_id: str,
        model: str,
        pressure_levels: tuple[int, ...] | None = None,
    ) -> str:
        """构建网格数据的缓存键。"""
        # 边界取整到 0.01 度，避免细微差异导致缓存失效
        west = round(bbox.west, 2)
        south = round(bbox.south, 2)
        east = round(bbox.east, 2)
        north = round(bbox.north, 2)
        res_key = str(round(resolution, 3)).replace(".", "_")
        model_key = model.replace("/", "_").replace(":", "_")
        pl_key = "-pl" + "_".join(str(p) for p in pressure_levels) if pressure_levels else ""
        return f"{layer_id}-{model_key}-{res_key}-{west}_{south}_{east}_{north}{pl_key}"
