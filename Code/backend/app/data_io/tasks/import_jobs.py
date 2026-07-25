"""导入任务 Celery 入口（可选）。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.celery_app import celery_app, celery_available
from app.core.config import settings

logger = logging.getLogger(__name__)


def _dispatch(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "vector":
        from app.data_io.services.vector import import_vector_from_paths

        paths = [Path(p) for p in payload.get("paths") or []]
        return import_vector_from_paths(paths, source_name=payload.get("source_name"))
    if kind == "document":
        from app.data_io.services.document import create_document_session

        return create_document_session(
            Path(payload["path"]), source_name=payload.get("source_name")
        )
    if kind == "document_commit":
        from app.data_io.services.document import commit_document_session

        return commit_document_session(
            payload["session_id"],
            x_field=payload["x_field"],
            y_field=payload["y_field"],
            source_crs=payload.get("source_crs", "EPSG:4326"),
            target_crs=payload.get("target_crs", "EPSG:4326"),
            lng_offset=float(payload.get("lng_offset") or 0),
            lat_offset=float(payload.get("lat_offset") or 0),
        )
    if kind == "raster_commit":
        from app.data_io.services.raster_commit import commit_raster_upload

        return commit_raster_upload(
            upload_id=str(payload.get("upload_id") or ""),
            variable_id=payload.get("variable_id"),
            variable_ids=list(payload.get("variable_ids") or []),
            time_index=int(payload.get("time_index") or 0),
            source_name=payload.get("source_name"),
            source_crs=payload.get("source_crs"),
            grid_preset=payload.get("grid_preset"),
            bounds=payload.get("bounds"),
            invalid_values=list(payload.get("invalid_values") or []),
            nodata=payload.get("nodata"),
            auto_confirm=bool(payload.get("auto_confirm", True)),
            lng_offset=float(payload.get("lng_offset") or 0),
            lat_offset=float(payload.get("lat_offset") or 0),
        )
    if kind == "export_batch":
        from app.data_io.services.export_layer import export_layers_batch_zip

        return export_layers_batch_zip(
            payload.get("layer_ids") or [],
            format=payload.get("format") or "geojson",
            encoding=payload.get("encoding") or "auto",
        )
    raise ValueError(f"未知导入任务类型: {kind}")


if celery_available and celery_app is not None:

    @celery_app.task(
        name="app.tasks.import_tasks.run_import_job",
        queue=getattr(settings, "workflow_queue_batch", "celery"),
    )
    def run_import_job(job_id: str, kind: str) -> dict[str, Any]:
        from app.data_io.services.jobs import run_job_sync

        def handler(payload: dict[str, Any]) -> dict[str, Any]:
            return _dispatch(kind, payload)

        return run_job_sync(job_id, handler)

else:

    def run_import_job(job_id: str, kind: str) -> dict[str, Any]:  # type: ignore[misc]
        raise RuntimeError("Celery unavailable")
