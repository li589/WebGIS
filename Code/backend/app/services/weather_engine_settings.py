"""天气引擎全局设置：默认模型真源 + Open-Meteo sync 摘要。"""

from __future__ import annotations

import logging
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from app.core.config import settings
from app.services.weather_engine_settings_repository import (
    KEY_DEFAULT_MODEL,
    KEY_LAST_SYNC,
    WeatherEngineSettingsRepository,
)
from app.weatherengine.supported_models import (
    is_supported_weather_model,
    list_supported_weather_models,
)

logger = logging.getLogger(__name__)

_effective_model_cache: str | None = None


@lru_cache(maxsize=1)
def _get_repo() -> WeatherEngineSettingsRepository:
    db_path = Path(settings.gee_credentials_db_path).parent / "weather_engine.sqlite3"
    return WeatherEngineSettingsRepository(db_path=db_path)


def invalidate_weather_default_model_cache() -> None:
    global _effective_model_cache
    _effective_model_cache = None


def get_effective_weather_default_model() -> str:
    """DB 覆盖 > env ``BACKEND_WEATHER_DEFAULT_MODEL`` > ecmwf_ifs025。"""
    global _effective_model_cache
    if _effective_model_cache is not None:
        return _effective_model_cache
    try:
        persisted = _get_repo().get(KEY_DEFAULT_MODEL)
    except Exception as exc:
        logger.warning("Failed to read weather default_model from DB: %s", exc)
        persisted = None
    model = (persisted or settings.weather_default_model or "ecmwf_ifs025").strip()
    if not model or model in {"best_match", "auto"}:
        model = "ecmwf_ifs025"
    _effective_model_cache = model
    return model


def parse_sync_domains() -> list[str]:
    raw = settings.open_meteo_sync_domains or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def set_weather_default_model(model: str) -> dict[str, Any]:
    """持久化全局默认模型；返回配置快照（可能含 warning）。"""
    cleaned = (model or "").strip()
    if not cleaned:
        raise ValueError("default_model must be a non-empty string")
    if not is_supported_weather_model(cleaned):
        raise ValueError(f"Unsupported weather model: {cleaned}")

    _get_repo().set(KEY_DEFAULT_MODEL, cleaned)
    invalidate_weather_default_model_cache()

    domains = parse_sync_domains()
    warning: str | None = None
    if cleaned not in domains:
        warning = "not_in_sync_domains"

    return {
        **get_weather_engine_public_config(),
        "default_model": cleaned,
        "warning": warning,
    }


def record_open_meteo_sync_result(
    *,
    ok: bool,
    domains: str | list[str],
    message: str = "",
    exit_code: int | None = None,
    stderr_tail: str = "",
) -> None:
    """写入最近一次 sync 结果（供 overview / 设置页）。"""
    from datetime import datetime, timezone

    domain_list = (
        [d.strip() for d in domains.split(",") if d.strip()]
        if isinstance(domains, str)
        else [str(d).strip() for d in domains if str(d).strip()]
    )
    now = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "ok": ok,
        "domains": domain_list,
        "message": (message or "")[:2000],
        "exit_code": exit_code,
        "stderr_tail": (stderr_tail or "")[:2000],
        "finished_at": now,
    }
    if ok:
        payload["last_success_at"] = now
    else:
        payload["last_failure_at"] = now

    previous = _get_repo().get_json(KEY_LAST_SYNC) or {}
    if ok:
        payload["last_failure_at"] = previous.get("last_failure_at")
    else:
        payload["last_success_at"] = previous.get("last_success_at")

    try:
        _get_repo().set_json(KEY_LAST_SYNC, payload)
    except Exception as exc:
        logger.warning("Failed to persist open-meteo sync result: %s", exc)


def get_last_sync_record() -> dict[str, Any] | None:
    try:
        return _get_repo().get_json(KEY_LAST_SYNC)
    except Exception as exc:
        logger.warning("Failed to read last_sync: %s", exc)
        return None


def probe_local_open_meteo_reachable(timeout: float = 2.0) -> bool:
    """轻量可达性探测（不解析完整 coverage）。"""
    from app.weatherengine.provider_ids import OPEN_METEO_LOCAL_URL

    try:
        with urlopen(
            f"{OPEN_METEO_LOCAL_URL}?latitude=0&longitude=0", timeout=timeout
        ) as resp:
            return 200 <= int(getattr(resp, "status", 200)) < 500
    except (URLError, HTTPError, OSError, TimeoutError):
        return False


