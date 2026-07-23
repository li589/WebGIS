"""单一运行时配置投影：env 冷启动 + DB 覆盖。

出网与鉴权热路径应通过本模块读取，避免 Settings / SQLite / ApiConfigManager 三源分叉。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_hydrated = False
_secrets_insecure = False


@dataclass
class RuntimeSnapshot:
    """进程内可失效的运行时投影。"""

    api_keys: dict[str, str] = field(default_factory=dict)
    weather_cache_ttl_seconds: int = 3600
    max_active_runs: int = 8
    max_active_weather_tile_runs: int = 16
    max_requested_outputs: int = 6
    weather_refresh_forecast_hours: int = 6
    log_level: str = "INFO"
    task_executor: str = "sync"
    secrets_insecure: bool = False
    cache_default_ttl_seconds: int = 1800
    provider_max_hotspots: int = 200
    provider_max_series_points: int = 240
    provider_table_chunk_size: int = 100
    provider_series_chunk_size: int = 120
    result_inline_max_bytes: int = 131072
    celery_task_soft_time_limit: int = 300
    celery_task_time_limit: int = 360
    hydrated: bool = False


_snapshot = RuntimeSnapshot()


def secrets_encryption_required() -> bool:
    env = (settings.environment or "").lower()
    return env not in {"development", "dev", "test", "testing"}


def assert_encryption_policy() -> None:
    """非 development 环境缺少加密 key 时 fail-fast。"""
    global _secrets_insecure
    key = (settings.gee_credentials_encryption_key or "").strip()
    if key:
        _secrets_insecure = False
        return
    if secrets_encryption_required():
        raise RuntimeError(
            "BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY is required outside development. "
            "Refusing to start with plaintext secret storage."
        )
    _secrets_insecure = True
    logger.error(
        "Secrets encryption key is not set; storing plaintext is allowed only in development. "
        "Set BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY for production."
    )


def is_secrets_insecure() -> bool:
    return _secrets_insecure


def hydrate_effective_config() -> RuntimeSnapshot:
    """启动时或 DB 变更后重建投影。"""
    global _snapshot, _hydrated
    with _lock:
        assert_encryption_policy()

        from app.services.config_service import get_effective_api_key

        api_keys: dict[str, str] = {}
        for name in ("tianditu", "baidu", "backend_auth", "gaode"):
            value = get_effective_api_key(name)
            if value:
                api_keys[name] = value

        # 将 DB 覆盖投影到 ApiConfigManager（仅作只读状态面，禁止第二套消费）
        try:
            from app.services.config_service import _sync_api_config_manager_key

            for name, value in api_keys.items():
                _sync_api_config_manager_key(name, value)
        except Exception:
            logger.exception("Failed to project api keys into ApiConfigManager")

        # runtime_config DB 覆盖（仅接线字段）
        overrides = _load_runtime_overrides()
        snap = RuntimeSnapshot(
            api_keys=api_keys,
            weather_cache_ttl_seconds=int(
                overrides.get(
                    "weather_cache_ttl_seconds", settings.weather_cache_ttl_seconds
                )
            ),
            max_active_runs=int(
                overrides.get("max_active_runs", settings.max_active_runs)
            ),
            max_active_weather_tile_runs=int(
                overrides.get(
                    "max_active_weather_tile_runs",
                    settings.max_active_weather_tile_runs,
                )
            ),
            max_requested_outputs=int(
                overrides.get("max_requested_outputs", settings.max_requested_outputs)
            ),
            weather_refresh_forecast_hours=int(
                overrides.get(
                    "weather_refresh_forecast_hours",
                    settings.weather_refresh_forecast_hours,
                )
            ),
            log_level=str(overrides.get("log_level", settings.log_level)),
            task_executor=str(
                overrides.get("task_executor", settings.workflow_executor)
            ).lower(),
            secrets_insecure=_secrets_insecure,
            cache_default_ttl_seconds=int(
                overrides.get(
                    "cache_default_ttl_seconds", settings.cache_default_ttl_seconds
                )
            ),
            provider_max_hotspots=int(
                overrides.get("provider_max_hotspots", settings.provider_max_hotspots)
            ),
            provider_max_series_points=int(
                overrides.get(
                    "provider_max_series_points", settings.provider_max_series_points
                )
            ),
            provider_table_chunk_size=int(
                overrides.get(
                    "provider_table_chunk_size", settings.provider_table_chunk_size
                )
            ),
            provider_series_chunk_size=int(
                overrides.get(
                    "provider_series_chunk_size", settings.provider_series_chunk_size
                )
            ),
            result_inline_max_bytes=int(
                overrides.get(
                    "result_inline_max_bytes", settings.result_inline_max_bytes
                )
            ),
            celery_task_soft_time_limit=int(
                overrides.get(
                    "celery_task_soft_time_limit", settings.celery_task_soft_time_limit
                )
            ),
            celery_task_time_limit=int(
                overrides.get("celery_task_time_limit", settings.celery_task_time_limit)
            ),
            hydrated=True,
        )
        _snapshot = snap
        _hydrated = True
        logger.info(
            "Effective config hydrated: keys=%s executor=%s weather_ttl=%s secrets_insecure=%s",
            sorted(api_keys.keys()),
            snap.task_executor,
            snap.weather_cache_ttl_seconds,
            snap.secrets_insecure,
        )
        return snap


def get_runtime_snapshot() -> RuntimeSnapshot:
    if not _hydrated:
        return hydrate_effective_config()
    return _snapshot


def invalidate_effective_config() -> None:
    """密钥或 runtime PATCH 后使投影失效。"""
    global _hydrated
    with _lock:
        _hydrated = False


def get_effective_secret(key_name: str) -> Optional[str]:
    snap = get_runtime_snapshot()
    value = snap.api_keys.get(key_name)
    if value:
        return value
    # 冷路径回落（hydrate 前/缓存清空间隙）
    from app.services.config_service import get_effective_api_key

    return get_effective_api_key(key_name)


def get_backend_auth_key() -> Optional[str]:
    return get_effective_secret("backend_auth") or (settings.api_key or None)


def get_weather_cache_ttl_seconds() -> int:
    return get_runtime_snapshot().weather_cache_ttl_seconds


def get_task_executor() -> str:
    return get_runtime_snapshot().task_executor


def use_celery_executor_effective() -> bool:
    return get_task_executor() == "celery"


def executor_honesty_details() -> dict[str, Any]:
    """供 runtime status 展示：声明 Celery 却跑 sync 时标红。"""
    from app.core.celery_app import celery_available, get_celery_runtime_details

    executor = get_task_executor()
    details = get_celery_runtime_details()
    worker_count = int(details.get("worker_count", 0) or 0)
    mismatch = False
    message = ""
    if executor != "celery" and celery_available and worker_count > 0:
        mismatch = True
        message = (
            f"workflow executor is '{executor}' but Celery workers are online; "
            "async queues will not receive workflow-runs until BACKEND_WORKFLOW_EXECUTOR=celery "
            "or runtime backend.task_executor=celery."
        )
    return {
        "task_executor": executor,
        "celery_available": celery_available,
        "worker_count": worker_count,
        "executor_worker_mismatch": mismatch,
        "message": message,
        "secrets_insecure": is_secrets_insecure(),
    }


def _load_runtime_overrides() -> dict[str, Any]:
    try:
        from app.services.workflow_repository import SQLiteWorkflowRepository

        snapshot = SQLiteWorkflowRepository().get_config_snapshot()
        backend = snapshot.get("backend") or {}
        if not isinstance(backend, dict):
            return {}
        return dict(backend)
    except Exception:
        logger.exception("Failed to load runtime config overrides")
        return {}


def get_cache_default_ttl_seconds() -> int:
    return get_runtime_snapshot().cache_default_ttl_seconds


def get_provider_max_hotspots() -> int:
    return get_runtime_snapshot().provider_max_hotspots


def get_provider_max_series_points() -> int:
    return get_runtime_snapshot().provider_max_series_points


def get_celery_task_soft_time_limit() -> int:
    return get_runtime_snapshot().celery_task_soft_time_limit


def get_celery_task_time_limit() -> int:
    return get_runtime_snapshot().celery_task_time_limit
