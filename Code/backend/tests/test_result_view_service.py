from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
import unittest

from app.services.result_view_service import ResultViewService
from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ClientIdentity,
    ExecutionStatus,
    ResultKind,
    RuntimeMapContext,
    WorkflowAnalysisResultDto,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowResourceProfile,
    WorkflowResultReference,
    WorkflowRunStatusResponse,
)


class ResultViewServiceTests(unittest.TestCase):
    def test_builds_view_model_from_run_status(self) -> None:
        tmpdir = Path(tempfile.mkdtemp())
        try:
            repository = SQLiteWorkflowRepository(state_dir=tmpdir)
            service = ResultViewService(repository)
            now = datetime.now(timezone.utc)
            run = WorkflowRunStatusResponse(
                run_id="run-1",
                status_url="/workflow-runs/run-1",
                events_url="/workflow-runs/run-1/events",
                command_type=WorkflowCommandType.analysis,
                command_label="analysis test",
                layer_id="wind-field",
                priority=WorkflowPriority.normal,
                resource_profile=WorkflowResourceProfile.standard,
                status=ExecutionStatus.succeeded,
                progress=100,
                message="done",
                created_at=now,
                updated_at=now,
                client=ClientIdentity(client_id="client-1"),
                map_context=RuntimeMapContext(active_layer_id="wind-field"),
                result_dto=WorkflowAnalysisResultDto(
                    workflow_entry_name="analysis_workflow",
                    layer_id="wind-field",
                    metric_label="NDVI",
                    metric_value=0.74,
                    metric_unit="index",
                    hotspot_count=5,
                    result_category="analysis",
                ),
                result_refs=[
                    WorkflowResultReference(
                        result_id="ref-1",
                        result_kind=ResultKind.json,
                        title="json result",
                        mime_type="application/json",
                        resource_url="https://example.test/artifacts/ref-1",
                        updated_at=now,
                    )
                ],
            )
            repository.save_run(run)

            view = service.get_workflow_run_view("run-1")
            self.assertIsNotNone(view)
            self.assertEqual(view.run_id, "run-1")
            self.assertEqual(view.title, "analysis_workflow")
            self.assertEqual(view.subtitle, "wind-field")
            self.assertEqual(view.status_text, "done")
            self.assertEqual(view.progress_text, "100%")
            self.assertTrue(view.can_show_link)
            self.assertEqual(view.result_url, "https://example.test/artifacts/ref-1")
            self.assertGreaterEqual(len(view.metric_rows), 4)
            self.assertEqual(view.metric_rows[0].label, "Entry")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
