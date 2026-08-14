"""Tests for app.services.workflow.queue_dispatch_service.QueueDispatchService.

Covers queue routing (capacity full -> break), per-user capacity skip,
missing/invalid request_json -> fail, CAS-skip for non-queued runs, and
the happy-path dispatch. Uses mock repository + submission service.
"""

from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

from app.services.workflow.queue_dispatch_service import QueueDispatchService
from app.services.workflow.transition_builder import WorkflowTransitionBuilder
from shared.contracts.api_contracts import (
    ExecutionStatus,
    WorkflowCommandType,
    WorkflowSubmitRequest,
)


def _payload() -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="queue dispatch test",
        requested_outputs=[],
    )


def _queued_status(run_id: str) -> object:
    """Build a real queued WorkflowRunStatusResponse (supports model_copy)."""
    transitions = WorkflowTransitionBuilder()
    now = datetime.now(UTC)
    return transitions.build_execution_transition(
        run_id=run_id,
        payload=_payload(),
        status=ExecutionStatus.queued,
        progress=12,
        message="queued",
        created_at=now,
        updated_at=now,
    )


def _queued_run_dict(
    run_id: str, *, request_json: str | None = None, user_id=None
) -> dict:
    return {
        "run_id": run_id,
        "run_class": "business",
        "user_id": user_id,
        "request_json": request_json,
    }


def _submission_mock(capacity: int = 10) -> MagicMock:
    sub = MagicMock()
    sub._workflow_capacity_limit.return_value = capacity
    sub._user_concurrency_limit.return_value = None
    sub._dispatch_async_workflow = MagicMock()
    return sub


# ---------------------------------------------------------------------------
# Empty / capacity
# ---------------------------------------------------------------------------


def test_dispatch_no_queued_returns_zero():
    """No queued runs -> 0 dispatched."""
    repo = MagicMock()
    repo.get_queued_runs.return_value = []
    svc = QueueDispatchService(repo, _submission_mock())
    assert svc.dispatch_queued_workflows() == 0, "no queued runs must yield 0"


def test_dispatch_global_capacity_full_breaks_dispatch():
    """When the global pool is full, dispatch stops immediately (break)."""
    repo = MagicMock()
    repo.get_queued_runs.return_value = [_queued_run_dict("r1")]
    repo.count_active_runs.return_value = 10  # >= capacity 10
    sub = _submission_mock(capacity=10)
    svc = QueueDispatchService(repo, sub)
    assert svc.dispatch_queued_workflows() == 0, "full pool must dispatch 0"
    sub._dispatch_async_workflow.assert_not_called(), (
        "no dispatch when global capacity is reached"
    )


# ---------------------------------------------------------------------------
# request_json validation -> fail queued run
# ---------------------------------------------------------------------------


def test_dispatch_missing_request_json_marks_run_failed():
    """A queued run with no request_json is marked failed (not dispatched)."""
    repo = MagicMock()
    repo.get_queued_runs.return_value = [_queued_run_dict("r1", request_json=None)]
    repo.count_active_runs.return_value = 0
    repo.get_run.return_value = _queued_status("r1")
    sub = _submission_mock()
    svc = QueueDispatchService(repo, sub)

    assert svc.dispatch_queued_workflows() == 0, "missing json must dispatch 0"
    sub._dispatch_async_workflow.assert_not_called(), "must not dispatch invalid run"
    repo.save_run_cas.assert_called_once(), "_fail_queued_run must CAS-save the failure"


def test_dispatch_invalid_request_json_marks_run_failed():
    """A queued run with unparseable request_json is marked failed."""
    repo = MagicMock()
    repo.get_queued_runs.return_value = [_queued_run_dict("r1", request_json="{not json")]
    repo.count_active_runs.return_value = 0
    repo.get_run.return_value = _queued_status("r1")
    sub = _submission_mock()
    svc = QueueDispatchService(repo, sub)

    assert svc.dispatch_queued_workflows() == 0, "invalid json must dispatch 0"
    sub._dispatch_async_workflow.assert_not_called(), "must not dispatch invalid run"
    repo.save_run_cas.assert_called_once(), "invalid run must be CAS-failed"


