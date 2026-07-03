from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime

from contracts.job import JobResult
from service.async_jobs import FileAsyncJobRegistry


class _Response:
    def __init__(self, *, status_code: int, body: dict[str, object]) -> None:
        self.status_code = status_code
        self.body = body


class FileAsyncJobRegistryTests(unittest.TestCase):
    def test_file_registry_persists_submission_state_across_instances(self) -> None:
        root_dir = tempfile.mkdtemp()
        registry = FileAsyncJobRegistry(root_dir)
        record = registry.create_submission("persisted-job-001")

        registry.mark_queued(record.submission_id)
        registry.record_status(
            record.submission_id,
            job_id="persisted-job-001",
            run_id="run-persist-001",
            status="running",
            detail={"queue": "disk"},
        )
        result = JobResult(
            job_id="persisted-job-001",
            run_id="run-persist-001",
            status="success",
            started_at=datetime(2025, 1, 1, tzinfo=UTC),
            finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
            manifest_uri="memory://persisted-manifest.json",
        )
        registry.record_completion(record.submission_id, result=result)
        registry.record_response(
            record.submission_id,
            _Response(
                status_code=200,
                body={
                    "job_result": {
                        "job_id": "persisted-job-001",
                        "run_id": "run-persist-001",
                        "status": "success",
                    }
                },
            ),
        )

        reopened_registry = FileAsyncJobRegistry(root_dir)
        snapshot = reopened_registry.get_submission(record.submission_id)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.state, "completed")
        self.assertEqual(snapshot.job_id, "persisted-job-001")
        self.assertEqual(snapshot.run_id, "run-persist-001")
        self.assertEqual(snapshot.scheduler_status, "running")
        self.assertEqual(snapshot.status_detail["queue"], "disk")
        self.assertEqual(snapshot.final_response_status, 200)
        self.assertEqual(snapshot.job_result.status, "success")
        self.assertTrue(snapshot.job_result.started_at.tzinfo is not None)

    def test_file_registry_marks_failed_when_only_error_response_is_recorded(self) -> None:
        registry = FileAsyncJobRegistry(tempfile.mkdtemp())
        record = registry.create_submission("failed-job-001")

        registry.record_response(
            record.submission_id,
            _Response(
                status_code=500,
                body={"error_code": "job_execution_failed"},
            ),
        )

        snapshot = registry.get_submission(record.submission_id)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.state, "failed")
        self.assertEqual(snapshot.final_response_status, 500)


if __name__ == "__main__":
    unittest.main()
