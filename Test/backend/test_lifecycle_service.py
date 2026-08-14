"""Tests for app.services.workflow.lifecycle_service.WorkflowLifecycleService.

Focuses on cancel_workflow_run, finalize_workflow_success, the protected
terminal guard (_is_protected_terminal), and best-effort queue dispatch
triggering. Failure/timeout paths are covered by test_workflow_lifecycle_failure.py.
"""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.workflow.lifecycle_service import WorkflowLifecycleService
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
        command_label="lifecycle test",
        priority=WorkflowPriority.normal,
        requested_outputs=[],
    )


def _build_services(tmpdir: str):
    """Create a full service stack backed by a temp-dir SQLite repository."""
    repository = SQLiteWorkflowRepository(state_dir=tmpdir)
    persistence = WorkflowPersistenceService(repository)
    transitions = WorkflowTransitionBuilder()
    lifecycle = WorkflowLifecycleService(repository, persistence, transitions)
    return repository, persistence, transitions, lifecycle


def _make_run(
    persistence: WorkflowPersistenceService,
    transitions: WorkflowTransitionBuilder,
    run_id: str,
    status: ExecutionStatus,
    payload: WorkflowSubmitRequest | None = None,
    progress: int = 50,
    message: str = "running",
) -> datetime:
    payload = payload or _payload()
    now = datetime.now(UTC)
    persistence.save_run_status(
        run_status=transitions.build_execution_transition(
            run_id=run_id,
            payload=payload,
            status=status,
            progress=progress,
            message=message,
            created_at=now,
            updated_at=now,
        )
    )
    return now


def _patch_cancel_paths(monkeypatch, tmpdir: str) -> None:
    """Redirect cancel flag writes into the temp dir."""
    base = Path(tmpdir) / "cancel"
    monkeypatch.setattr(
        "app.services.workflow.lifecycle_service.workflow_cancel_tmp_dir",
        lambda run_id: base / run_id,
    )
    monkeypatch.setattr(
        "app.services.workflow.lifecycle_service.workflow_cancel_flag_path",
        lambda run_id: base / run_id / "cancel.requested",
    )


# ---------------------------------------------------------------------------
# cancel_workflow_run
# ---------------------------------------------------------------------------


def test_cancel_not_found_raises(monkeypatch):
    """Cancelling a non-existent run raises ValueError."""
    with TemporaryDirectory() as tmpdir:
        _patch_cancel_paths(monkeypatch, tmpdir)
        repo, persistence, transitions, lifecycle = _build_services(tmpdir)
        try:
            try:
                lifecycle.cancel_workflow_run("run-missing")
            except ValueError as exc:
                assert "not found" in str(exc).lower(), "error must mention not found"
            else:
                raise AssertionError("cancel on missing run must raise ValueError")
        finally:
            repo.close()


def test_cancel_terminal_state_raises(monkeypatch):
    """Cancelling a run already in a terminal state raises ValueError."""
    with TemporaryDirectory() as tmpdir:
        _patch_cancel_paths(monkeypatch, tmpdir)
        repo, persistence, transitions, lifecycle = _build_services(tmpdir)
        try:
            _make_run(persistence, transitions, "run-done", ExecutionStatus.succeeded)
            try:
                lifecycle.cancel_workflow_run("run-done")
            except ValueError as exc:
                assert "terminal" in str(exc).lower(), "error must mention terminal state"
            else:
                raise AssertionError("cancel on terminal run must raise ValueError")
        finally:
            repo.close()


def test_cancel_running_transitions_to_cancelled(monkeypatch):
    """A running run is cancelled: status -> cancelled and a cancel flag is written."""
    with TemporaryDirectory() as tmpdir:
        _patch_cancel_paths(monkeypatch, tmpdir)
        repo, persistence, transitions, lifecycle = _build_services(tmpdir)
        try:
            _make_run(persistence, transitions, "run-live", ExecutionStatus.running)

            result = lifecycle.cancel_workflow_run("run-live")

            assert result is not None, "cancel must return the updated run"
            assert result.status == ExecutionStatus.cancelled, "status must be cancelled"
            assert result.progress == 100, "cancelled progress must be 100"
            # The cancel flag file must have been written.
            flag = Path(tmpdir) / "cancel" / "run-live" / "cancel.requested"
            assert flag.exists(), "cancel flag file must be created"
            assert flag.read_text(encoding="utf-8") == "1", "cancel flag content must be '1'"
        finally:
            repo.close()


