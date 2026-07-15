"""Runtime status service.

Handles runtime status reporting, config management, cache/Redis health checks,
and frontend command submission. Extracted from interaction_hub.py to separate
runtime observability from workflow orchestration.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from app.core.celery_app import celery_available, get_celery_runtime_details
from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.services.workflow_repository import SQLiteWorkflowRepository
from app.services.workflow.transition_builder import use_celery_executor
from shared.contracts.api_contracts import (
    BackendServiceStatus,
    FrontendCommandRequest,
    FrontendCommandResponse,
    RuntimeConfigUpdateRequest,
    RuntimeConfigUpdateResponse,
    RuntimeStatusResponse,
    ServiceHealth,
)

logger = logging.getLogger(__name__)

ALLOWED_RUNTIME_CONFIG_KEYS: dict[str, set[str]] = {
    "frontend": {"demo_source_mode", "timeline_granularity", "ui_density"},
    "backend": {
        "task_executor",
        "demo_snapshot_provider",
        "max_active_runs",
        "max_active_weather_tile_runs",
        "max_requested_outputs",
        "weather_cache_ttl_seconds",
        "weather_refresh_forecast_hours",
        "log_level",
    },
    "workflow": {"default_queue", "result_retention"},
}

# Value type/range validation for runtime config keys.
# Each entry: (type_name, min_value, max_value) or ("choice", [allowed_values])
RUNTIME_CONFIG_VALUE_VALIDATORS: dict[str, dict[str, tuple]] = {
    "backend": {
        "max_active_runs": ("int", 1, 16),
        "max_active_weather_tile_runs": ("int", 1, 64),
        "max_requested_outputs": ("int", 1, 20),
        "weather_cache_ttl_seconds": ("int", 60, 86400),
        "weather_refresh_forecast_hours": ("int", 1, 48),
        "log_level": ("choice", ["DEBUG", "INFO", "WARNING", "ERROR"]),
        "task_executor": ("choice", ["celery", "in_memory", "sync"]),
    },
}


class RuntimeStatusService:
    """Provides runtime status, config management, and health diagnostics."""

    def __init__(self, repository: SQLiteWorkflowRepository | None = None) -> None:
        self._repository = repository or SQLiteWorkflowRepository()

    def get_runtime_status(self) -> RuntimeStatusResponse:
        now = datetime.now(timezone.utc)
        active_run_count = self._repository.count_active_runs()
        active_business_run_count = self._repository.count_active_runs(run_class="business")
        active_weather_tile_run_count = self._repository.count_active_runs(run_class="weather_tile")
        celery_details = get_celery_runtime_details()
        if use_celery_executor():
            if not celery_available:
                dispatcher_health = ServiceHealth.offline
                dispatcher_message = "Celery 未安装，当前异步消费不可用。"
            elif not celery_details.get("probe_ok"):
                dispatcher_health = ServiceHealth.degraded
                dispatcher_message = "Celery 已配置，但当前无法确认 worker 在线状态。"
            elif int(celery_details.get("worker_count", 0)) == 0:
                dispatcher_health = ServiceHealth.degraded
                dispatcher_message = "Celery broker 可访问，但未发现在线 worker。"
            else:
                dispatcher_health = ServiceHealth.busy if active_run_count > 0 else ServiceHealth.ok
                dispatcher_message = "当前使用 Celery 异步分发器，worker 在线。"
        else:
            dispatcher_health = ServiceHealth.busy if active_run_count > 0 else ServiceHealth.ok
            dispatcher_message = "当前使用本地同步任务编排器。"
        services = [
            BackendServiceStatus(
                service_name="api",
                health=ServiceHealth.ok,
                message="接口服务正常。",
                updated_at=now,
                details={"router_count": 14, "workflow_route_count_hint": 14},
            ),
            BackendServiceStatus(
                service_name="workflow_dispatcher",
                health=dispatcher_health,
                message=dispatcher_message,
                updated_at=now,
                details={
                    "active_run_count": active_run_count,
                    "active_business_run_count": active_business_run_count,
                    "active_weather_tile_run_count": active_weather_tile_run_count,
                    "executor": settings.workflow_executor,
                    "celery_available": celery_available,
                    "celery_probe": celery_details,
                    "max_active_runs": settings.max_active_runs,
                    "max_active_weather_tile_runs": settings.max_active_weather_tile_runs,
                    "queues": {
                        "realtime": settings.workflow_queue_realtime,
                        "algorithm_realtime": settings.workflow_queue_algorithm_realtime,
                        "algorithm_standard": settings.workflow_queue_algorithm_standard,
                        "algorithm_heavy": settings.workflow_queue_algorithm_heavy,
                        "algorithm_batch": settings.workflow_queue_algorithm_batch,
                        "download_realtime": settings.workflow_queue_download_realtime,
                        "download_standard": settings.workflow_queue_download_standard,
                        "analysis_standard": settings.workflow_queue_analysis_standard,
                        "analysis_heavy": settings.workflow_queue_analysis_heavy,
                        "analysis_batch": settings.workflow_queue_analysis_batch,
                        "gee_realtime": settings.workflow_queue_gee_realtime,
                        "gee_standard": settings.workflow_queue_gee_standard,
                        "gee_heavy": settings.workflow_queue_gee_heavy,
                        "gee_batch": settings.workflow_queue_gee_batch,
                        "weather_realtime": settings.workflow_queue_weather_realtime,
                        "weather_standard": settings.workflow_queue_weather_standard,
                        "weather_heavy": settings.workflow_queue_weather_heavy,
                        "weather_batch": settings.workflow_queue_weather_batch,
                    },
                },
            ),
            BackendServiceStatus(
                service_name="analysis_workflow_service",
                health=ServiceHealth.ok,
                message="分析工作流服务可用。",
                updated_at=now,
                details={
                    "execution_mode": "sync_or_provider",
                    "result_inline_max_bytes": settings.result_inline_max_bytes,
                    "provider_max_hotspots": settings.provider_max_hotspots,
                    "provider_max_series_points": settings.provider_max_series_points,
                    "provider_table_chunk_size": settings.provider_table_chunk_size,
                    "provider_series_chunk_size": settings.provider_series_chunk_size,
                    "object_store_backend": settings.object_store_backend,
                },
            ),
            BackendServiceStatus(
                service_name="python_provider_bridge_service",
                health=ServiceHealth.ok,
                message="Python 算法桥接服务可用。",
                updated_at=now,
                details={
                    "provider_root": settings.python_provider_root,
                    "workspace": settings.python_provider_workspace,
                    "queues": {
                        "realtime": settings.workflow_queue_algorithm_realtime,
                        "standard": settings.workflow_queue_algorithm_standard,
                        "heavy": settings.workflow_queue_algorithm_heavy,
                        "batch": settings.workflow_queue_algorithm_batch,
                    },
                },
            ),
            BackendServiceStatus(
                service_name="gee_bridge_service",
                health=ServiceHealth.ok if settings.gee_enabled else ServiceHealth.offline,
                message="GEE 引擎桥接服务可用。" if settings.gee_enabled else "GEE 引擎桥接已禁用（BACKEND_GEE_ENABLED=false）。",
                updated_at=now,
                details={
                    "enabled": settings.gee_enabled,
                    "module_root": settings.gee_module_root,
                    "storage_backend": settings.gee_storage_backend,
                    "local_storage_root": settings.gee_local_storage_root,
                    "account_cooldown_seconds": settings.gee_account_cooldown_seconds,
                    "max_parallel_exports": settings.gee_max_parallel_exports,
                    "queues": {
                        "realtime": settings.workflow_queue_gee_realtime,
                        "standard": settings.workflow_queue_gee_standard,
                        "heavy": settings.workflow_queue_gee_heavy,
                        "batch": settings.workflow_queue_gee_batch,
                    },
                },
            ),
            BackendServiceStatus(
                service_name="weather_bridge_service",
                health=ServiceHealth.ok if settings.weather_workflow_enabled else ServiceHealth.offline,
                message="天气工作流桥接服务可用。" if settings.weather_workflow_enabled else "天气工作流桥接已禁用（BACKEND_WEATHER_WORKFLOW_ENABLED=false）。",
                updated_at=now,
                details={
                    "enabled": settings.weather_workflow_enabled,
                    "queues": {
                        "realtime": settings.workflow_queue_weather_realtime,
                        "standard": settings.workflow_queue_weather_standard,
                        "heavy": settings.workflow_queue_weather_heavy,
                        "batch": settings.workflow_queue_weather_batch,
                    },
                },
            ),
            BackendServiceStatus(
                service_name="download_workflow_service",
                health=ServiceHealth.ok,
                message="下载工作流服务可用。",
                updated_at=now,
                details={
                    "dispatch_channel": "download",
                    "download_realtime_queue": settings.workflow_queue_download_realtime,
                    "download_standard_queue": settings.workflow_queue_download_standard,
                    "cache_dir": settings.cache_dir,
                    "cache_default_ttl_seconds": settings.cache_default_ttl_seconds,
                    "cache_stats": self._collect_cache_stats(),
                },
            ),
            BackendServiceStatus(
                service_name="redis_cache",
                health=self._get_redis_health(),
                message=self._get_redis_message(),
                updated_at=now,
                details=self._collect_redis_stats(),
            ),
        ]
        overall_health = ServiceHealth.busy if active_run_count > 0 else ServiceHealth.ok
        return RuntimeStatusResponse(
            overall_health=overall_health,
            service_name=settings.service_name,
            environment=settings.environment,
            updated_at=now,
            active_run_count=active_run_count,
            config_snapshot=self._repository.get_config_snapshot(),
            services=services,
        )

    def update_runtime_config(self, payload: RuntimeConfigUpdateRequest) -> RuntimeConfigUpdateResponse:
        now = datetime.now(timezone.utc)
        self._validate_runtime_config(payload)
        applied_count = self._repository.apply_runtime_config(payload.items)
        return RuntimeConfigUpdateResponse(
            accepted=True,
            updated_at=now,
            applied_count=applied_count,
            message="运行时配置已更新。",
            config_snapshot=self._repository.get_config_snapshot(),
        )

    def get_runtime_config(self) -> dict[str, dict[str, object]]:
        """Return the current runtime config snapshot (merged defaults + DB overrides)."""
        return self._repository.get_config_snapshot()

    def submit_frontend_command(self, payload: FrontendCommandRequest) -> FrontendCommandResponse:
        now = datetime.now(timezone.utc)
        next_action = {
            "preload": "schedule-prefetch",
            "clear_cache": "clear-local-cache",
            "cleanup": "release-preview-resources",
            "cancel_run": "cancel-pending-run",
            "reload_catalog": "refresh-layer-catalog",
            "custom": "inspect-custom-command",
        }.get(payload.command_type.value, "inspect-command")
        return FrontendCommandResponse(
            accepted=True,
            command_type=payload.command_type,
            target=payload.target,
            created_at=now,
            message="前端控制指令已接收。",
            next_action=next_action,
        )

    def _validate_runtime_config(self, payload: RuntimeConfigUpdateRequest) -> None:
        for item in payload.items:
            allowed_keys = ALLOWED_RUNTIME_CONFIG_KEYS.get(item.scope.value, set())
            if item.key not in allowed_keys:
                raise ValueError(f"Unsupported runtime config key: {item.scope.value}.{item.key}")
            scope_validators = RUNTIME_CONFIG_VALUE_VALIDATORS.get(item.scope.value, {})
            validator = scope_validators.get(item.key)
            if validator is None:
                continue
            kind = validator[0]
            if kind == "int":
                _, min_val, max_val = validator
                if not isinstance(item.value, int) or isinstance(item.value, bool):
                    raise ValueError(
                        f"Invalid value for {item.scope.value}.{item.key}: expected int, got {type(item.value).__name__}"
                    )
                if not (min_val <= item.value <= max_val):
                    raise ValueError(
                        f"Value for {item.scope.value}.{item.key} out of range: {item.value}, expected [{min_val}, {max_val}]"
                    )
            elif kind == "choice":
                allowed_values = validator[1]
                if item.value not in allowed_values:
                    raise ValueError(
                        f"Invalid value for {item.scope.value}.{item.key}: {item.value!r}, expected one of {allowed_values}"
                    )

    def _collect_cache_stats(self) -> dict[str, Any]:
        """收集 cache_service 的运行时统计快照。"""
        try:
            from app.services.cache_service import cache_service

            stats = cache_service.get_stats()
            return {
                "hits": stats.hits,
                "misses": stats.misses,
                "upserts": stats.upserts,
                "evictions": stats.evictions,
                "hit_rate": stats.hit_rate,
                "total_entries": stats.total_entries,
                "fresh_entries": stats.fresh_entries,
                "expired_entries": stats.expired_entries,
                "scopes": stats.scopes,
            }
        except Exception as exc:  # pragma: no cover - 防御性兜底
            return {"error": str(exc)}

    def _get_redis_health(self) -> ServiceHealth:
        """探测 Redis 缓存健康状态。"""
        client = get_redis_client()
        if client is None:
            return ServiceHealth.degraded
        try:
            client.ping()
            return ServiceHealth.ok
        except Exception:
            return ServiceHealth.degraded

    def _get_redis_message(self) -> str:
        """返回 Redis 缓存状态描述。"""
        client = get_redis_client()
        if client is None:
            return "Redis 缓存不可用，天气数据回退到文件缓存。"
        try:
            client.ping()
            return "Redis 缓存在线，用于天气数据缓存与跨 worker 去重。"
        except Exception as exc:
            return f"Redis 连接异常：{exc}"

    def _collect_redis_stats(self) -> dict[str, Any]:
        """收集 Redis 缓存运行时统计快照。"""
        client = get_redis_client()
        if client is None:
            return {"available": False, "reason": "client_unavailable"}
        try:
            info = client.info(section="memory")
            dbsize = client.dbsize()
            weather_keys = len(client.keys("weather:*"))
            dedup_lock_keys = len(client.keys("weather:lock:*"))
            return {
                "available": True,
                "url": settings.redis_url,
                "db_size": dbsize,
                "weather_cache_keys": weather_keys - dedup_lock_keys,
                "dedup_lock_keys": dedup_lock_keys,
                "used_memory_human": info.get("used_memory_human"),
                "used_memory_peak_human": info.get("used_memory_peak_human"),
                "maxmemory_human": info.get("maxmemory_human"),
                "evicted_keys": info.get("evicted_keys", 0),
                "expired_keys": info.get("expired_keys", 0),
                "connected_clients": info.get("connected_clients"),
                "uptime_in_seconds": info.get("uptime_in_seconds"),
            }
        except Exception as exc:  # pragma: no cover - 防御性兜底
            return {"available": False, "error": str(exc)}
