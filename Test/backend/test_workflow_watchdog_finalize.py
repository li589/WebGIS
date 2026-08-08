"""审查 BUG-2：看门狗 failed / 用户 cancelled 不可被成功收口覆盖。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.services.workflow.lifecycle_service import WorkflowLifecycleService
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.transition_builder import WorkflowTransitionBuilder
from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ExecutionStatus,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowResourceProfile,
    WorkflowSubmitRequest,
)


def _payload() -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="watchdog race test",
        priority=WorkflowPriority.normal,
        resource_profile=WorkflowResourceProfile.standard,
        requested_outputs=[],
    )


def test_finalize_success_skips_watchdog_failed(tmp_path: Path) -> None:
    repo = SQLiteWorkflowRepository(state_dir=tmp_path)
    try:
        persistence = WorkflowPersistenceService(repo)
        transitions = WorkflowTransitionBuilder()
        lifecycle = WorkflowLifecycleService(repo, persistence, transitions)
        now = datetime.now(timezone.utc)
        run_id = "run-watchdog-protected"
        payload = _payload()
        persistence.save_run_status(
            run_status=transitions.build_execution_transition(
                run_id=run_id,
                payload=payload,
                status=ExecutionStatus.failed,
                progress=100,
                message="watchdog marked failed",
                created_at=now,
                updated_at=now,
                diagnostics=["error_code=workflow_stuck_running_watchdog"],
                executor_metadata={
                    "cleanup_reason": "stuck_running_watchdog",
                    "watchdog_failed_at": now.isoformat(),
                },
            )
        )

        execution = SimpleNamespace(
            result_refs=[],
            diagnostics=[],
            result_dto=None,
            message="would have succeeded",
            follow_up_tasks=[],
        )
        lifecycle.finalize_workflow_success(
            run_id=run_id,
            payload=payload,
            execution=execution,
            requested_at=now,
        )
        run = repo.get_run(run_id)
        assert run is not None
        assert run.status == ExecutionStatus.failed
        assert run.executor_metadata.get("cleanup_reason") == "stuck_running_watchdog"
    finally:
        repo.close()


def test_finalize_success_skips_cancelled(tmp_path: Path) -> None:
    repo = SQLiteWorkflowRepository(state_dir=tmp_path)
    try:
        persistence = WorkflowPersistenceService(repo)
        transitions = WorkflowTransitionBuilder()
        lifecycle = WorkflowLifecycleService(repo, persistence, transitions)
        now = datetime.now(timezone.utc)
        run_id = "run-cancelled-protected"
        payload = _payload()
        persistence.save_run_status(
            run_status=transitions.build_execution_transition(
                run_id=run_id,
                payload=payload,
                status=ExecutionStatus.cancelled,
                progress=100,
                message="cancelled by user",
                created_at=now,
                updated_at=now,
                diagnostics=["error_code=workflow_cancelled_by_user"],
                executor_metadata={"cancelled_by": "user"},
            )
        )

        execution = SimpleNamespace(
            result_refs=[],
            diagnostics=[],
            result_dto=None,
            message="late success",
            follow_up_tasks=[],
        )
        lifecycle.finalize_workflow_success(
            run_id=run_id,
            payload=payload,
            execution=execution,
            requested_at=now,
        )
        run = repo.get_run(run_id)
        assert run is not None
        assert run.status == ExecutionStatus.cancelled
    finally:
        repo.close()