def test_cancel_records_cancelled_event(monkeypatch):
    """Cancelling records a status event with the cancelled payload."""
    with TemporaryDirectory() as tmpdir:
        _patch_cancel_paths(monkeypatch, tmpdir)
        repo, persistence, transitions, lifecycle = _build_services(tmpdir)
        try:
            _make_run(persistence, transitions, "run-evt", ExecutionStatus.running)
            lifecycle.cancel_workflow_run("run-evt")
            events = repo.list_events("run-evt")
            assert any(
                "取消" in e.message for e in events
            ), "a cancel status event must be recorded"
        finally:
            repo.close()


# ---------------------------------------------------------------------------
# _is_protected_terminal
# ---------------------------------------------------------------------------


def test_is_protected_terminal_blocks_all_terminal_states(monkeypatch):
    """succeeded, failed, and cancelled runs are all protected terminals."""
    with TemporaryDirectory() as tmpdir:
        _patch_cancel_paths(monkeypatch, tmpdir)
        repo, persistence, transitions, lifecycle = _build_services(tmpdir)
        try:
            for status in (
                ExecutionStatus.succeeded,
                ExecutionStatus.failed,
                ExecutionStatus.cancelled,
            ):
                run_id = f"run-{status.value}"
                _make_run(persistence, transitions, run_id, status)
                blocked, reason = lifecycle._is_protected_terminal(run_id)
                assert blocked is True, f"{status.value} must be a protected terminal"
                assert reason, f"{status.value} must carry a non-empty reason"
        finally:
            repo.close()


def test_is_protected_terminal_allows_non_terminal_states(monkeypatch):
    """running, queued, accepted, retry_pending are NOT protected terminals."""
    with TemporaryDirectory() as tmpdir:
        _patch_cancel_paths(monkeypatch, tmpdir)
        repo, persistence, transitions, lifecycle = _build_services(tmpdir)
        try:
            for status in (
                ExecutionStatus.running,
                ExecutionStatus.queued,
                ExecutionStatus.accepted,
                ExecutionStatus.retry_pending,
            ):
                run_id = f"run-{status.value}"
                _make_run(persistence, transitions, run_id, status)
                blocked, reason = lifecycle._is_protected_terminal(run_id)
                assert blocked is False, f"{status.value} must not be protected"
                assert reason == "", f"{status.value} reason must be empty"
        finally:
            repo.close()


def test_is_protected_terminal_missing_run_returns_false(monkeypatch):
    """A missing run is not protected (returns False, empty reason)."""
    with TemporaryDirectory() as tmpdir:
        _patch_cancel_paths(monkeypatch, tmpdir)
        repo, persistence, transitions, lifecycle = _build_services(tmpdir)
        try:
            blocked, reason = lifecycle._is_protected_terminal("no-such-run")
            assert blocked is False, "missing run must not be blocked"
            assert reason == "", "missing run reason must be empty"
        finally:
            repo.close()


# ---------------------------------------------------------------------------
# finalize_workflow_success
# ---------------------------------------------------------------------------


def test_finalize_workflow_success_transitions_to_succeeded(monkeypatch):
    """A running run finalizes to succeeded with result refs materialized."""
    with TemporaryDirectory() as tmpdir:
        _patch_cancel_paths(monkeypatch, tmpdir)
        repo, persistence, transitions, lifecycle = _build_services(tmpdir)
        monkeypatch.setattr(
            "app.services.workflow.lifecycle_service.result_storage_service",
            MagicMock(materialize_result_refs=lambda **kw: ([], [])),
        )
        try:
            now = _make_run(persistence, transitions, "run-ok", ExecutionStatus.running)
            execution = SimpleNamespace(
                result_refs=[],
                diagnostics=["done"],
                message="completed",
                follow_up_tasks=[],
                result_dto=None,
            )

            lifecycle.finalize_workflow_success(
                run_id="run-ok",
                payload=_payload(),
                execution=execution,
                requested_at=now,
            )

            run = repo.get_run("run-ok")
            assert run is not None, "run must exist"
            assert run.status == ExecutionStatus.succeeded, "status must be succeeded"
            assert run.progress == 100, "succeeded progress must be 100"
        finally:
            repo.close()


