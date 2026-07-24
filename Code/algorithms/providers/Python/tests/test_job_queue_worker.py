from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime

from contracts.job import JobRequest, JobResult
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, TimeRange
from service.async_jobs import AsyncJobRegistry
from service.job_queue import InMemoryJobQueue
from service.worker import JobQueueWorker
from utils.local_adapters import (
    ConsoleLoggerAdapter,
    LocalDataSourceAdapter,
    LocalProductSink,
    LocalSchedulerAdapter,
)


def _build_request() -> JobRequest:
    return JobRequest(
        job_id="queued-job-001",
        pipeline_name="workflow",
        task_type="workflow",
        time_range=TimeRange(start=datetime(2025, 1, 1), end=datetime(2025, 1, 2)),
        region=RegionSpec(kind="global", value={}),
        datasource_selection={},
        algorithm_params={},
        output_spec=OutputSpec(),
        module_name="ndvi_daily",
    )


class JobQueueWorkerTests(unittest.TestCase):
    def test_process_next_consumes_queue_and_updates_registry(self) -> None:
        workspace = tempfile.mkdtemp()
        registry = AsyncJobRegistry()
        job_queue = InMemoryJobQueue()
        request = _build_request()
        record = registry.create_submission(request.job_id)
        registry.mark_queued(record.submission_id)
        job_queue.enqueue(record.submission_id, request)

        def fake_run_job(
            request,
            scheduler_adapter,
            datasource_adapter,
            logger_adapter,
            product_sink=None,
            workspace=None,
        ):
            scheduler_adapter.update_status(
                request.job_id, "run-worker-001", "running", {"stage": "dispatch"}
            )
            result = JobResult(
                job_id=request.job_id,
                run_id="run-worker-001",
                status="success",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 0, 5, tzinfo=UTC),
                manifest_uri="memory://run-worker-001.json",
            )
            scheduler_adapter.complete(result)
            return result

        worker = JobQueueWorker(
            job_queue=job_queue,
            async_job_registry=registry,
            scheduler_adapter_factory=LocalSchedulerAdapter,
            datasource_adapter_factory=LocalDataSourceAdapter,
            logger_adapter_factory=ConsoleLoggerAdapter,
            product_sink_factory=lambda: LocalProductSink(workspace),
            workspace=workspace,
            run_job_fn=fake_run_job,
        )

        processed = worker.process_next(timeout=0.01)
        snapshot = registry.get_submission(record.submission_id)

        self.assertTrue(processed)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.state, "completed")
        self.assertEqual(snapshot.scheduler_status, "running")
        self.assertEqual(snapshot.run_id, "run-worker-001")
        self.assertEqual(snapshot.final_response_status, 200)
        self.assertEqual(snapshot.job_result.status, "success")

    def test_process_next_returns_false_when_queue_is_empty(self) -> None:
        worker = JobQueueWorker(
            job_queue=InMemoryJobQueue(),
            async_job_registry=AsyncJobRegistry(),
            scheduler_adapter_factory=LocalSchedulerAdapter,
            datasource_adapter_factory=LocalDataSourceAdapter,
            logger_adapter_factory=ConsoleLoggerAdapter,
            product_sink_factory=lambda: None,
            workspace=tempfile.mkdtemp(),
            run_job_fn=lambda *args, **kwargs: None,
        )

        processed = worker.process_next(timeout=0.01)

        self.assertFalse(processed)

    def test_process_next_records_failed_response_for_unhandled_exception(self) -> None:
        workspace = tempfile.mkdtemp()
        registry = AsyncJobRegistry()
        job_queue = InMemoryJobQueue()
        request = _build_request()
        record = registry.create_submission(request.job_id)
        registry.mark_queued(record.submission_id)
        job_queue.enqueue(record.submission_id, request)

        worker = JobQueueWorker(
            job_queue=job_queue,
            async_job_registry=registry,
            scheduler_adapter_factory=LocalSchedulerAdapter,
            datasource_adapter_factory=LocalDataSourceAdapter,
            logger_adapter_factory=ConsoleLoggerAdapter,
            product_sink_factory=lambda: None,
            workspace=workspace,
            run_job_fn=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("boom")
            ),
        )

        processed = worker.process_next(timeout=0.01)
        snapshot = registry.get_submission(record.submission_id)
        processed_again = worker.process_next(timeout=0.01)

        self.assertTrue(processed)
        self.assertFalse(processed_again)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.state, "failed")
        self.assertEqual(snapshot.final_response_status, 500)
        self.assertEqual(
            snapshot.final_response_body["error_code"], "internal_server_error"
        )
        self.assertEqual(snapshot.final_response_body["developer_message"], "boom")


if __name__ == "__main__":
    unittest.main()
