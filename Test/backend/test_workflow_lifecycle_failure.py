"""Tests for workflow lifecycle failure handling paths.

Covers G2-02: Workflow CAS Locking + Lifecycle Failure Paths.

Tests handle_workflow_failure classification routing (retry vs finalize),
handle_workflow_timeout, finalize_workflow_failure diagnostics, protected
terminal skips, and _schedule_retry dispatch-failure fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from unittest.mock import patch

from app.services.workflow.lifecycle_service import WorkflowLifecycleService
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.transition_builder import WorkflowTransitionBuilder
from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ExecutionStatus,
    FailureCategory,
    RetryPolicy,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowSubmitRequest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload(
    retry_attempt: int | None = None,
    max_attempts: int = 3,
) -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="lifecycle failure test",
        priority=WorkflowPriority.normal,
        requested_outputs=[],
        retry_policy=RetryPolicy(max_attempts=max_attempts),
        retry_attempt=retry_attempt,
    )


def _setup_services(tmpdir: str):
    """Create repository, persistence, transitions, lifecycle with a temp DB."""
    repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
    persistence = WorkflowPersistenceService(repository)
    transitions = WorkflowTransitionBuilder()
    lifecycle = WorkflowLifecycleService(repository, persistence, transitions)
    return repository, persistence, transitions, lifecycle


def _make_running_run(
    persistence: WorkflowPersistenceService,
    transitions: WorkflowTransitionBuilder,
    run_id: str,
    payload: WorkflowSubmitRequest,
) -> datetime:
    """Create a run with status=running and return the creation timestamp."""
    now = datetime.now(timezone.utc)
    persistence.save_run_status(
        run_status=transitions.build_execution_transition(
            run_id=run_id,
            payload=payload,
            status=ExecutionStatus.running,
            progress=50,
            message="running",
            created_at=now,
            updated_at=now,
        )
    )
    return now


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("app.services.workflow.lifecycle_service.dispatch_workflow_task")
def test_handle_workflow_failure_retryable(
    mock_dispatch: object
) -> None:
    """Retryable exception with attempt < max_attempts → retry_pending."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, lifecycle = _setup_services(tmpdir)
        try:
            now = _make_running_run(
                persistence, transitions, "run-retryable", _payload(1, 3)
            )

            # ConnectionError → transient_network (retryable=True)
            lifecycle.handle_workflow_failure(
                run_id="run-retryable",
                payload=_payload(1, 3),
                created_at=now,
                exc=ConnectionError("network down"),
            )

            run = repository.get_run("run-retryable")
            assert run is not None, 'run is not None'
            assert run.status == ExecutionStatus.retry_pending, 'run.status == ExecutionStatus.retry_pending'
        finally:
            repository.close()


def test_handle_workflow_failure_non_retryable() -> None:
    """Non-retryable exception (KeyError → terminal_failure) → failed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, lifecycle = _setup_services(tmpdir)
        try:
            now = _make_running_run(
                persistence, transitions, "run-terminal", _payload(1, 3)
            )

            # KeyError → terminal_failure (retryable=False)
            lifecycle.handle_workflow_failure(
                run_id="run-terminal",
                payload=_payload(1, 3),
                created_at=now,
                exc=KeyError("missing key"),
            )

            run = repository.get_run("run-terminal")
            assert run is not None, 'run is not None'
            assert run.status == ExecutionStatus.failed, 'run.status == ExecutionStatus.failed'
        finally:
            repository.close()


def test_handle_workflow_failure_max_attempts_exceeded() -> None:
    """Retryable exception but attempt == max_attempts → failed (not retry)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, lifecycle = _setup_services(tmpdir)
        try:
            now = _make_running_run(
                persistence, transitions, "run-max-attempts", _payload(3, 3)
            )

            # ConnectionError → transient_network (retryable), but 3 < 3 is False
            lifecycle.handle_workflow_failure(
                run_id="run-max-attempts",
                payload=_payload(3, 3),
                created_at=now,
                exc=ConnectionError("network down"),
            )

            run = repository.get_run("run-max-attempts")
            assert run is not None, 'run is not None'
            assert run.status == ExecutionStatus.failed, 'run.status == ExecutionStatus.failed'
        finally:
            repository.close()


