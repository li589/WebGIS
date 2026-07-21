"""Phase 4: 工作流定时器 Celery Beat 任务。

每分钟调用 workflow_timer_service.tick() 检查到期定时器并提交对应工作流。
事件触发器不依赖此任务，由 emit_event 接口同步触发。
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.celery_app import celery_app, celery_available
from app.core.config import settings

logger = logging.getLogger(__name__)


def execute_timer_tick() -> dict[str, Any]:
    """执行一次定时器扫描（非 Celery 入口，可供 API 直接调用）。"""
    from app.services.workflow_timer_service import tick

    return tick()


if celery_available and celery_app is not None:

    @celery_app.task(
        name="app.tasks.workflow_timer_tasks.tick_workflow_timers",
        queue=settings.workflow_queue_standard,
    )
    def tick_workflow_timers() -> dict[str, Any]:
        """Celery 任务入口：每分钟扫描到期定时器。"""
        try:
            return execute_timer_tick()
        except Exception:
            logger.exception("workflow timer tick failed")
            return {"checked": 0, "fired": 0, "failed": 0, "skipped": 0, "error": "tick_failed"}

else:

    def tick_workflow_timers() -> dict[str, Any]:
        raise RuntimeError(
            "Celery is not installed. Install backend dependencies before using workflow timer tasks."
        )
