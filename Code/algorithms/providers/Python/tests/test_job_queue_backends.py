from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from contracts.job import JobResult
from contracts.serialization import coerce_job_request
from service.job_api import build_local_persistent_job_service, build_worker
from service.job_queue import FileJobQueue
from service.platform_job_queue import CallbackJobQueueBackend, PlatformJobQueue


def _build_valid_payload() -> dict[str, object]:
    return {
        "job_id": "file-queue-job-001",
        "pipeline_name": "workflow",
        "workflow_name": "retrieval_workflow",
        "task_type": "retrieval",
        "time_range": {
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-02T00:00:00Z",
        },
        "region": {
            "kind": "global",
            "value": {},
        },
        "datasource_selection": {
            "omega_fixed_mat": "D:/data/omega_fixed.mat",
            "exp0_calib_mat": "D:/data/exp0_calib.mat",
        },
        "algorithm_params": {
            "mode": "omega",
        },
    }


class JobQueueBackendTests(unittest.TestCase):
    def test_file_job_queue_supports_cross_instance_enqueue_and_dequeue(self) -> None:
        root_dir = tempfile.mkdtemp()
        queue_a = FileJobQueue(root_dir)
        queue_b = FileJobQueue(root_dir)
        request = coerce_job_request(_build_valid_payload())

        item = queue_a.enqueue(
            "submission-file-001",
            request,
        )
        claimed = queue_b.dequeue(timeout=0.01)

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.submission_id, item.submission_id)
        self.assertEqual(claimed.request.job_id, "file-queue-job-001")
        queue_b.task_done()
        self.assertEqual(list((Path(root_dir) / "pending").glob("*.json")), [])
        self.assertEqual(list((Path(root_dir) / "inflight").glob("*.json")), [])

    def test_persistent_service_and_worker_can_share_file_queue(self) -> None:
        workspace = tempfile.mkdtemp()
        queue_root = Path(workspace) / "service_state" / "queue"

        def fake_run_job(request, scheduler_adapter, datasource_adapter, logger_adapter, product_sink=None, workspace=None):
            scheduler_adapter.update_status(request.job_id, "run-file-001", "running", {"backend": "file"})
            result = JobResult(
                job_id=request.job_id,
                run_id="run-file-001",
                status="success",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
                manifest_uri="memory://run-file-001.json",
            )
            scheduler_adapter.complete(result)
            return result

        submit_service = build_local_persistent_job_service(
            workspace=workspace,
            job_queue=FileJobQueue(queue_root),
            run_job_fn=fake_run_job,
            start_worker=False,
        )
        worker_service = build_local_persistent_job_service(
            workspace=workspace,
            job_queue=FileJobQueue(queue_root),
            run_job_fn=fake_run_job,
            start_worker=False,
        )

        accepted = submit_service.submit_job_async(_build_valid_payload())
        worker = build_worker(worker_service)
        processed = worker.process_next(timeout=0.01)
        snapshot = submit_service.get_job_status(accepted.body["submission_id"])

        self.assertEqual(accepted.status_code, 202)
        self.assertTrue(processed)
        self.assertEqual(snapshot.status_code, 200)
        self.assertEqual(snapshot.body["state"], "completed")
        self.assertEqual(snapshot.body["run_id"], "run-file-001")
        self.assertEqual(snapshot.body["job_result"]["status"], "success")

    def test_platform_job_queue_supports_callback_and_client_styles(self) -> None:
        published: list[str] = []
        claimed_items = []
        acked: list[str] = []

        callback_queue = CallbackJobQueueBackend(
            publish_submission_fn=lambda item: published.append(item.submission_id),
            claim_submission_fn=lambda timeout: claimed_items.pop(0) if claimed_items else None,
            ack_submission_fn=lambda item: acked.append(item.submission_id),
        )

        request = coerce_job_request(_build_valid_payload())
        queued_item = callback_queue.enqueue("submission-callback-001", request)
        claimed_items.append(queued_item)
        claimed = callback_queue.dequeue(timeout=0.01)
        callback_queue.task_done()

        self.assertEqual(published, ["submission-callback-001"])
        self.assertIsNotNone(claimed)
        self.assertEqual(acked, ["submission-callback-001"])

        class _Client:
            def __init__(self) -> None:
                self.published: list[str] = []
                self.claimed: list[object] = []
                self.acked: list[str] = []

            def publish_submission(self, item) -> None:
                self.published.append(item.submission_id)
                self.claimed.append(item)

            def claim_submission(self, *, timeout=None):
                _ = timeout
                return self.claimed.pop(0) if self.claimed else None

            def ack_submission(self, item) -> None:
                self.acked.append(item.submission_id)

        client = _Client()
        platform_queue = PlatformJobQueue(platform_client=client)
        platform_queue.enqueue("submission-platform-001", request)
        claimed_platform = platform_queue.dequeue(timeout=0.01)
        platform_queue.task_done()

        self.assertIsNotNone(claimed_platform)
        self.assertEqual(client.published, ["submission-platform-001"])
        self.assertEqual(client.acked, ["submission-platform-001"])


if __name__ == "__main__":
    unittest.main()