def test_handle_workflow_timeout() -> None:
    """handle_workflow_timeout → finalize_workflow_failure with terminal_failure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, lifecycle = _setup_services(tmpdir)
        try:
            now = _make_running_run(
                persistence, transitions, "run-timeout", _payload(1, 3)
            )

            lifecycle.handle_workflow_timeout(
                run_id="run-timeout",
                payload=_payload(1, 3),
                created_at=now,
            )

            run = repository.get_run("run-timeout")
            assert run is not None, 'run is not None'
            assert run.status == ExecutionStatus.failed, 'run.status == ExecutionStatus.failed'
            # Verify failure_category=terminal_failure in diagnostics
            assert any(
                    "failure_category=terminal_failure" in d
                    for d in run.diagnostics
                ), f"Expected failure_category=terminal_failure in diagnostics: {run.diagnostics}"
        finally:
            repository.close()


def test_finalize_workflow_failure_validation_error_message() -> None:
    """validation_error failure message includes the exception text."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, lifecycle = _setup_services(tmpdir)
        try:
            now = _make_running_run(
                persistence, transitions, "run-validation", _payload(1, 3)
            )

            exc = ValueError("invalid layer parameter")
            lifecycle.finalize_workflow_failure(
                run_id="run-validation",
                payload=_payload(1, 3),
                created_at=now,
                exc=exc,
                category=FailureCategory.validation_error,
            )

            run = repository.get_run("run-validation")
            assert run is not None, 'run is not None'
            assert run.status == ExecutionStatus.failed, 'run.status == ExecutionStatus.failed'
            assert "工作流校验失败" in run.message, '"工作流校验失败" in run.message'
            assert "invalid layer parameter" in run.message, '"invalid layer parameter" in run.message'
        finally:
            repository.close()


def test_finalize_workflow_failure_skips_protected_terminal() -> None:
    """Run already succeeded → _is_protected_terminal blocks → no status change."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, lifecycle = _setup_services(tmpdir)
        try:
            now = datetime.now(timezone.utc)
            payload = _payload(1, 3)

            # Create run as succeeded (terminal)
            persistence.save_run_status(
                run_status=transitions.build_execution_transition(
                    run_id="run-protected",
                    payload=payload,
                    status=ExecutionStatus.succeeded,
                    progress=100,
                    message="already succeeded",
                    created_at=now,
                    updated_at=now,
                )
            )

            lifecycle.finalize_workflow_failure(
                run_id="run-protected",
                payload=payload,
                created_at=now,
                exc=RuntimeError("late failure"),
                category=FailureCategory.terminal_failure,
            )

            # Run should still be succeeded (protected terminal)
            run = repository.get_run("run-protected")
            assert run is not None, 'run is not None'
            assert run.status == ExecutionStatus.succeeded, 'run.status == ExecutionStatus.succeeded'
            assert run.message == "already succeeded", 'run.message == "already succeeded"'
        finally:
            repository.close()


@patch("app.services.workflow.lifecycle_service.dispatch_workflow_task")
def test_schedule_retry_failure_transitions_to_failed(
    mock_dispatch: object
) -> None:
    """If dispatch_workflow_task raises, _schedule_retry transitions to failed.

    Flow: handle_workflow_failure (retryable) → finalize_workflow_retry
    (retry_pending) → _schedule_retry (dispatch raises) → finalize_workflow_failure
    (CAS retries from retry_pending → failed).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, lifecycle = _setup_services(tmpdir)
        try:
            now = _make_running_run(
                persistence, transitions, "run-dispatch-fail", _payload(1, 3)
            )

            # Mock dispatch to raise → _schedule_retry fallback to failed
            mock_dispatch.side_effect = RuntimeError("dispatch failed")

            lifecycle.handle_workflow_failure(
                run_id="run-dispatch-fail",
                payload=_payload(1, 3),
                created_at=now,
                exc=ConnectionError("transient"),
            )

            run = repository.get_run("run-dispatch-fail")
            assert run is not None, 'run is not None'
            assert run.status == ExecutionStatus.failed, 'run.status == ExecutionStatus.failed'
        finally:
            repository.close()


def test_finalize_workflow_failure_diagnostics() -> None:
    """Diagnostics list includes error_type, error_message, failure_category, retryable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, lifecycle = _setup_services(tmpdir)
        try:
            now = _make_running_run(
                persistence, transitions, "run-diagnostics", _payload(1, 3)
            )

            exc = RuntimeError("boom")
            lifecycle.finalize_workflow_failure(
                run_id="run-diagnostics",
                payload=_payload(1, 3),
                created_at=now,
                exc=exc,
                category=FailureCategory.terminal_failure,
                attempt_count=2,
            )

            run = repository.get_run("run-diagnostics")
            assert run is not None, 'run is not None'
            assert run.status == ExecutionStatus.failed, 'run.status == ExecutionStatus.failed'

            diagnostics_text = " ".join(run.diagnostics)
            assert "error_type=RuntimeError" in diagnostics_text, '"error_type=RuntimeError" in diagnostics_text'
            assert "error_message=boom" in diagnostics_text, '"error_message=boom" in diagnostics_text'
            assert "failure_category=terminal_failure" in diagnostics_text, '"failure_category=terminal_failure" in diagnostics_text'
            assert "retryable=False" in diagnostics_text, '"retryable=False" in diagnostics_text'
        finally:
            repository.close()
