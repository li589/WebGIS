from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from celery import Celery
    from celery.schedules import crontab
    from celery.signals import task_failure, worker_process_init, worker_ready
except ImportError:  # pragma: no cover - optional dependency during bootstrap
    Celery = None
    crontab = None
    task_failure = None
    worker_process_init = None
    worker_ready = None


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
            "app.tasks.import_tasks",
            "app.data_io.tasks.import_jobs",
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
        # Windows 上 Celery 5.4 prefork 模式的 fast_trace_task 存在 thread-local
        # _loc 未初始化 bug（ValueError: not enough values to unpack），
        # 使用 solo pool 在主进程中执行任务以避免此问题。
        # C3：池模式经 settings.celery_worker_pool 配置——Windows 默认 solo（开发兜底），
        # Linux 默认 prefork（生产并行，concurrency 生效）；BACKEND_CELERY_WORKER_POOL 可覆盖。
        worker_pool=settings.celery_worker_pool,
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
        # worker 并发度与预取倍数：防止多 worker 过订阅 CPU，
        # prefetch=1 配合 acks_late 避免长任务预取占槽阻塞短任务。
        # launch.py 可按 worker 角色用 -c / --prefetch-multiplier 覆盖。
        worker_concurrency=settings.celery_worker_concurrency,
        worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
        # 防内存泄漏兜底：worker 进程处理此数任务后回收重启（0=不限制）。
        # 仅 prefork 池生效（solo 池无子进程可回收）。按任务数回收不会 kill
        # 运行中任务；不启用 max_memory_per_child 以遵守"运行中内存超限不 kill"。
        worker_max_tasks_per_child=settings.celery_worker_max_tasks_per_child,
        # 发布就绪修复（P0-7）：broker_transport_options。
        # visibility_timeout 必须 > 最长 task_time_limit（workflow=7500s），否则 acks_late
        # 下长任务会在 visibility 超时（Redis 默认 3600s）后被重投到另一 worker → 并发重复执行。
        # socket_timeout/socket_connect_timeout 给 broker 连接/读取定上界，避免 broker 挂起时
        # 工作线程无限期阻塞（同根修复线程池阻塞无寿命上界问题）。
        # C6：H3 审查修复——启用 Redis 优先级列队，使 dispatch_workflow_task 中传入的
        # priority=1/5/8/9（low/normal/high/critical）在 broker 端真正生效。
        # 注意：新增 priority_steps 后需重启全部 worker 并刷新 Redis 列队（launch.py flush）
        # 才能使现有消息对新优先列结构可见；未刷新时旧消息仍在 priority=0 默认列队，worker
        # 仍会消费（worker 订阅所有 priority steps）。
        broker_transport_options={
            "visibility_timeout": settings.celery_broker_visibility_timeout,
            "socket_timeout": settings.celery_broker_socket_timeout,
            "socket_connect_timeout": settings.celery_broker_socket_connect_timeout,
            "priority_steps": [0, 1, 5, 8, 9],
        },
        # task_queue_max_priority 须与 priority_steps 最大值一致
        task_queue_max_priority=9,
        # 兜底默认队列：任何遗漏显式 queue 的新任务落到 standard（有 worker 监听），
        # 避免静默落到无消费者消费的默认 "celery" 队列导致任务永久堆积。
        task_default_queue=settings.workflow_queue_standard,
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
    # 发布就绪修复（P1-6）：任务失败可观测。task_failure 信号在任务抛异常时触发，
    # 统一记录失败任务与异常，提供聚合的失败观测点（此前任务失败仅散落各模块日志）。
    if task_failure is not None:

        @task_failure.connect
        def _on_task_failure(sender=None, task_id=None, exception=None, **kwargs):  # type: ignore[no-untyped-def]
            logger.error(
                "Celery task failed: name=%s id=%s error=%r",
                getattr(sender, "name", "?"),
                task_id,
                exception,
            )

    # FastAPI registers weather providers in lifespan; Celery workers are a
    # separate process and must bootstrap the same registry or weather DAG
    # nodes fail with "provider is not registered" while /weather/tiles still works.
    def _bootstrap_worker_runtime() -> None:
        """P-C：worker 侧应用 DB 持久化配置（provider 覆盖 / runtime overrides / celery 时限）。

        worker_ready 覆盖 solo 池与主进程；worker_process_init 覆盖 prefork 子进程。
        任一步失败仅告警，不阻断 worker 启动（DB 不可用时保持 env/code 默认）。
        """
        try:
            from app.services.config_weather_providers import (
                apply_persisted_provider_overrides,
            )

            apply_persisted_provider_overrides()
        except Exception:
            logger.exception(
                "worker init: failed to apply persisted weather provider overrides"
            )
        try:
            from app.services.effective_config import (
                get_celery_task_soft_time_limit,
                get_celery_task_time_limit,
                hydrate_effective_config,
            )
            from app.services.weather_engine_settings import (
                invalidate_weather_default_model_cache,
            )

            hydrate_effective_config()
            invalidate_weather_default_model_cache()
            celery_app.conf.update(
                task_soft_time_limit=get_celery_task_soft_time_limit(),
                task_time_limit=get_celery_task_time_limit(),
            )
        except Exception:
            logger.exception("worker init: failed to apply runtime config overrides")

    if worker_ready is not None:

        @worker_ready.connect
        def _on_worker_ready(**kwargs):  # type: ignore[no-untyped-def]
            try:
                from app.weatherengine.provider_registry import (
                    register_default_providers,
                )

                register_default_providers()
                logger.info("Weather providers registered in Celery worker")
            except Exception:
                logger.exception(
                    "Failed to register weather providers in Celery worker"
                )
            _bootstrap_worker_runtime()

    if worker_process_init is not None:

        @worker_process_init.connect
        def _on_worker_process_init(**kwargs):  # type: ignore[no-untyped-def]
            _bootstrap_worker_runtime()

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
    # 发布就绪修复（P1-4）：solo 池看门狗，每 15 分钟把卡死的 running 工作流标记为失败
    if crontab is not None:
        beat_schedule["watchdog-stuck-running-workflows"] = {
            "task": "app.tasks.cleanup_tasks.watchdog_stuck_running_workflows",
            "schedule": crontab(minute="*/15"),
            "options": {"queue": settings.workflow_queue_batch},
        }
    # Phase C：排队工作流唤醒调度，每 2 分钟检查是否有排队工作流可以派发。
    # 兜底机制——主要触发点在 lifecycle_service 的 finalize/failure/cancel，
    # 此 Beat 任务处理边缘情况（Beat 恢复后补 dispatch、并发窗口在 finalize
    # 触发时恰好关闭等）。
    if crontab is not None:
        beat_schedule["dispatch-queued-workflows"] = {
            "task": "app.tasks.cleanup_tasks.dispatch_queued_workflows",
            "schedule": crontab(minute="*/2"),
            "options": {"queue": settings.workflow_queue_standard},
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
    """撤销 Celery 任务。

    Windows 上 ``terminate=True`` 对子进程树清理不保证；配合算法侧
    ``cancel.requested`` 旗标做协作式停止。
    """
    if not celery_available or celery_app is None:
        return
    try:
        celery_app.control.revoke(task_id, terminate=terminate)
    except Exception:
        logger = __import__("logging").getLogger(__name__)
        logger.warning("revoke_task failed for %s", task_id, exc_info=True)
