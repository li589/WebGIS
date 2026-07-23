from __future__ import annotations

from app.core.celery_app import celery_app, celery_available
from app.core.config import settings
from app.weatherengine.service import weather_engine_service


if celery_available and celery_app is not None:

    @celery_app.task(
        name="app.tasks.weather_tasks.refresh_weather_layers_hourly",
        queue=settings.workflow_queue_weather_standard,
    )
    def refresh_weather_layers_hourly() -> list[dict[str, object]]:
        return weather_engine_service.refresh_default_layers()

else:

    def refresh_weather_layers_hourly() -> list[dict[str, object]]:
        raise RuntimeError(
            "Celery is not installed. Install backend dependencies before using weather schedule tasks."
        )
