from __future__ import annotations

from typing import Any

from app.core.config import settings

try:
    from celery import Celery
    from celery.schedules import crontab
except ImportError:  # pragma: no cover - optional dependency during bootstrap
    Celery = None
    crontab = None


celery_available = Celery is not None

if celery_available:
    celery_app = Celery(
        "cgda_backend",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["app.tasks.workflow_tasks", "app.tasks.download_tasks", "app.tasks.weather_tasks"],
    )
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        # 禁用 task_send_sent_event 以避免 Windows 上 Celery 5.4 的 ValueError 问题
        task_send_sent_event=False,
        worker_send_task_events=False,
        # 使用标准 trace 模式而非 fast_trace
        worker_pool="prefork",
        task_always_eager=settings.celery_task_always_eager,
        # 默认任务超时限制，防止无限期运行
        # soft_time_limit：软超时，抛出 SoftTimeLimitExceeded，可被捕获清理
        # time_limit：硬超时，直接 SIGKILL，不可捕获
        task_soft_time_limit=settings.celery_task_soft_time_limit,
        task_time_limit=settings.celery_task_time_limit,
    )
    if settings.weather_schedule_enabled and crontab is not None:
        celery_app.conf.beat_schedule = {
            "refresh-weather-layers-hourly": {
                "task": "app.tasks.weather_tasks.refresh_weather_layers_hourly",
                "schedule": crontab(minute=0),
            }
        }
else:  # pragma: no cover - exercised only when Celery is unavailable
    celery_app = None


def get_celery_runtime_details() -> dict[str, Any]:
    """返回 Celery broker/worker 的轻量运行态信息。"""
    if not celery_available or celery_app is None:
        return {
            "available": False,
            "probe_ok": False,
            "worker_count": 0,
            "workers": [],
            "active_queues": {},
        }

    try:
        inspector = celery_app.control.inspect(timeout=1.0)
        ping_result = inspector.ping() or {}
        queues_result = inspector.active_queues() or {}
        stats_result = inspector.stats() or {}
        worker_names = sorted(set(ping_result) | set(queues_result) | set(stats_result))
        queue_names = {
            worker: [item.get("name", "") for item in queues_result.get(worker, [])]
            for worker in worker_names
        }
        return {
            "available": True,
            "probe_ok": True,
            "worker_count": len(worker_names),
            "workers": worker_names,
            "active_queues": queue_names,
        }
    except Exception as exc:  # pragma: no cover - depends on runtime infra
        return {
            "available": True,
            "probe_ok": False,
            "worker_count": 0,
            "workers": [],
            "active_queues": {},
            "error": str(exc),
        }


def revoke_task(task_id: str, terminate: bool = False) -> None:
    """撤销 Celery 任务。"""
    if not celery_available or celery_app is None:
        return
    celery_app.control.revoke(task_id, terminate=terminate)
