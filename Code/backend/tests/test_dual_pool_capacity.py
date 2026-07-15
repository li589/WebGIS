"""Tests for dual-pool run_class capacity helpers and repository counting."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.workflow.run_class import (
    RUN_CLASS_BUSINESS,
    RUN_CLASS_WEATHER_TILE,
    resolve_workflow_run_class,
)
from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ClientIdentity,
    ExecutionStatus,
    RuntimeMapContext,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
)


def _status(run_id: str, status: ExecutionStatus = ExecutionStatus.running) -> WorkflowRunStatusResponse:
    now = datetime.now(timezone.utc)
    return WorkflowRunStatusResponse(
        run_id=run_id,
        status_url=f"/workflow-runs/{run_id}",
        events_url=f"/workflow-runs/{run_id}/events",
        command_type=WorkflowCommandType.analysis,
        layer_id="wind-field",
        priority=WorkflowPriority.normal,
        status=status,
        progress=10,
        message="running",
        created_at=now,
        updated_at=now,
        client=ClientIdentity(client_id="client-1"),
        map_context=RuntimeMapContext(active_layer_id="wind-field"),
    )


class RunClassResolverTests(unittest.TestCase):
    def test_business_default(self) -> None:
        payload = WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            layer_id="lab-output",
            requested_outputs=["json"],
        )
        self.assertEqual(resolve_workflow_run_class(payload), RUN_CLASS_BUSINESS)

    def test_weather_tile_node_classifies_as_weather_tile(self) -> None:
        payload = WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            layer_id="wind-field",
            requested_outputs=["json"],
            weather_request={
                "workflow_id": "wf-tile",
                "workflow": {
                    "workflow_id": "wf-tile",
                    "nodes": [
                        {
                            "node_id": "tile-render",
                            "node_type": "weather_tile_render",
                            "params": {"layer_id": "wind-field", "z": 3, "x": 1, "y": 2},
                        }
                    ],
                    "edges": [],
                },
            },
        )
        self.assertEqual(resolve_workflow_run_class(payload), RUN_CLASS_WEATHER_TILE)


class DualPoolRepositoryTests(unittest.TestCase):
    def test_count_active_runs_filters_by_run_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            repository.save_run(_status("run-biz-1"), request_json="{}", run_class=RUN_CLASS_BUSINESS)
            repository.save_run(_status("run-biz-2"), request_json="{}", run_class=RUN_CLASS_BUSINESS)
            repository.save_run(
                _status("run-tile-1"),
                request_json="{}",
                run_class=RUN_CLASS_WEATHER_TILE,
            )
            repository.save_run(
                _status("run-done", status=ExecutionStatus.succeeded),
                request_json="{}",
                run_class=RUN_CLASS_BUSINESS,
            )

            self.assertEqual(repository.count_active_runs(), 3)
            self.assertEqual(repository.count_active_runs(run_class=RUN_CLASS_BUSINESS), 2)
            self.assertEqual(repository.count_active_runs(run_class=RUN_CLASS_WEATHER_TILE), 1)

    def test_status_update_preserves_run_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            repository.save_run(
                _status("run-tile"),
                request_json="{}",
                run_class=RUN_CLASS_WEATHER_TILE,
            )
            repository.save_run(_status("run-tile", status=ExecutionStatus.running))
            self.assertEqual(repository.count_active_runs(run_class=RUN_CLASS_WEATHER_TILE), 1)
            self.assertEqual(repository.count_active_runs(run_class=RUN_CLASS_BUSINESS), 0)


if __name__ == "__main__":
    unittest.main()
