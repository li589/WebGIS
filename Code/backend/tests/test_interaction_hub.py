from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.interaction_hub import InMemoryInteractionHub
from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ExecutionStatus,
    WorkflowAnalysisResultDto,
    WorkflowAcceptedResponse,
    WorkflowCommandType,
    WorkflowDownloadResultDto,
    WorkflowPriority,
    WorkflowProviderResultDto,
    WorkflowResultReference,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
    RuntimeMapContext,
    ClientIdentity,
)


class InteractionHubTests(unittest.TestCase):
    def _build_payload(self, command_type: WorkflowCommandType) -> WorkflowSubmitRequest:
        return WorkflowSubmitRequest(
            command_type=command_type,
            layer_id="wind-field",
            priority=WorkflowPriority.normal,
            requested_outputs=[],
            client=ClientIdentity(client_id="test-client"),
            map_context=RuntimeMapContext(active_layer_id="wind-field"),
        )

    def test_submit_workflow_creates_accepted_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hub = InMemoryInteractionHub(SQLiteWorkflowRepository(state_dir=Path(tmpdir)))
            response = hub.submit_workflow(self._build_payload(WorkflowCommandType.analysis))

            self.assertIsInstance(response, WorkflowAcceptedResponse)
            run = hub.get_workflow_run(response.run_id)
            self.assertIsNotNone(run)
            self.assertEqual(run.status, ExecutionStatus.succeeded)
            self.assertEqual(run.status_url, f"/workflow-runs/{response.run_id}")
            self.assertEqual(run.events_url, f"/workflow-runs/{response.run_id}/events")

    def test_cancel_workflow_marks_terminal_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hub = InMemoryInteractionHub(SQLiteWorkflowRepository(state_dir=Path(tmpdir)))
            response = hub.submit_workflow(self._build_payload(WorkflowCommandType.analysis))
            cancelled = hub.cancel_workflow_run(response.run_id)

            self.assertEqual(cancelled.status, ExecutionStatus.cancelled)
            self.assertGreaterEqual(cancelled.progress, 100)

    def test_runtime_status_reports_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hub = InMemoryInteractionHub(SQLiteWorkflowRepository(state_dir=Path(tmpdir)))
            status = hub.get_runtime_status()

            self.assertEqual(status.service_name, "Comprehensive Geographic Data Analysis system")
            self.assertGreaterEqual(len(status.services), 3)


if __name__ == "__main__":
    unittest.main()
