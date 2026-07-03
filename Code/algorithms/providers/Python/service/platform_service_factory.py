from __future__ import annotations

from pathlib import Path
from typing import Callable

from contracts.job import JobResult
from runner.dispatch import run_job
from service.async_jobs import AsyncJobRegistry, AsyncJobStore, FileAsyncJobRegistry
from service.job_api import JobService
from service.job_queue import InMemoryJobQueue, JobQueueBackend
from service.platform_client_mock import PlatformClientMock
from service.platform_datasource_adapter import PlatformDataSourceAdapter
from service.platform_http_client import PlatformHttpClient, build_platform_http_client_from_env
from service.platform_job_queue import PlatformJobQueue
from service.platform_logger_adapter import PlatformLoggerAdapter
from service.platform_product_sink import PlatformProductSink
from service.platform_scheduler_adapter import PlatformSchedulerAdapter
from service.worker import JobQueueWorker


RunJobFn = Callable[..., JobResult]


def build_platform_job_service(
    *,
    platform_client,
    workspace: str | Path | None = None,
    run_job_fn: RunJobFn = run_job,
    async_job_registry: AsyncJobStore | None = None,
    job_queue: JobQueueBackend | None = None,
    use_platform_queue: bool = False,
    start_worker: bool = True,
) -> tuple[JobService, JobQueueWorker]:
    resolved_workspace = None if workspace is None else Path(workspace)
    async_registry = async_job_registry or AsyncJobRegistry()
    queue_backend = job_queue or _build_default_queue(platform_client, use_platform_queue=use_platform_queue)
    service = JobService(
        scheduler_adapter_factory=lambda: PlatformSchedulerAdapter(platform_client=platform_client),
        datasource_adapter_factory=lambda: PlatformDataSourceAdapter(platform_client=platform_client),
        logger_adapter_factory=lambda: PlatformLoggerAdapter(platform_client=platform_client),
        product_sink_factory=lambda: PlatformProductSink(platform_client=platform_client),
        workspace=resolved_workspace,
        run_job_fn=run_job_fn,
        async_job_registry=async_registry,
        job_queue=queue_backend,
    )
    worker = JobQueueWorker(
        job_queue=queue_backend,
        async_job_registry=async_registry,
        scheduler_adapter_factory=lambda: PlatformSchedulerAdapter(platform_client=platform_client),
        datasource_adapter_factory=lambda: PlatformDataSourceAdapter(platform_client=platform_client),
        logger_adapter_factory=lambda: PlatformLoggerAdapter(platform_client=platform_client),
        product_sink_factory=lambda: PlatformProductSink(platform_client=platform_client),
        workspace=resolved_workspace,
        run_job_fn=run_job_fn,
    )
    if start_worker:
        import threading

        thread = threading.Thread(target=lambda: _run_worker_forever(worker), daemon=True)
        thread.start()
    return service, worker


def build_platform_mock_service(
    *,
    workspace: str | Path | None = None,
    run_job_fn: RunJobFn = run_job,
    async_job_registry: AsyncJobStore | None = None,
    job_queue: JobQueueBackend | None = None,
    use_platform_queue: bool = True,
    start_worker: bool = True,
) -> tuple[JobService, JobQueueWorker, PlatformClientMock]:
    platform_client = PlatformClientMock()
    service, worker = build_platform_job_service(
        platform_client=platform_client,
        workspace=workspace,
        run_job_fn=run_job_fn,
        async_job_registry=async_job_registry,
        job_queue=job_queue,
        use_platform_queue=use_platform_queue,
        start_worker=start_worker,
    )
    return service, worker, platform_client


def build_platform_http_job_service(
    *,
    workspace: str | Path,
    base_url: str | None = None,
    token: str | None = None,
    timeout: float | None = None,
    run_job_fn: RunJobFn = run_job,
    async_job_registry: AsyncJobStore | None = None,
    use_platform_queue: bool = True,
    start_worker: bool = True,
) -> tuple[JobService, JobQueueWorker, PlatformHttpClient]:
    resolved_workspace = Path(workspace)
    async_registry = async_job_registry or FileAsyncJobRegistry(
        resolved_workspace / "service_state" / "submissions"
    )
    platform_client = build_platform_http_client_from_env(
        base_url=base_url,
        token=token,
        timeout=timeout,
    )
    service, worker = build_platform_job_service(
        platform_client=platform_client,
        workspace=resolved_workspace,
        run_job_fn=run_job_fn,
        async_job_registry=async_registry,
        use_platform_queue=use_platform_queue,
        start_worker=start_worker,
    )
    return service, worker, platform_client


def _build_default_queue(platform_client, *, use_platform_queue: bool) -> JobQueueBackend:
    if use_platform_queue:
        return PlatformJobQueue(platform_client=platform_client)
    return InMemoryJobQueue()


def _run_worker_forever(worker: JobQueueWorker) -> None:
    while True:
        worker.process_next(timeout=0.2)
