from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime

from contracts.data import DataBundle
from contracts.job import JobResult
from contracts.runtime import TimeRange
from service.platform_service_factory import build_platform_mock_service


def _build_async_payload() -> dict[str, object]:
    return {
        "job_id": "platform-mock-job-001",
        "pipeline_name": "workflow",
        "module_name": "ndvi_daily",
        "task_type": "ndvi_daily",
        "time_range": {
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-02T00:00:00Z",
        },
        "region": {
            "kind": "global",
            "value": {},
        },
        "datasource_selection": {
            "input_dir": "D:/platform/input",
        },
        "algorithm_params": {},
    }


class PlatformMockIntegrationTests(unittest.TestCase):
    def test_platform_mock_service_runs_async_job_end_to_end(self) -> None:
        workspace = tempfile.mkdtemp()

        def fake_run_job(
            request,
            scheduler_adapter,
            datasource_adapter,
            logger_adapter,
            product_sink=None,
            workspace=None,
        ):
            scheduler_adapter.get_run_context(request)
            scheduler_adapter.update_status(
                request.job_id, "run-mock-001", "planning", {"queue": "mock"}
            )
            result = JobResult(
                job_id=request.job_id,
                run_id="run-mock-001",
                status="success",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
                manifest_uri="memory://manifests/run-mock-001.json",
            )
            scheduler_adapter.complete(result)
            return result

        service, worker, platform_client = build_platform_mock_service(
            workspace=workspace,
            run_job_fn=fake_run_job,
            start_worker=False,
        )

        response = service.submit_job_async(_build_async_payload())
        self.assertEqual(response.status_code, 202)
        submission_id = response.body["submission_id"]
        self.assertEqual(len(platform_client.queued_submissions), 1)
        self.assertEqual(
            platform_client.queued_submissions[0].submission_id, submission_id
        )

        processed = worker.process_next(timeout=0.01)
        self.assertTrue(processed)

        status_response = service.get_job_status(submission_id)
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.body["state"], "completed")
        self.assertEqual(status_response.body["job_result"]["status"], "success")
        self.assertEqual(status_response.body["run_id"], "run-mock-001")
        self.assertEqual(platform_client.status_events[0]["status"], "planning")
        self.assertEqual(platform_client.completed_results[0].run_id, "run-mock-001")
        self.assertEqual(platform_client.acked_submissions, [submission_id])

    def test_platform_mock_client_can_preload_bundle_records(self) -> None:
        service, worker, platform_client = build_platform_mock_service(
            workspace=tempfile.mkdtemp(),
            run_job_fn=lambda *args, **kwargs: JobResult(
                job_id="x",
                run_id="y",
                status="success",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
            ),
            start_worker=False,
        )
        _ = (service, worker)

        platform_client.register_bundle(
            "demo_dataset",
            DataBundle(
                bundle_id="bundle-demo",
                dataset_name="demo_dataset",
                variables=["v1"],
                time_range=TimeRange(
                    start=datetime(2025, 1, 1), end=datetime(2025, 1, 2)
                ),
                storage_mode="lazy",
            ),
        )

        bundle = platform_client.resolve_bundle(
            type(
                "Request",
                (),
                {
                    "dataset_name": "demo_dataset",
                    "variables": ["v1"],
                    "time_range": TimeRange(
                        start=datetime(2025, 1, 1), end=datetime(2025, 1, 2)
                    ),
                    "acquire_mode": "lazy",
                },
            )()
        )

        self.assertEqual(bundle.bundle_id, "bundle-demo")

    def test_platform_job_service_can_disable_platform_queue_and_fall_back_to_in_memory(
        self,
    ) -> None:
        service, worker, platform_client = build_platform_mock_service(
            workspace=tempfile.mkdtemp(),
            run_job_fn=lambda *args, **kwargs: JobResult(
                job_id="x",
                run_id="y",
                status="success",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
            ),
            use_platform_queue=False,
            start_worker=False,
        )
        _ = worker

        response = service.submit_job_async(_build_async_payload())

        self.assertEqual(response.status_code, 202)
        self.assertEqual(platform_client.queued_submissions, [])
        self.assertEqual(platform_client.acked_submissions, [])


if __name__ == "__main__":
    unittest.main()