# ---------------------------------------------------------------------------
# Happy path + CAS skip
# ---------------------------------------------------------------------------


def test_dispatch_success_dispatches_one():
    """A valid queued run under capacity is CAS-transitioned and dispatched."""
    payload = _payload()
    repo = MagicMock()
    repo.get_queued_runs.return_value = [
        _queued_run_dict("r1", request_json=payload.model_dump_json())
    ]
    repo.count_active_runs.return_value = 0
    repo.get_run.return_value = _queued_status("r1")
    sub = _submission_mock(capacity=10)
    svc = QueueDispatchService(repo, sub)

    assert svc.dispatch_queued_workflows() == 1, "one run must be dispatched"
    repo.save_run_cas.assert_called_once(), "CAS queued->accepted must run"
    sub._dispatch_async_workflow.assert_called_once(), (
        "dispatch_async_workflow must be invoked for the accepted run"
    )
    dispatched_run_id = sub._dispatch_async_workflow.call_args.args[0]
    assert dispatched_run_id == "r1", "dispatch must target the queued run id"


def test_dispatch_skips_run_no_longer_queued():
    """If the run's status changed away from queued before CAS, it is skipped."""
    payload = _payload()
    repo = MagicMock()
    repo.get_queued_runs.return_value = [
        _queued_run_dict("r1", request_json=payload.model_dump_json())
    ]
    repo.count_active_runs.return_value = 0
    # current_run is now accepted (another trigger already dispatched it).
    repo.get_run.return_value = _queued_status("r1").model_copy(
        update={"status": ExecutionStatus.accepted}
    )
    sub = _submission_mock()
    svc = QueueDispatchService(repo, sub)

    assert svc.dispatch_queued_workflows() == 0, "non-queued run must dispatch 0"
    sub._dispatch_async_workflow.assert_not_called(), (
        "must not re-dispatch a run that left the queued state"
    )


def test_dispatch_cas_conflict_skips_run():
    """If save_run_cas raises (concurrent dispatch), the run is skipped."""
    payload = _payload()
    repo = MagicMock()
    repo.get_queued_runs.return_value = [
        _queued_run_dict("r1", request_json=payload.model_dump_json())
    ]
    repo.count_active_runs.return_value = 0
    repo.get_run.return_value = _queued_status("r1")
    repo.save_run_cas.side_effect = RuntimeError("CAS conflict")
    sub = _submission_mock()
    svc = QueueDispatchService(repo, sub)

    assert svc.dispatch_queued_workflows() == 0, "CAS conflict must yield 0 dispatched"
    sub._dispatch_async_workflow.assert_not_called(), (
        "must not dispatch when CAS fails"
    )


# ---------------------------------------------------------------------------
# Per-user capacity
# ---------------------------------------------------------------------------


@patch("app.services.user_repository.get_user_repository")
def test_dispatch_user_at_capacity_skips_run(mock_get_user_repo):
    """A run whose owner is at the per-user concurrency limit is skipped."""
    payload = _payload()
    repo = MagicMock()
    repo.get_queued_runs.return_value = [
        _queued_run_dict("r1", request_json=payload.model_dump_json(), user_id=5)
    ]
    repo.count_active_runs.return_value = 0
    repo.get_run.return_value = _queued_status("r1")
    repo.count_active_runs_by_user.return_value = 2  # >= user_limit 2

    mock_get_user_repo.return_value.get_by_id.return_value = {"role": "standard"}
    sub = _submission_mock()
    sub._user_concurrency_limit.return_value = 2
    svc = QueueDispatchService(repo, sub)

    assert svc.dispatch_queued_workflows() == 0, "user-at-capacity run must dispatch 0"
    sub._dispatch_async_workflow.assert_not_called(), (
        "must not dispatch when user is at capacity"
    )
