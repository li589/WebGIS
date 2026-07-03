from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ExecutionStatus,
    EventChannel,
    ResultKind,
    WorkflowAnalysisResultDto,
    WorkflowDownloadResultDto,
    WorkflowEvent,
    WorkflowPriority,
    WorkflowProviderResultDto,
    WorkflowResultReference,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
    WorkflowCommandType,
    RuntimeMapContext,
    ClientIdentity,
)


class WorkflowRepositoryTests(unittest.TestCase):
    def test_save_and_load_workflow_run_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            now = datetime.now(timezone.utc)
            payload = WorkflowRunStatusResponse(
                run_id="run-test",
                status_url="/workflow-runs/run-test",
                events_url="/workflow-runs/run-test/events",
                command_type=WorkflowCommandType.analysis,
                layer_id="wind-field",
                priority=WorkflowPriority.normal,
                status=ExecutionStatus.running,
                progress=35,
                message="running",
                created_at=now,
                updated_at=now,
                client=ClientIdentity(client_id="client-1"),
                map_context=RuntimeMapContext(active_layer_id="wind-field"),
                result_dto=WorkflowAnalysisResultDto(
                    workflow_entry_name="analysis_workflow",
                    layer_id="wind-field",
                    requested_hour=12.0,
                    metric_label="NDVI",
                    metric_value=0.7,
                    metric_unit="index",
                    hotspot_count=2,
                ),
                result_refs=[
                    WorkflowResultReference(
                        result_id="ref-1",
                        result_kind=ResultKind.json,
                        title="result",
                        mime_type="application/json",
                        inline_data={"ok": True},
                        updated_at=now,
                    )
                ],
                diagnostics=["ok"],
            )

            repository.save_run(payload, request_json="{}")
            loaded = repository.get_run("run-test")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.run_id, payload.run_id)
            self.assertEqual(loaded.status, payload.status)
            self.assertEqual(loaded.result_dto.workflow_entry_name, "analysis_workflow")
            self.assertEqual(repository.get_run_request_json("run-test"), "{}")

    def test_append_and_list_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            now = datetime.now(timezone.utc)
            event = WorkflowEvent(
                event_id="evt-1",
                run_id="run-test",
                channel=EventChannel.status,
                message="created",
                created_at=now,
            )
            repository.append_event(event)

            events = repository.list_events("run-test")
            self.assertIsNotNone(events)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_id, "evt-1")
            self.assertEqual(events[0].channel, EventChannel.status)


if __name__ == "__main__":
    unittest.main()