def test_finalize_workflow_success_skips_protected_terminal(monkeypatch):
    """Finalizing success on an already-cancelled run must NOT overwrite status."""
    with TemporaryDirectory() as tmpdir:
        _patch_cancel_paths(monkeypatch, tmpdir)
        repo, persistence, transitions, lifecycle = _build_services(tmpdir)
        monkeypatch.setattr(
            "app.services.workflow.lifecycle_service.result_storage_service",
            MagicMock(materialize_result_refs=lambda **kw: ([], [])),
        )
        try:
            now = _make_run(
                persistence, transitions, "run-protected", ExecutionStatus.cancelled
            )
            execution = SimpleNamespace(
                result_refs=[],
                diagnostics=[],
                message="late success",
                follow_up_tasks=[],
                result_dto=None,
            )

            lifecycle.finalize_workflow_success(
                run_id="run-protected",
                payload=_payload(),
                execution=execution,
                requested_at=now,
            )

            run = repo.get_run("run-protected")
            assert run.status == ExecutionStatus.cancelled, (
                "protected cancelled run must not be overwritten to succeeded"
            )
        finally:
            repo.close()


def test_finalize_workflow_success_dispatches_follow_up_tasks(monkeypatch):
    """When execution has follow_up_tasks, the follow-up dispatcher is invoked."""
    with TemporaryDirectory() as tmpdir:
        _patch_cancel_paths(monkeypatch, tmpdir)
        repo, persistence, transitions, lifecycle = _build_services(tmpdir)
        monkeypatch.setattr(
            "app.services.workflow.lifecycle_service.result_storage_service",
            MagicMock(materialize_result_refs=lambda **kw: ([], [])),
        )
        follow_up = MagicMock()
        lifecycle._follow_up = follow_up
        try:
            now = _make_run(persistence, transitions, "run-followup", ExecutionStatus.running)
            execution = SimpleNamespace(
                result_refs=[],
                diagnostics=[],
                message="ok",
                follow_up_tasks=[{"task_type": "download_fetch"}],
                result_dto=None,
            )

            lifecycle.finalize_workflow_success(
                run_id="run-followup",
                payload=_payload(),
                execution=execution,
                requested_at=now,
            )

            follow_up.dispatch_follow_up_tasks.assert_called_once(), (
                "follow-up dispatcher must be called when follow_up_tasks present"
            )
        finally:
            repo.close()


# ---------------------------------------------------------------------------
# _trigger_queue_dispatch
# ---------------------------------------------------------------------------


def test_trigger_queue_dispatch_best_effort_swallows_exceptions(monkeypatch):
    """If queue dispatch raises, the lifecycle call must not propagate the error."""
    with TemporaryDirectory() as tmpdir:
        _patch_cancel_paths(monkeypatch, tmpdir)
        repo, persistence, transitions, lifecycle = _build_services(tmpdir)
        queue_dispatch = MagicMock()
        queue_dispatch.dispatch_queued_workflows.side_effect = RuntimeError("boom")
        lifecycle._queue_dispatch = queue_dispatch
        monkeypatch.setattr(
            "app.services.workflow.lifecycle_service.result_storage_service",
            MagicMock(materialize_result_refs=lambda **kw: ([], [])),
        )
        try:
            now = _make_run(persistence, transitions, "run-qd", ExecutionStatus.running)
            execution = SimpleNamespace(
                result_refs=[],
                diagnostics=[],
                message="ok",
                follow_up_tasks=[],
                result_dto=None,
            )
            # Must not raise despite queue_dispatch blowing up.
            lifecycle.finalize_workflow_success(
                run_id="run-qd",
                payload=_payload(),
                execution=execution,
                requested_at=now,
            )
            queue_dispatch.dispatch_queued_workflows.assert_called_once(), (
                "queue dispatch must be attempted"
            )
            run = repo.get_run("run-qd")
            assert run.status == ExecutionStatus.succeeded, (
                "success finalize must still complete despite queue dispatch failure"
            )
        finally:
            repo.close()


def test_trigger_queue_dispatch_skipped_when_none():
    """When no queue_dispatch service is injected, triggering is a no-op."""
    with TemporaryDirectory() as tmpdir:
        repo, persistence, transitions, lifecycle = _build_services(tmpdir)
        try:
            assert lifecycle._queue_dispatch is None, "default queue_dispatch must be None"
            # Should not raise.
            lifecycle._trigger_queue_dispatch()
        finally:
            repo.close()