def parse_sync_variables() -> list[str]:
    raw = settings.open_meteo_sync_variables or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def _model_meta_for_domains(domains: list[str]) -> list[dict[str, Any]]:
    by_id = {m["id"]: m for m in list_supported_weather_models()}
    rows: list[dict[str, Any]] = []
    for domain in domains:
        meta = by_id.get(domain)
        if meta:
            rows.append(dict(meta))
        else:
            rows.append(
                {
                    "id": domain,
                    "label": domain,
                    "region": "unknown",
                    "update_interval": "unknown",
                    "native_resolution": "unknown",
                    "forecast_horizon": "unknown",
                }
            )
    return rows


def _spatial_summary(models_meta: list[dict[str, Any]]) -> dict[str, Any]:
    if not models_meta:
        return {"scope": "global", "native_resolution": "unknown", "regions": []}
    regions = sorted({str(m.get("region") or "unknown") for m in models_meta})
    resolutions = [str(m.get("native_resolution") or "unknown") for m in models_meta]
    primary = models_meta[0]
    scope = "global" if all(r == "global" for r in regions) else ",".join(regions)
    return {
        "scope": scope,
        "native_resolution": str(primary.get("native_resolution") or "unknown"),
        "regions": regions,
        "resolutions": resolutions,
    }


def get_weather_sync_overview() -> dict[str, Any]:
    last = get_last_sync_record() or {}
    domains = parse_sync_domains()
    variables = parse_sync_variables()
    models_meta = _model_meta_for_domains(domains)
    spatial = _spatial_summary(models_meta)
    compose_dir = Path(settings.open_meteo_sync_compose_dir)
    compose_file = compose_dir / "docker-compose.yml"

    return {
        "local_reachable": probe_local_open_meteo_reachable(),
        "domains": domains,
        "variables": variables,
        "models_meta": models_meta,
        "data_mode": "forecast",
        "spatial": spatial,
        "temporal": {
            "kind": "forecast",
            "probe_forecast_days": 16,
            "tile_hour_cap": 47,
            "runtime_forecast_days": 2,
            "cron": {
                "minute": settings.open_meteo_sync_cron_minute,
                "hour": settings.open_meteo_sync_cron_hour,
                "timezone": "UTC",
            },
            "last_success_at": last.get("last_success_at"),
        },
        # Router may enrich these from live coverage probe + in-flight jobs
        "coverage": None,
        "coverage_error": None,
        "sync_in_progress": False,
        "enabled": bool(settings.open_meteo_sync_enabled),
        "cron": {
            "minute": settings.open_meteo_sync_cron_minute,
            "hour": settings.open_meteo_sync_cron_hour,
            "timezone": "UTC",
        },
        "compose_project": settings.open_meteo_sync_compose_project,
        "compose_dir": str(compose_dir),
        "compose_file_exists": compose_file.is_file(),
        "docker_cli_available": bool(shutil.which("docker")),
        "last_success_at": last.get("last_success_at"),
        "last_failure_at": last.get("last_failure_at"),
        "last_message": last.get("message") or "",
        "last_ok": last.get("ok"),
        "last_finished_at": last.get("finished_at"),
        "compose_hint": "docker compose -p backend up -d open-meteo  # API; sync: Code/infra/data-sync",
    }


def get_weather_engine_public_config() -> dict[str, Any]:
    """供 GET /config/weather 扩展字段。"""
    default_model = get_effective_weather_default_model()
    domains = parse_sync_domains()
    return {
        "default_model": default_model,
        "default_model_source": ("db" if _get_repo().get(KEY_DEFAULT_MODEL) else "env"),
        "sync_domains": domains,
        "sync_enabled": bool(settings.open_meteo_sync_enabled),
        "sync_cron": {
            "minute": settings.open_meteo_sync_cron_minute,
            "hour": settings.open_meteo_sync_cron_hour,
            "timezone": "UTC",
        },
        "supported_models": list_supported_weather_models(),
        "model_in_sync_domains": default_model in domains,
    }
