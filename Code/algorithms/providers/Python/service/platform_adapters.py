from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from contracts.data import DataBundle, DataRequest
from contracts.event import LogEvent
from contracts.job import JobRequest, JobResult
from contracts.product import ProductManifest, ProductRef
from interfaces.datasource import DataAsset
from interfaces.product_sink import RasterProduct, TableProduct


class CallbackSchedulerAdapter:
    def __init__(
        self,
        *,
        get_run_context: Callable[[JobRequest], dict[str, Any]] | None = None,
        update_status: Callable[[str, str, str, dict[str, Any] | None], None]
        | None = None,
        complete: Callable[[JobResult], None] | None = None,
    ) -> None:
        self._get_run_context = get_run_context or (
            lambda request: {"job_id": request.job_id}
        )
        self._update_status = update_status or (
            lambda job_id, run_id, status, detail=None: None
        )
        self._complete = complete or (lambda result: None)

    def get_run_context(self, request: JobRequest) -> dict[str, Any]:
        return self._get_run_context(request)

    def update_status(
        self,
        job_id: str,
        run_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._update_status(job_id, run_id, status, detail)

    def complete(self, result: JobResult) -> None:
        self._complete(result)


class TrackingSchedulerAdapter:
    def __init__(
        self,
        delegate,
        *,
        on_status: Callable[[str, str, str, dict[str, Any] | None], None] | None = None,
        on_complete: Callable[[JobResult], None] | None = None,
    ) -> None:
        self._delegate = delegate
        self._on_status = on_status or (
            lambda job_id, run_id, status, detail=None: None
        )
        self._on_complete = on_complete or (lambda result: None)

    def get_run_context(self, request: JobRequest) -> dict[str, Any]:
        return self._delegate.get_run_context(request)

    def update_status(
        self,
        job_id: str,
        run_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._delegate.update_status(job_id, run_id, status, detail)
        self._on_status(job_id, run_id, status, detail)

    def complete(self, result: JobResult) -> None:
        self._delegate.complete(result)
        self._on_complete(result)


class CallbackDataSourceAdapter:
    def __init__(
        self,
        *,
        discover: Callable[[DataRequest], list[DataAsset]] | None = None,
        resolve: Callable[[DataRequest], DataBundle] | None = None,
        acquire: Callable[[DataBundle], DataBundle] | None = None,
        materialize: Callable[[DataBundle], DataBundle] | None = None,
    ) -> None:
        self._discover = discover or (lambda request: [])
        if resolve is None:
            raise ValueError(
                "resolve callback is required for CallbackDataSourceAdapter"
            )
        self._resolve = resolve
        self._acquire = acquire or (lambda bundle: bundle)
        self._materialize = materialize or self._default_materialize

    def discover(self, request: DataRequest) -> list[DataAsset]:
        return self._discover(request)

    def resolve(self, request: DataRequest) -> DataBundle:
        return self._resolve(request)

    def acquire(self, bundle: DataBundle) -> DataBundle:
        return self._acquire(bundle)

    def materialize(self, bundle: DataBundle) -> DataBundle:
        return self._materialize(bundle)

    @staticmethod
    def _default_materialize(bundle: DataBundle) -> DataBundle:
        bundle.is_materialized = True
        return bundle


class CallbackLoggerAdapter:
    def __init__(
        self,
        *,
        emit: Callable[[LogEvent], None] | None = None,
    ) -> None:
        self._emit = emit or (lambda event: None)
        self._job_id: str | None = None
        self._run_id: str | None = None

    def bind_context(self, job_id: str, run_id: str) -> None:
        self._job_id = job_id
        self._run_id = run_id
        self._emit_event("bind", "dispatch", "Bind logging context")

    def emit_stage_start(self, stage: str, message: str) -> None:
        self._emit_event("stage_start", stage, message)

    def emit_progress(self, stage: str, progress: float, message: str) -> None:
        self._emit_event("progress", stage, message, progress=progress)

    def emit_warning(
        self,
        stage: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._emit_event("warning", stage, message, extra=extra or {})

    def emit_error(
        self,
        stage: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._emit_event("error", stage, message, extra=extra or {})

    def emit_artifact(self, stage: str, artifact_uri: str, artifact_type: str) -> None:
        self._emit_event(
            "artifact",
            stage,
            "Artifact emitted",
            extra={"artifact_uri": artifact_uri, "artifact_type": artifact_type},
        )

    def emit_stage_end(self, stage: str, message: str) -> None:
        self._emit_event("stage_end", stage, message)

    def _emit_event(
        self,
        event_type: str,
        stage: str,
        message: str,
        *,
        progress: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._emit(
            LogEvent(
                job_id=self._job_id or "",
                run_id=self._run_id or "",
                stage=stage,
                event_type=event_type,
                timestamp=datetime.now(UTC),
                message=message,
                progress=progress,
                extra={} if extra is None else dict(extra),
            )
        )


class CallbackProductSink:
    def __init__(
        self,
        *,
        write_raster: Callable[[RasterProduct], ProductRef] | None = None,
        write_table: Callable[[TableProduct], ProductRef] | None = None,
        write_manifest: Callable[[ProductManifest], str] | None = None,
    ) -> None:
        self._write_raster = write_raster or (
            lambda product: ProductRef(
                name=product.name,
                type="raster",
                uri=product.uri,
                variable=product.variable,
            )
        )
        self._write_table = write_table or (
            lambda product: ProductRef(name=product.name, type="table", uri=product.uri)
        )
        if write_manifest is None:
            raise ValueError(
                "write_manifest callback is required for CallbackProductSink"
            )
        self._write_manifest = write_manifest

    def write_raster(self, product: RasterProduct) -> ProductRef:
        return self._write_raster(product)

    def write_table(self, product: TableProduct) -> ProductRef:
        return self._write_table(product)

    def write_manifest(self, manifest: ProductManifest) -> str:
        return self._write_manifest(manifest)
