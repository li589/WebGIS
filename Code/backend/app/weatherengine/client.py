from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
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
    ) -> tuple[dict[str, Any], str]:
        cache_key = self._build_cache_key(
            latitude=latitude,
            longitude=longitude,
            layer_id=layer_spec.layer_id,
            model=model,
            forecast_hours=forecast_hours,
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
        query = urlencode(
            {
                "latitude": f"{latitude:.4f}",
                "longitude": f"{longitude:.4f}",
                "timezone": "auto",
                "forecast_days": 2,
                "current": ",".join(current_fields),
                "hourly": ",".join(hourly_fields),
                "models": model,
            }
        )
        with urlopen(f"{OPEN_METEO_BASE_URL}?{query}", timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))

        cache_path.write_text(
            json.dumps(
                {
                    "expires_at": datetime.fromtimestamp(now.timestamp() + max(60, ttl_seconds), tz=timezone.utc).isoformat(),
                    "payload": payload,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return payload, "miss"

    def _build_cache_key(
        self,
        *,
        latitude: float,
        longitude: float,
        layer_id: str,
        model: str,
        forecast_hours: int,
    ) -> str:
        lat_key = str(round(latitude, 3)).replace("-", "m").replace(".", "_")
        lon_key = str(round(longitude, 3)).replace("-", "m").replace(".", "_")
        model_key = model.replace("/", "_").replace(":", "_")
        return f"{layer_id}-{model_key}-{forecast_hours}-{lat_key}-{lon_key}"
