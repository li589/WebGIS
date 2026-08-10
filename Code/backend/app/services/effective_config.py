"""单一运行时配置投影：env 冷启动 + DB 覆盖。

出网与鉴权热路径应通过本模块读取，避免 Settings / SQLite / ApiConfigManager 三源分叉。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from app.core import config

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
    # 并发与资源（热更新类）
    workflow_node_parallelism: int = 1
    algorithm_max_parallel_workers: int = 0
    task_memory_budget_mb: int = 0
    task_cpu_budget_cores: int = 0
    hydrated: bool = False


_snapshot = RuntimeSnapshot()


# AES-GCM 256-bit key encoded as 64 hex chars (shared master key for GEE / API keys /
# weather providers / remote storage / portal credentials — blast radius if leaked).
_ENCRYPTION_KEY_HEX_LEN = 64


def secrets_encryption_required() -> bool:
    env = (config.settings.environment or "").lower()
    return env not in {"development", "dev", "test", "testing"}


def validate_encryption_key_format(key: str) -> None:
    """Require 32-byte AES key as 64 lowercase/uppercase hex chars."""
    raw = (key or "").strip()
    if len(raw) != _ENCRYPTION_KEY_HEX_LEN:
        raise RuntimeError(
            "BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY must be exactly 64 hex characters "
            f"(32 bytes); got length={len(raw)}."
        )
    try:
        key_bytes = bytes.fromhex(raw)
    except ValueError as exc:
        raise RuntimeError(
            "BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY is not valid hexadecimal."
        ) from exc
    if len(key_bytes) != 32:
        raise RuntimeError(
            "BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY must decode to 32 bytes."
        )


def refuse_empty_iv_outside_development(iv_b64: str | None) -> None:
    """Block treating empty-IV blobs as plaintext when encryption is mandatory."""
    if iv_b64:
        return
    if secrets_encryption_required():
        raise RuntimeError(
            "Refusing empty-IV secret blob outside development "
            "(plaintext legacy rows are not allowed when encryption is required)."
        )


def assert_encryption_policy() -> None:
    """非 development 环境缺少加密 key 时 fail-fast；有 key 时校验 hex 形态。"""
    global _secrets_insecure
    key = (config.settings.gee_credentials_encryption_key or "").strip()
    if key:
        validate_encryption_key_format(key)
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
        "Set BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY for production. "
        "Note: the same key encrypts GEE SA JSON, API keys, weather provider secrets, "
        "remote-storage credentials, and portal tokens (shared blast radius)."
    )


def assert_data_root_policy() -> None:
    """非 development/test 环境缺少 BACKEND_DATA_ROOT 时 fail-fast（去硬编码批 1）。"""
    env = (config.settings.environment or "").lower()
    if env in {"development", "dev", "test", "testing"}:
        return
    if not (config.settings.data_root or "").strip():
        raise RuntimeError(
            "BACKEND_DATA_ROOT is required outside development. "
            "Refusing to start without a configured geographic data root "
            "(do not rely on a hardcoded lab drive letter)."
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
        for name in ("tianditu", "baidu", "backend_auth", "gaode", "bing"):
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
                    "weather_cache_ttl_seconds",
                    config.settings.weather_cache_ttl_seconds,
                )
            ),
            max_active_runs=int(
                overrides.get("max_active_runs", config.settings.max_active_runs)
            ),
            max_active_weather_tile_runs=int(
                overrides.get(
                    "max_active_weather_tile_runs",
                    config.settings.max_active_weather_tile_runs,
                )
            ),
            max_requested_outputs=int(
                overrides.get(
                    "max_requested_outputs", config.settings.max_requested_outputs
                )
            ),
            weather_refresh_forecast_hours=int(
                overrides.get(
                    "weather_refresh_forecast_hours",
                    config.settings.weather_refresh_forecast_hours,
                )
            ),
            log_level=str(overrides.get("log_level", config.settings.log_level)),
            task_executor=str(
                overrides.get("task_executor", config.settings.workflow_executor)
            ).lower(),
            secrets_insecure=_secrets_insecure,
            cache_default_ttl_seconds=int(
                overrides.get(
                    "cache_default_ttl_seconds",
                    config.settings.cache_default_ttl_seconds,
                )
            ),
            provider_max_hotspots=int(
                overrides.get(
                    "provider_max_hotspots", config.settings.provider_max_hotspots
                )
            ),
            provider_max_series_points=int(
                overrides.get(
                    "provider_max_series_points",
                    config.settings.provider_max_series_points,
                )
            ),
            provider_table_chunk_size=int(
                overrides.get(
                    "provider_table_chunk_size",
                    config.settings.provider_table_chunk_size,
                )
            ),
            provider_series_chunk_size=int(
                overrides.get(
                    "provider_series_chunk_size",
                    config.settings.provider_series_chunk_size,
                )
            ),
            result_inline_max_bytes=int(
                overrides.get(
                    "result_inline_max_bytes", config.settings.result_inline_max_bytes
                )
            ),
            celery_task_soft_time_limit=int(
                overrides.get(
                    "celery_task_soft_time_limit",
                    config.settings.celery_task_soft_time_limit,
                )
            ),
            celery_task_time_limit=int(
                overrides.get(
                    "celery_task_time_limit", config.settings.celery_task_time_limit
                )
            ),
            workflow_node_parallelism=max(
                1,
                int(
                    overrides.get(
                        "workflow_node_parallelism",
                        config.settings.workflow_node_parallelism,
                    )
                ),
            ),
            algorithm_max_parallel_workers=max(
                0,
                int(
                    overrides.get(
                        "algorithm_max_parallel_workers",
                        config.settings.algorithm_max_parallel_workers,
                    )
                ),
            ),
            task_memory_budget_mb=max(
                0,
                int(
                    overrides.get(
                        "task_memory_budget_mb",
                        config.settings.task_memory_budget_mb,
                    )
                ),
            ),
            task_cpu_budget_cores=max(
                0,
                int(
                    overrides.get(
                        "task_cpu_budget_cores",
                        config.settings.task_cpu_budget_cores,
                    )
                ),
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


def get_effective_secret(key_name: str) -> str | None:
    snap = get_runtime_snapshot()
    value = snap.api_keys.get(key_name)
    if value:
        return value
    # 冷路径回落（hydrate 前/缓存清空间隙）
    from app.services.config_service import get_effective_api_key

    return get_effective_api_key(key_name)


def get_backend_auth_key() -> str | None:
    """后端写接口鉴权密钥。

    发布就绪修复（P1-6 吊销语义）：DB 存在 backend_auth 行（含禁用）时以 DB 为准，
    禁用/为空即返回 None，**绝不回落 env**——否则"禁用/删除"会静默复活已退役的
    env 密钥（config.settings.api_key 为 frozen dataclass，编辑 .env 不生效，须全栈重启，
    更放大该风险）。仅当无 DB 行（冷启动）时才回落 env。
    """
    secret = get_effective_secret("backend_auth")
    from app.services.config_service import has_api_key_db_row

    if has_api_key_db_row("backend_auth"):
        if not secret:
            logger.warning(
                "backend_auth DB 行存在但已禁用/为空：按吊销语义返回 None，不回落 env。"
                "若需恢复请重新启用或更新该 key。"
            )
        return secret
    return secret or (config.settings.api_key or None)


def get_weather_cache_ttl_seconds() -> int:
    return get_runtime_snapshot().weather_cache_ttl_seconds


def get_task_executor() -> str:
    return get_runtime_snapshot().task_executor


def use_celery_executor_effective() -> bool:
    if (config.settings.environment or "").lower() in ("test", "testing"):
        return False
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


def get_workflow_node_parallelism() -> int:
    """工作流就绪节点并行度（热更新，executor 每次执行时读取）。"""
    return get_runtime_snapshot().workflow_node_parallelism


def get_algorithm_max_parallel_workers() -> int:
    """算法包单任务最大并行进程数（0=自动）。

    bridge service 在调用算法 run_job 前读取本值并注入 os.environ
    ``CGDA_MAX_PARALLEL_WORKERS``，使算法包 _parallel.auto_process_count 生效。
    """
    return get_runtime_snapshot().algorithm_max_parallel_workers


def get_task_memory_budget_mb() -> int:
    """单任务内存预算（MB，声明值，0=不限制）。调度准入参考，非硬 kill。"""
    return get_runtime_snapshot().task_memory_budget_mb


def get_task_cpu_budget_cores() -> int:
    """单任务 CPU 预算核数（声明值，0=不限制）。调度准入参考，非硬 kill。"""
    return get_runtime_snapshot().task_cpu_budget_cores
