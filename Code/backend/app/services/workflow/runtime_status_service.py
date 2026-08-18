"""Runtime status service.

Handles runtime status reporting, config management, cache/Redis health checks,
and frontend command submission. Extracted from interaction_hub.py to separate
runtime observability from workflow orchestration.
"""

from __future__ import annotations

from datetime import datetime, UTC
import logging
import os
import time
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
    ProcessResourceSnapshot,
    ResourceUsageResponse,
    RuntimeConfigUpdateRequest,
    RuntimeConfigUpdateResponse,
    RuntimeStatusResponse,
    ServiceHealth,
    SystemResourceSnapshot,
)

logger = logging.getLogger(__name__)

_HEALTH_RANK = {
    ServiceHealth.ok: 0,
    ServiceHealth.busy: 1,
    ServiceHealth.degraded: 2,
    ServiceHealth.offline: 3,
}

# 资源采集 TTL：避免 /runtime/resources 高频轮询时反复执行 psutil 采样
_RESOURCE_TTL_SECONDS = 5
_resource_cache: dict[str, Any] = {}


def _rollup_overall_health(
    services: list[BackendServiceStatus],
    active_run_count: int,
) -> ServiceHealth:
    worst = ServiceHealth.ok
    for svc in services:
        if _HEALTH_RANK[svc.health] > _HEALTH_RANK[worst]:
            worst = svc.health
    if worst == ServiceHealth.ok and active_run_count > 0:
        return ServiceHealth.busy
    return worst


# 仅允许已接线字段；幽灵 key（如 demo_snapshot_provider、default_queue）禁止写入。
# frontend scope 暂无消费方，保留空集合占位以支持未来扩展。
# task_memory_budget_mb / task_cpu_budget_cores 为预留键：值入库+快照可读，
# 消费方（调度准入）待算法执行器接入后接线（见 .ai/progress/2026-08-18-config-effect-verification.md）。
ALLOWED_RUNTIME_CONFIG_KEYS: dict[str, set[str]] = {
    "frontend": set(),
    "backend": {
        "task_executor",
        "max_active_runs",
        "max_active_weather_tile_runs",
        "max_requested_outputs",
        "weather_cache_ttl_seconds",
        "weather_refresh_forecast_hours",
        "log_level",
        "cache_default_ttl_seconds",
        "provider_max_hotspots",
        "provider_max_series_points",
        "provider_table_chunk_size",
        "provider_series_chunk_size",
        "result_inline_max_bytes",
        "celery_task_soft_time_limit",
        "celery_task_time_limit",
        "workflow_node_parallelism",
        "algorithm_max_parallel_workers",
        "task_memory_budget_mb",
        "task_cpu_budget_cores",
    },
    "workflow": set(),
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
        "task_executor": ("choice", ["celery", "sync"]),
        "cache_default_ttl_seconds": ("int", 60, 86400),
        "provider_max_hotspots": ("int", 10, 1000),
        "provider_max_series_points": ("int", 10, 500),
        "provider_table_chunk_size": ("int", 10, 500),
        "provider_series_chunk_size": ("int", 10, 500),
        "result_inline_max_bytes": ("int", 4096, 1048576),
        "celery_task_soft_time_limit": ("int", 60, 7200),
        "celery_task_time_limit": ("int", 120, 7200),
        "workflow_node_parallelism": ("int", 1, 16),
        "algorithm_max_parallel_workers": ("int", 0, 64),
        "task_memory_budget_mb": ("int", 0, 65536),
        "task_cpu_budget_cores": ("int", 0, 64),
    },
}


