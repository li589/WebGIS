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
        include=[
            "app.tasks.workflow_tasks",
            "app.tasks.download_tasks",
            "app.tasks.weather_tasks",
            "app.tasks.open_meteo_sync_tasks",
            "app.tasks.workflow_timer_tasks",
            "app.tasks.cleanup_tasks",
        ],
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
        # 显式设置结果过期时间：Redis backend 会在 TTL 到期后自动删除
        # 避免长期运行后 Celery 结果在 Redis 中无限累积
        result_expires=86400,  # 1 天
        result_persistent=False,
        # Beat / 运维任务必须落到 launch.py 实际监听的队列（勿用默认 celery）
        task_routes={
            "app.tasks.open_meteo_sync_tasks.sync_open_meteo_data": {
                "queue": settings.workflow_queue_weather_batch,
            },
            "app.tasks.weather_tasks.refresh_weather_layers_hourly": {
                "queue": settings.workflow_queue_weather_standard,
            },
            "app.tasks.workflow_timer_tasks.tick_workflow_timers": {
                "queue": settings.workflow_queue_standard,
            },
            "app.tasks.cleanup_tasks.cleanup_workflow_runs": {
                "queue": settings.workflow_queue_batch,
            },
            "app.tasks.cleanup_tasks.cleanup_cache_files": {
                "queue": settings.workflow_queue_batch,
            },
        },
    )
    beat_schedule: dict[str, dict[str, Any]] = {}
    if settings.weather_schedule_enabled and crontab is not None:
        beat_schedule["refresh-weather-layers-hourly"] = {
            "task": "app.tasks.weather_tasks.refresh_weather_layers_hourly",
            "schedule": crontab(minute=0),
            "options": {"queue": settings.workflow_queue_weather_standard},
        }
    # Phase 2: Open-Meteo 本地数据自动同步
    # 默认每 6 小时在 30 分触发（UTC），避开 ECMWF 00/06/12/18 UTC 发布时刻
    if settings.open_meteo_sync_enabled and crontab is not None:
        beat_schedule["sync-open-meteo-data"] = {
            "task": "app.tasks.open_meteo_sync_tasks.sync_open_meteo_data",
            "schedule": crontab(
                minute=settings.open_meteo_sync_cron_minute,
                hour=settings.open_meteo_sync_cron_hour,
            ),
            "options": {
                "queue": settings.workflow_queue_weather_batch,
                # 覆盖全局 300/360s；全球 sync 可达数十分钟
                "soft_time_limit": 3600,
                "time_limit": 3900,
            },
        }
    # Phase 4: 工作流定时器扫描（每分钟触发）
    # 事件触发器由 emit_event API 同步执行，不依赖此 beat 任务
    if crontab is not None:
        beat_schedule["tick-workflow-timers"] = {
            "task": "app.tasks.workflow_timer_tasks.tick_workflow_timers",
            "schedule": crontab(minute="*"),
            "options": {"queue": settings.workflow_queue_standard},
        }
    # 长期运行清理任务：避免 SQLite 与缓存文件无限增长
    # - workflow runs 保留 30 天，每天 03:00 UTC 清理
    # - 缓存文件每天 03:30 UTC 清理（仅删除已过期项）
    if crontab is not None:
        beat_schedule["cleanup-workflow-runs"] = {
            "task": "app.tasks.cleanup_tasks.cleanup_workflow_runs",
            "schedule": crontab(minute=0, hour=3),
            "kwargs": {"retention_days": 30, "vacuum": False},
            "options": {"queue": settings.workflow_queue_batch},
        }
        beat_schedule["cleanup-cache-files"] = {
            "task": "app.tasks.cleanup_tasks.cleanup_cache_files",
            "schedule": crontab(minute=30, hour=3),
            "options": {"queue": settings.workflow_queue_batch},
        }
    if beat_schedule:
        celery_app.conf.beat_schedule = beat_schedule
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
        inspector = celery_app.control.inspect(timeout=0.5)
        ping_result = inspector.ping() or {}
        worker_names = sorted(set(ping_result))
        return {
            "available": True,
            "probe_ok": True,
            "worker_count": len(worker_names),
            "workers": worker_names,
            "active_queues": {},
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
