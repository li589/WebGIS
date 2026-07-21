"""长期运行清理任务：避免 SQLite 与缓存文件无限增长。

Celery Beat 调度：
- cleanup_workflow_runs: 每天凌晨 3:00 UTC，清理 30 天前已完成的 workflow runs
- cleanup_cache_files:   每天凌晨 3:30 UTC，删除已过期的缓存文件
- celery.backend_cleanup: Celery 默认任务，每天 3:30 清理过期结果（result_expires 控制）
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.celery_app import celery_app, celery_available
from app.core.config import settings

logger = logging.getLogger(__name__)


def execute_workflow_runs_cleanup(*, retention_days: int = 30, vacuum: bool = False) -> dict[str, Any]:
    """执行 workflow_runs/events 清理（非 Celery 入口，可供 API 直接调用）。"""
    from app.services.workflow_repository import SQLiteWorkflowRepository

    repository = SQLiteWorkflowRepository()
    stats = repository.cleanup_old_runs(
        retention_days=retention_days,
        vacuum=vacuum,
    )
    logger.info("workflow runs cleanup done: %s", stats)
    return {"retention_days": retention_days, **stats}


def execute_cache_cleanup() -> dict[str, Any]:
    """执行缓存文件清理（非 Celery 入口，可供 API 直接调用）。"""
    from app.services.cache_service import cache_service

    stats = cache_service.cleanup_expired()
    logger.info("cache cleanup done: %s", stats)
    return stats


if celery_available and celery_app is not None:

    @celery_app.task(
        name="app.tasks.cleanup_tasks.cleanup_workflow_runs",
        queue=settings.workflow_queue_batch,
    )
    def cleanup_workflow_runs(retention_days: int = 30, vacuum: bool = False) -> dict[str, Any]:
        """Celery 任务入口：清理过期 workflow runs。"""
        try:
            return execute_workflow_runs_cleanup(retention_days=retention_days, vacuum=vacuum)
        except Exception:
            logger.exception("workflow runs cleanup task failed")
            return {"error": "cleanup_failed", "retention_days": retention_days}

    @celery_app.task(
        name="app.tasks.cleanup_tasks.cleanup_cache_files",
        queue=settings.workflow_queue_batch,
    )
    def cleanup_cache_files() -> dict[str, Any]:
        """Celery 任务入口：清理过期缓存文件。"""
        try:
            return execute_cache_cleanup()
        except Exception:
            logger.exception("cache cleanup task failed")
            return {"error": "cleanup_failed"}

else:

    def cleanup_workflow_runs(retention_days: int = 30, vacuum: bool = False) -> dict[str, Any]:
        raise RuntimeError(
            "Celery is not installed. Install backend dependencies before using cleanup tasks."
        )

    def cleanup_cache_files() -> dict[str, Any]:
        raise RuntimeError(
            "Celery is not installed. Install backend dependencies before using cleanup tasks."
        )
