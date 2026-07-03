from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from contracts.api_errors import build_api_error_response
from contracts.job import JobResult
from runner.dispatch import run_job
from service.async_jobs import AsyncJobStore
from service.job_queue import JobQueueBackend
from service.platform_adapters import TrackingSchedulerAdapter


RunJobFn = Callable[..., JobResult]
AdapterFactory = Callable[[], Any]


class JobQueueWorker:
    def __init__(
        self,
        *,
        job_queue: JobQueueBackend,
        async_job_registry: AsyncJobStore,
        scheduler_adapter_factory: AdapterFactory,
        datasource_adapter_factory: AdapterFactory,
        logger_adapter_factory: AdapterFactory,
        product_sink_factory: AdapterFactory,
        workspace: str | Path | None = None,
        run_job_fn: RunJobFn = run_job,
    ) -> None:
        self._job_queue = job_queue
        self._async_job_registry = async_job_registry
        self._scheduler_adapter_factory = scheduler_adapter_factory
        self._datasource_adapter_factory = datasource_adapter_factory
        self._logger_adapter_factory = logger_adapter_factory
        self._product_sink_factory = product_sink_factory
        self._workspace = None if workspace is None else Path(workspace)
        self._run_job_fn = run_job_fn

    def process_next(self, *, timeout: float | None = None) -> bool:
        item = self._job_queue.dequeue(timeout=timeout)
        if item is None:
            return False
        should_ack = False
        try:
            self._async_job_registry.mark_running(item.submission_id)
            try:
                self._execute_submission(item.submission_id, item.request)
            except Exception as exc:
                self._record_unhandled_failure(item.submission_id, item.request, exc)
            should_ack = True
            return True
        finally:
            if should_ack:
                self._job_queue.task_done()

    def _execute_submission(self, submission_id: str, request) -> None:
        scheduler_adapter = self._scheduler_adapter_factory()
        datasource_adapter = self._datasource_adapter_factory()
        logger_adapter = self._logger_adapter_factory()
        product_sink = self._product_sink_factory()
        tracking_scheduler = TrackingSchedulerAdapter(
            scheduler_adapter,
            on_status=lambda job_id, run_id, status, detail: self._async_job_registry.record_status(
                submission_id,
                job_id=job_id,
                run_id=run_id,
                status=status,
                detail=detail,
            ),
            on_complete=lambda result: self._async_job_registry.record_completion(submission_id, result=result),
        )
        result = self._run_job_fn(
            request,
            tracking_scheduler,
            datasource_adapter,
            logger_adapter,
            product_sink=product_sink,
            workspace=self._workspace,
        )
        if result.status == "success":
            response_status = 200
            response_body = {"job_result": _to_jsonable(result)}
        else:
            response_status = 500
            response_body = {
                "error_type": "job_execution_failed",
                "error_code": "job_execution_failed",
                "http_status": 500,
                "retryable": False,
                "user_message": "任务执行失败，请检查错误摘要、日志和产物清单。",
                "developer_message": result.error_summary or "run_job returned a failed result",
                "job_result": _to_jsonable(result),
            }
        self._async_job_registry.record_response(
            submission_id,
            _RegistryResponse(status_code=response_status, body=response_body),
        )

    def _record_unhandled_failure(self, submission_id: str, request, error: Exception) -> None:
        api_error = build_api_error_response(error, request=request)
        self._async_job_registry.record_response(
            submission_id,
            _RegistryResponse(status_code=api_error.http_status, body=_to_jsonable(api_error)),
        )


class PlatformWorkerLoop:
    def __init__(self, worker: JobQueueWorker) -> None:
        self._worker = worker

    def run_forever(self, *, poll_timeout: float = 0.5) -> None:
        while True:
            self._worker.process_next(timeout=poll_timeout)


class _RegistryResponse:
    def __init__(self, *, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.body = body


def _to_jsonable(value: Any) -> Any:
    from dataclasses import asdict, is_dataclass
    from pathlib import Path

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    return value
