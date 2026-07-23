from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from threading import Lock
from typing import Any

from contracts.data import DataBundle, DataRequest
from contracts.event import LogEvent
from contracts.job import JobRequest, JobResult
from contracts.product import ProductManifest, ProductRef
from interfaces.datasource import DataAsset
from interfaces.product_sink import RasterProduct, TableProduct
from service.job_queue import QueuedJobSubmission


@dataclass(slots=True)
class MockBundleRecord:
    data_bundle: DataBundle
    assets: list[DataAsset] = field(default_factory=list)


class PlatformClientMock:
    def __init__(self) -> None:
        self._lock = Lock()
        self.run_contexts: dict[str, dict[str, Any]] = {}
        self.status_events: list[dict[str, Any]] = []
        self.completed_results: list[JobResult] = []
        self.log_events: list[LogEvent] = []
        self.persisted_products: list[ProductRef] = []
        self.persisted_manifests: dict[str, ProductManifest] = {}
        self.data_bundles: dict[str, MockBundleRecord] = {}
        self.queued_submissions: list[QueuedJobSubmission] = []
        self.acked_submissions: list[str] = []

    def register_bundle(
        self,
        dataset_name: str,
        bundle: DataBundle,
        *,
        assets: list[DataAsset] | None = None,
    ) -> None:
        with self._lock:
            self.data_bundles[dataset_name] = MockBundleRecord(
                data_bundle=bundle,
                assets=[] if assets is None else list(assets),
            )

    def build_run_context(self, request: JobRequest) -> dict[str, Any]:
        context = {"job_id": request.job_id, "platform": "mock"}
        with self._lock:
            self.run_contexts[request.job_id] = dict(context)
        return context

    def publish_submission(self, item: QueuedJobSubmission) -> None:
        with self._lock:
            self.queued_submissions.append(_copy_submission(item))

    def claim_submission(
        self, *, timeout: float | None = None
    ) -> QueuedJobSubmission | None:
        _ = timeout
        with self._lock:
            if not self.queued_submissions:
                return None
            return self.queued_submissions.pop(0)

    def ack_submission(self, item: QueuedJobSubmission) -> None:
        with self._lock:
            self.acked_submissions.append(item.submission_id)

    def update_job_status(
        self,
        job_id: str,
        run_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self.status_events.append(
                {
                    "job_id": job_id,
                    "run_id": run_id,
                    "status": status,
                    "detail": {} if detail is None else dict(detail),
                }
            )

    def complete_job(self, result: JobResult) -> None:
        with self._lock:
            self.completed_results.append(result)

    def discover_assets(self, request: DataRequest) -> list[DataAsset]:
        with self._lock:
            record = self.data_bundles.get(request.dataset_name)
            if record is None:
                return []
            return list(record.assets)

    def resolve_bundle(self, request: DataRequest) -> DataBundle:
        with self._lock:
            record = self.data_bundles.get(request.dataset_name)
            if record is None:
                return DataBundle(
                    bundle_id=request.dataset_name,
                    dataset_name=request.dataset_name,
                    variables=list(request.variables),
                    time_range=request.time_range,
                    storage_mode=request.acquire_mode,
                )
            return _copy_bundle(record.data_bundle)

    def acquire_bundle(self, bundle: DataBundle) -> DataBundle:
        bundle.metadata["acquired_by"] = "platform_client_mock"
        return bundle

    def materialize_bundle(self, bundle: DataBundle) -> DataBundle:
        bundle.is_materialized = True
        if not bundle.local_paths:
            bundle.local_paths.append(f"memory://{bundle.bundle_id}")
        return bundle

    def emit_log_event(self, event: LogEvent) -> None:
        with self._lock:
            self.log_events.append(event)

    def persist_raster(self, product: RasterProduct) -> ProductRef:
        ref = ProductRef(
            name=product.name,
            type="platform_raster",
            uri=product.uri,
            variable=product.variable,
        )
        with self._lock:
            self.persisted_products.append(ref)
        return ref

    def persist_table(self, product: TableProduct) -> ProductRef:
        ref = ProductRef(name=product.name, type="platform_table", uri=product.uri)
        with self._lock:
            self.persisted_products.append(ref)
        return ref

    def persist_manifest(self, manifest: ProductManifest) -> str:
        uri = f"memory://manifests/{manifest.run_id}.json"
        with self._lock:
            self.persisted_manifests[manifest.run_id] = manifest
        return uri


def _copy_bundle(bundle: DataBundle) -> DataBundle:
    return DataBundle(
        bundle_id=bundle.bundle_id,
        dataset_name=bundle.dataset_name,
        variables=list(bundle.variables),
        time_range=bundle.time_range,
        storage_mode=bundle.storage_mode,
        local_paths=list(bundle.local_paths),
        remote_refs=list(bundle.remote_refs),
        metadata=dict(bundle.metadata),
        is_materialized=bundle.is_materialized,
    )


def _copy_submission(item: QueuedJobSubmission) -> QueuedJobSubmission:
    return QueuedJobSubmission(
        submission_id=item.submission_id,
        request=_copy_job_request(item.request),
        enqueued_at=item.enqueued_at.astimezone(UTC)
        if item.enqueued_at.tzinfo is not None
        else item.enqueued_at,
    )


def _copy_job_request(request: JobRequest) -> JobRequest:
    return JobRequest(
        job_id=request.job_id,
        pipeline_name=request.pipeline_name,
        task_type=request.task_type,
        time_range=request.time_range,
        region=request.region,
        datasource_selection=dict(request.datasource_selection),
        algorithm_params=dict(request.algorithm_params),
        output_spec=request.output_spec,
        resource_hint=request.resource_hint,
        cache_policy=request.cache_policy,
        resume_policy=None
        if request.resume_policy is None
        else dict(request.resume_policy),
        priority=request.priority,
        tags=dict(request.tags),
        module_name=request.module_name,
        workflow_name=request.workflow_name,
        workflow_definition=request.workflow_definition,
    )
