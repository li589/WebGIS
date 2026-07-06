from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from app.core.config import settings
from app.weatherengine.constants import OPEN_METEO_BASE_URL, WeatherLayerSpec


class OpenMeteoClient:
    def __init__(self, cache_root: str | Path | None = None) -> None:
        self._cache_root = Path(cache_root or settings.cache_dir) / "weatherengine"
        self._cache_root.mkdir(parents=True, exist_ok=True)

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
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            expires_raw = cached["expires_at"]
            if isinstance(expires_raw, (int, float)):
                expires_at = datetime.fromtimestamp(expires_raw, tz=timezone.utc)
            else:
                expires_at = datetime.fromisoformat(expires_raw)
            if expires_at > now:
                return cached["payload"], "hit"

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
        # HTTP 错误处理 + 瞬态失败重试：5xx 与 URLError 重试，4xx 立即抛出
        max_attempts = 3
        backoff = 2
        payload: dict[str, Any] | None = None
        for attempt in range(max_attempts):
            try:
                with urlopen(f"{OPEN_METEO_BASE_URL}?{query}", timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                # 4xx 客户端错误不重试，直接抛出
                if exc.code < 500 or attempt == max_attempts - 1:
                    raise
                time.sleep(backoff)
                backoff *= 2
            except URLError:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(backoff)
                backoff *= 2
        # payload 在 break 后必已赋值；此处仅为类型检查兜底
        assert payload is not None

        # 原子写入缓存：先写临时文件再 rename，避免半写文件被并发读取
        cache_tmp_path = cache_path.with_suffix(".tmp")
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