class RuntimeStatusService:
    """Provides runtime status, config management, and health diagnostics."""

    def __init__(self, repository: SQLiteWorkflowRepository | None = None) -> None:
        self._repository = repository or SQLiteWorkflowRepository()

    def get_runtime_status(self) -> RuntimeStatusResponse:
        now = datetime.now(UTC)
        active_run_count = self._repository.count_active_runs()
        active_business_run_count = self._repository.count_active_runs(
            run_class="business"
        )
        active_weather_tile_run_count = self._repository.count_active_runs(
            run_class="weather_tile"
        )
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
                dispatcher_health = (
                    ServiceHealth.busy if active_run_count > 0 else ServiceHealth.ok
                )
                dispatcher_message = "当前使用 Celery 异步分发器，worker 在线。"
        else:
            dispatcher_health = (
                ServiceHealth.busy if active_run_count > 0 else ServiceHealth.ok
            )
            dispatcher_message = "当前使用本地同步任务编排器。"
        try:
            from app.services.effective_config import executor_honesty_details

            honesty = executor_honesty_details()
            if honesty.get("executor_worker_mismatch"):
                dispatcher_health = ServiceHealth.degraded
                dispatcher_message = honesty.get("message") or dispatcher_message
            if honesty.get("secrets_insecure"):
                dispatcher_message = f"{dispatcher_message} secrets_insecure=true"
        except Exception:
            logger.exception("Failed to compute executor honesty details")
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
                health=ServiceHealth.ok
                if settings.gee_enabled
                else ServiceHealth.offline,
                message="GEE 引擎桥接服务可用。"
                if settings.gee_enabled
                else "GEE 引擎桥接已禁用（BACKEND_GEE_ENABLED=false）。",
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
                health=ServiceHealth.ok
                if settings.weather_workflow_enabled
                else ServiceHealth.offline,
                message="天气工作流桥接服务可用。"
                if settings.weather_workflow_enabled
                else "天气工作流桥接已禁用（BACKEND_WEATHER_WORKFLOW_ENABLED=false）。",
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
                service_name="redis_cache",
                health=self._get_redis_health(),
                message=self._get_redis_message(),
                updated_at=now,
                details=self._collect_redis_stats(),
            ),
        ]
        overall_health = _rollup_overall_health(services, active_run_count)
        return RuntimeStatusResponse(
            overall_health=overall_health,
            service_name=settings.service_name,
            environment=settings.environment,
            updated_at=now,
            active_run_count=active_run_count,
            config_snapshot=self._repository.get_config_snapshot(),
            services=services,
        )

    def get_resource_usage(self) -> ResourceUsageResponse:
        """采集后端进程与宿主系统资源占用（psutil 轻量采样，TTL 缓存）。

        cpu_percent 使用非阻塞一次采样：首次调用返回 0.0（psutil 语义），
        第二次调用起返回与上次采样间隔内的均值。TTL 5s 内直接返回缓存。
        """
        now = datetime.now(UTC)
        cached = _resource_cache.get("payload")
        cached_at = _resource_cache.get("at", 0.0)
        if (
            cached is not None
            and (time.monotonic() - cached_at) < _RESOURCE_TTL_SECONDS
        ):
            return cached
        try:
            import psutil
        except ImportError:
            payload = ResourceUsageResponse(updated_at=now)
            _resource_cache.update({"payload": payload, "at": time.monotonic()})
            return payload

        system: SystemResourceSnapshot | None = None
        processes: list[ProcessResourceSnapshot] = []
        worker_count: int | None = None
        try:
            vm = psutil.virtual_memory()
            try:
                disk_path = settings.data_root or os.getcwd()
                disk = psutil.disk_usage(disk_path)
                disk_total_mb = round(disk.total / (1024 * 1024), 1)
                disk_used_mb = round(disk.used / (1024 * 1024), 1)
                disk_percent = round(disk.percent, 1)
            except Exception:
                disk_total_mb = disk_used_mb = disk_percent = None
            system = SystemResourceSnapshot(
                cpu_percent=round(psutil.cpu_percent(interval=None) or 0.0, 1),
                memory_total_mb=round(vm.total / (1024 * 1024), 1),
                memory_used_mb=round(vm.used / (1024 * 1024), 1),
                memory_percent=round(vm.percent, 1),
                disk_total_mb=disk_total_mb,
                disk_used_mb=disk_used_mb,
                disk_percent=disk_percent,
            )
            current_pid = os.getpid()
            parent_pid: int | None = None
            try:
                parent_pid = psutil.Process(current_pid).ppid()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            seen_pids: set[int] = set()
            for proc in psutil.process_iter(
                [
                    "pid",
                    "ppid",
                    "name",
                    "cmdline",
                    "cpu_percent",
                    "memory_info",
                    "num_threads",
                    "status",
                ]
            ):
                try:
                    info = proc.info
                    pid = info.get("pid")
                    if pid is None or pid in seen_pids:
                        continue
                    seen_pids.add(pid)
                    # 仅收集后端相关进程：当前进程及其父进程、celery worker、uvicorn。
                    # Windows 下 worker/uvicorn 进程名常为 python.exe，仅靠 name 匹配会漏，
                    # 需同时匹配 cmdline（如 python -m celery -A app ... worker）。
                    name = (info.get("name") or "").lower()
                    cmdline = " ".join(
                        str(part) for part in (info.get("cmdline") or [])
                    ).lower()
                    is_backend = (
                        pid == current_pid
                        or pid == parent_pid
                        or "celery" in name
                        or "uvicorn" in name
                        or "celery" in cmdline
                        or "uvicorn" in cmdline
                    )
                    if not is_backend:
                        continue
                    mem = info.get("memory_info")
                    rss_mb = round(mem.rss / (1024 * 1024), 1) if mem else None
                    processes.append(
                        ProcessResourceSnapshot(
                            pid=pid,
                            name=info.get("name") or str(pid),
                            cpu_percent=round(info.get("cpu_percent") or 0.0, 1),
                            memory_rss_mb=rss_mb,
                            threads=info.get("num_threads"),
                            status=info.get("status"),
                        )
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            processes.sort(key=lambda p: p.pid)
            if use_celery_executor():
                celery_details = get_celery_runtime_details()
                worker_count = int(celery_details.get("worker_count") or 0)
        except Exception as exc:  # pragma: no cover - 防御性兜底
            logger.warning("Resource usage collection failed: %s", exc)
        payload = ResourceUsageResponse(
            updated_at=now,
            system=system,
            processes=processes,
            worker_count=worker_count,
        )
        _resource_cache.update({"payload": payload, "at": time.monotonic()})
        return payload

    def update_runtime_config(
        self, payload: RuntimeConfigUpdateRequest
    ) -> RuntimeConfigUpdateResponse:
        now = datetime.now(UTC)
        self._validate_runtime_config(payload)
        applied_count = self._repository.apply_runtime_config(payload.items)
        try:
            from app.services.effective_config import hydrate_effective_config

            hydrate_effective_config()
        except Exception:
            logger.exception("Failed to rehydrate effective config after runtime PATCH")
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

    def submit_frontend_command(
        self, payload: FrontendCommandRequest
    ) -> FrontendCommandResponse:
        """Deprecated — router returns HTTP 410. Kept for contract/type reference only."""
        del payload
        raise RuntimeError(
            "submit_frontend_command is retired; use POST /frontend/commands which returns 410."
        )

    def _validate_runtime_config(self, payload: RuntimeConfigUpdateRequest) -> None:
        for item in payload.items:
            allowed_keys = ALLOWED_RUNTIME_CONFIG_KEYS.get(item.scope.value, set())
            if item.key not in allowed_keys:
                raise ValueError(
                    f"Unsupported runtime config key: {item.scope.value}.{item.key}"
                )
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
            from app.core.redis_client import scan_keys

            weather_keys = len(scan_keys(client, "weather:*"))
            dedup_lock_keys = len(scan_keys(client, "weather:lock:*"))
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
