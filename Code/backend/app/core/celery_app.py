from __future__ import annotations

from app.core.config import settings

try:
    from celery import Celery
except ImportError:  # pragma: no cover - optional dependency during bootstrap
    Celery = None


celery_available = Celery is not None

if celery_available:
    celery_app = Celery(
        "cgda_backend",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["app.tasks.workflow_tasks", "app.tasks.download_tasks"],
    )
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_always_eager=settings.celery_task_always_eager,
    )
else:  # pragma: no cover - exercised only when Celery is unavailable
    celery_app = None
