"""Compatibility Celery task module — implementation in ``app.data_io.tasks``."""

from app.data_io.tasks.import_jobs import run_import_job

__all__ = ["run_import_job"]
