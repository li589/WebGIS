from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from contracts.data import DataBundle, DataRequest
from contracts.event import LogEvent
from contracts.job import JobRequest, JobResult
from contracts.product import ProductManifest, ProductRef
from interfaces.datasource import DataAsset
from interfaces.product_sink import RasterProduct, TableProduct


class PlatformSchedulerAdapterTemplate:
    def __init__(self, *, platform_client: Any = None) -> None:
        self.platform_client = platform_client

    def get_run_context(self, request: JobRequest) -> dict[str, Any]:
        return dict(self.build_run_context(request))

    def update_status(
        self,
        job_id: str,
        run_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.push_status(job_id=job_id, run_id=run_id, status=status, detail=detail)

    def complete(self, result: JobResult) -> None:
        self.push_completion(result)

    def build_run_context(self, request: JobRequest) -> dict[str, Any]:
        raise NotImplementedError

    def push_status(
        self,
        *,
        job_id: str,
        run_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError

    def push_completion(self, result: JobResult) -> None:
        raise NotImplementedError


class PlatformDataSourceAdapterTemplate:
    def __init__(self, *, platform_client: Any = None) -> None:
        self.platform_client = platform_client

    def discover(self, request: DataRequest) -> list[DataAsset]:
        return self.discover_assets(request)

    def resolve(self, request: DataRequest) -> DataBundle:
        return self.resolve_bundle(request)

    def acquire(self, bundle: DataBundle) -> DataBundle:
        return self.acquire_bundle(bundle)

    def materialize(self, bundle: DataBundle) -> DataBundle:
        return self.materialize_bundle(bundle)

    def discover_assets(self, request: DataRequest) -> list[DataAsset]:
        return []

    def resolve_bundle(self, request: DataRequest) -> DataBundle:
        raise NotImplementedError

    def acquire_bundle(self, bundle: DataBundle) -> DataBundle:
        return bundle

    def materialize_bundle(self, bundle: DataBundle) -> DataBundle:
        bundle.is_materialized = True
        return bundle


class PlatformLoggerAdapterTemplate:
    def __init__(self, *, platform_client: Any = None) -> None:
        self.platform_client = platform_client
        self._job_id: str | None = None
        self._run_id: str | None = None

    def bind_context(self, job_id: str, run_id: str) -> None:
        self._job_id = job_id
        self._run_id = run_id
        self.emit_platform_event(
            LogEvent(
                job_id=job_id,
                run_id=run_id,
                stage="dispatch",
                event_type="bind",
                timestamp=datetime.now(UTC),
                message="Bind logging context",
            )
        )

    def emit_stage_start(self, stage: str, message: str) -> None:
        self._emit(stage, "stage_start", message)

    def emit_progress(self, stage: str, progress: float, message: str) -> None:
        self._emit(stage, "progress", message, progress=progress)

    def emit_warning(
        self, stage: str, message: str, extra: dict[str, Any] | None = None
    ) -> None:
        self._emit(stage, "warning", message, extra=extra or {})

    def emit_error(
        self, stage: str, message: str, extra: dict[str, Any] | None = None
    ) -> None:
        self._emit(stage, "error", message, extra=extra or {})

    def emit_artifact(self, stage: str, artifact_uri: str, artifact_type: str) -> None:
        self._emit(
            stage,
            "artifact",
            "Artifact emitted",
            extra={"artifact_uri": artifact_uri, "artifact_type": artifact_type},
        )

    def emit_stage_end(self, stage: str, message: str) -> None:
        self._emit(stage, "stage_end", message)

    def emit_platform_event(self, event: LogEvent) -> None:
        raise NotImplementedError

    def _emit(
        self,
        stage: str,
        event_type: str,
        message: str,
        *,
        progress: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.emit_platform_event(
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


class PlatformProductSinkTemplate:
    def __init__(self, *, platform_client: Any = None) -> None:
        self.platform_client = platform_client

    def write_raster(self, product: RasterProduct) -> ProductRef:
        return self.persist_raster(product)

    def write_table(self, product: TableProduct) -> ProductRef:
        return self.persist_table(product)

    def write_manifest(self, manifest: ProductManifest) -> str:
        return self.persist_manifest(manifest)

    def persist_raster(self, product: RasterProduct) -> ProductRef:
        raise NotImplementedError

    def persist_table(self, product: TableProduct) -> ProductRef:
        raise NotImplementedError

    def persist_manifest(self, manifest: ProductManifest) -> str:
        raise NotImplementedError
