"""Tests for app.services.workflow.follow_up_dispatch_service.FollowUpDispatchService.

Covers dispatch_follow_up_tasks (task_type filtering, inline dispatch,
multi-task, error handling) and fail_stuck_running_workflows / cleanup
using a real temp-dir repository for the watchdog paths.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from app.services.workflow.follow_up_dispatch_service import FollowUpDispatchService
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.transition_builder import WorkflowTransitionBuilder
from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ExecutionStatus,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowSubmitRequest,
)


def _payload() -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="follow-up test",
        priority=WorkflowPriority.normal,
        requested_outputs=[],
    )


# ---------------------------------------------------------------------------
# dispatch_follow_up_tasks (mock persistence + patched celery helpers)
# ---------------------------------------------------------------------------


def _mock_service() -> tuple[FollowUpDispatchService, MagicMock]:
    repo = MagicMock()
    persistence = MagicMock()
    transitions = MagicMock()
    svc = FollowUpDispatchService(repo, persistence, transitions)
    return svc, persistence


@patch("app.services.workflow.follow_up_dispatch_service.execute_download_follow_up_task")
@patch("app.services.workflow.follow_up_dispatch_service.resolve_workflow_queue")
def test_dispatch_filters_non_download_tasks(mock_resolve_queue, mock_execute):
    """Tasks whose task_type is not download_fetch* are skipped entirely."""
    mock_resolve_queue.return_value = "q"
    svc, persistence = _mock_service()
    svc.dispatch_follow_up_tasks(
        run_id="run-1",
        payload=_payload(),
        follow_up_tasks=[{"task_type": "unknown_type"}, {"task_type": "compute"}],
        created_at=datetime.now(UTC),
    )
    mock_execute.assert_not_called(), "non-download tasks must not be dispatched"
    persistence.record_event.assert_not_called(), (
        "no events for filtered-out tasks"
    )


@patch("app.services.workflow.follow_up_dispatch_service.execute_download_follow_up_task")
@patch("app.services.workflow.follow_up_dispatch_service.resolve_workflow_queue")
def test_dispatch_empty_list_is_noop(mock_resolve_queue, mock_execute):
    """An empty follow_up_tasks list dispatches nothing."""
    mock_resolve_queue.return_value = "q"
    svc, persistence = _mock_service()
    svc.dispatch_follow_up_tasks(
        run_id="run-1",
        payload=_payload(),
        follow_up_tasks=[],
        created_at=datetime.now(UTC),
    )
    mock_execute.assert_not_called(), "empty list must not trigger execution"
    persistence.record_event.assert_not_called(), "empty list must record no events"


@patch("app.services.workflow.follow_up_dispatch_service.execute_download_follow_up_task")
@patch("app.services.workflow.follow_up_dispatch_service.resolve_workflow_queue")
def test_dispatch_inline_executes_download_fetch(mock_resolve_queue, mock_execute):
    """A download_fetch task is executed inline (sync executor) and an event recorded."""
    mock_resolve_queue.return_value = "q"
    svc, persistence = _mock_service()
    svc.dispatch_follow_up_tasks(
        run_id="run-1",
        payload=_payload(),
        follow_up_tasks=[{"task_type": "download_fetch", "uri": "demo://x"}],
        created_at=datetime.now(UTC),
    )
    mock_execute.assert_called_once(), "download_fetch must be executed inline"
    # An inline-completion event must be recorded.
    assert persistence.record_event.call_count == 1, (
        "exactly one completion event must be recorded"
    )
    kwargs = persistence.record_event.call_args.kwargs
    assert kwargs["run_id"] == "run-1", "event must be scoped to the run"
    assert "download follow-up" in kwargs["message"].lower() or "完成" in kwargs["message"], (
        "event message must mention follow-up completion"
    )


@patch("app.services.workflow.follow_up_dispatch_service.execute_download_follow_up_task")
@patch("app.services.workflow.follow_up_dispatch_service.resolve_workflow_queue")
def test_dispatch_multiple_tasks_all_dispatched(mock_resolve_queue, mock_execute):
    """Multiple download_fetch tasks are each dispatched exactly once."""
    mock_resolve_queue.return_value = "q"
    svc, persistence = _mock_service()
    tasks = [
        {"task_type": "download_fetch", "uri": "demo://a"},
        {"task_type": "download_fetch_placeholder"},
        {"task_type": "ignored"},
        {"task_type": "download_fetch", "uri": "demo://b"},
    ]
    svc.dispatch_follow_up_tasks(
        run_id="run-multi",
        payload=_payload(),
        follow_up_tasks=tasks,
        created_at=datetime.now(UTC),
    )
    assert mock_execute.call_count == 3, (
        "exactly 3 download_fetch* tasks must be dispatched (ignored filtered out)"
    )


@patch("app.services.workflow.follow_up_dispatch_service.execute_download_follow_up_task")
@patch("app.services.workflow.follow_up_dispatch_service.resolve_workflow_queue")
def test_dispatch_error_records_failure_event(mock_resolve_queue, mock_execute):
    """When inline execution raises, an error-level event is recorded (not propagated)."""
    mock_resolve_queue.return_value = "q"
    mock_execute.side_effect = RuntimeError("fetch blew up")
    svc, persistence = _mock_service()
    # Must not raise.
    svc.dispatch_follow_up_tasks(
        run_id="run-err",
        payload=_payload(),
        follow_up_tasks=[{"task_type": "download_fetch"}],
        created_at=datetime.now(UTC),
    )
    assert persistence.record_event.call_count == 1, "an error event must be recorded"
    kwargs = persistence.record_event.call_args.kwargs
    assert kwargs.get("level") is not None, "error event must carry a level"
    assert "派发失败" in kwargs["message"], "event message must mention dispatch failure"


# ---------------------------------------------------------------------------
# fail_stuck_running_workflows (real repo)
# ---------------------------------------------------------------------------


def _real_services(tmpdir: str):
    repository = SQLiteWorkflowRepository(state_dir=tmpdir)
    persistence = WorkflowPersistenceService(repository)
    transitions = WorkflowTransitionBuilder()
    svc = FollowUpDispatchService(repository, persistence, transitions)
    return repository, persistence, transitions, svc


def test_fail_stuck_running_marks_old_running_failed():
    """A running run older than the threshold is marked failed."""
    with TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, svc = _real_services(tmpdir)
        try:
            past = datetime.now(UTC) - timedelta(hours=2)
            payload = _payload()
            repository.save_run(
                transitions.build_execution_transition(
                    run_id="run-stuck",
                    payload=payload,
                    status=ExecutionStatus.running,
                    progress=50,
                    message="running",
                    created_at=past,
                    updated_at=past,
                )
            )

            failed = svc.fail_stuck_running_workflows(max_running_seconds=60)

            assert failed == 1, "one stuck run must be marked failed"
            run = repository.get_run("run-stuck")
            assert run.status == ExecutionStatus.failed, "stuck run must transition to failed"
        finally:
            repository.close()


def test_fail_stuck_running_skips_recent_running():
    """A running run updated recently is NOT marked failed."""
    with TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, svc = _real_services(tmpdir)
        try:
            now = datetime.now(UTC)
            payload = _payload()
            repository.save_run(
                transitions.build_execution_transition(
                    run_id="run-fresh",
                    payload=payload,
                    status=ExecutionStatus.running,
                    progress=40,
                    message="running",
                    created_at=now,
                    updated_at=now,
                )
            )

            failed = svc.fail_stuck_running_workflows(max_running_seconds=3600)

            assert failed == 0, "recent run must not be marked failed"
            run = repository.get_run("run-fresh")
            assert run.status == ExecutionStatus.running, "recent run must stay running"
        finally:
            repository.close()


def test_fail_stuck_running_ignores_terminal_runs():
    """Already-terminal runs (failed/succeeded) are ignored by the watchdog."""
    with TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, svc = _real_services(tmpdir)
        try:
            past = datetime.now(UTC) - timedelta(hours=5)
            payload = _payload()
            repository.save_run(
                transitions.build_execution_transition(
                    run_id="run-already-failed",
                    payload=payload,
                    status=ExecutionStatus.failed,
                    progress=100,
                    message="failed",
                    created_at=past,
                    updated_at=past,
                )
            )

            failed = svc.fail_stuck_running_workflows(max_running_seconds=0)
            assert failed == 0, "terminal runs must not be touched by watchdog"
        finally:
            repository.close()


# ---------------------------------------------------------------------------
# cleanup_stale_workflow_runs (real repo, patched celery inspect)
# ---------------------------------------------------------------------------


def test_cleanup_stale_returns_zero_on_empty_repo():
    """An empty repository yields zero cleaned runs."""
    with TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, svc = _real_services(tmpdir)
        try:
            assert svc.cleanup_stale_workflow_runs() == 0, "empty repo must clean 0 runs"
        finally:
            repository.close()


def test_cleanup_stale_skips_running_runs(monkeypatch):
    """Running runs are never cleaned up by the startup sweep."""
    # Avoid any real celery/redis interaction.
    monkeypatch.setattr(
        FollowUpDispatchService, "_collect_live_celery_task_ids", lambda self: set()
    )
    with TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, svc = _real_services(tmpdir)
        try:
            past = datetime.now(UTC) - timedelta(hours=3)
            payload = _payload()
            repository.save_run(
                transitions.build_execution_transition(
                    run_id="run-running",
                    payload=payload,
                    status=ExecutionStatus.running,
                    progress=50,
                    message="running",
                    created_at=past,
                    updated_at=past,
                )
            )
            assert svc.cleanup_stale_workflow_runs() == 0, "running runs must be skipped"
            run = repository.get_run("run-running")
            assert run.status == ExecutionStatus.running, "running run must remain running"
        finally:
            repository.close()
