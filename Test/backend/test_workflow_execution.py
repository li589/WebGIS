"""Tests for app.services.workflow.submission_service.WorkflowSubmissionService.

Covers pure-logic helpers (WorkflowValidationError, _template_error_to_issue,
_analysis_exclusivity_key), capacity/validation probes, the lifecycle late
binding, and process_workflow_run exception propagation with a mock lifecycle.
"""

from __future__ import annotations

from datetime import datetime, UTC
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.submission_service import (
    WorkflowSubmissionService,
    WorkflowValidationError,
    _template_error_to_issue,
)
from app.services.workflow.transition_builder import WorkflowTransitionBuilder
from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ExecutionStatus,
    WorkflowCommandType,
    WorkflowSubmitRequest,
)


def _payload(**kwargs) -> WorkflowSubmitRequest:
    base = dict(command_type=WorkflowCommandType.analysis, requested_outputs=[])
    base.update(kwargs)
    return WorkflowSubmitRequest(**base)


# ---------------------------------------------------------------------------
# WorkflowValidationError formatting
# ---------------------------------------------------------------------------


def test_workflow_validation_error_empty_issues_message():
    """An empty issue list produces a generic message."""
    err = WorkflowValidationError([])
    assert "validation failed" in str(err).lower(), "empty issues must yield generic message"
    assert err.issues == [], "issues list must be preserved"


def test_workflow_validation_error_formats_issues_with_fields():
    """Issues are formatted as [field] message, joined by semicolons."""
    err = WorkflowValidationError(
        [
            {"field": "datasource_selection.ndvi", "message": "Missing required datasource key: 'ndvi'"},
            {"field": "algorithm_params.alpha", "message": "Missing required algorithm param: 'alpha'"},
        ]
    )
    text = str(err)
    assert "[datasource_selection.ndvi]" in text, "first field must appear"
    assert "[algorithm_params.alpha]" in text, "second field must appear"
    assert "Missing required datasource key" in text, "first message must appear"
    assert ";" in text, "issues must be joined by semicolons"


# ---------------------------------------------------------------------------
# _template_error_to_issue
# ---------------------------------------------------------------------------


def test_template_error_to_issue_datasource_key():
    """Datasource-key errors map to the datasource_selection field."""
    issue = _template_error_to_issue("Missing required datasource key: 'ndvi_layer'")
    assert issue["field"] == "datasource_selection.ndvi_layer", (
        "datasource key must map to datasource_selection.<key>"
    )
    assert "ndvi_layer" in issue["message"], "original message must be preserved"


def test_template_error_to_issue_algorithm_param():
    """Algorithm-param errors map to the algorithm_params field."""
    issue = _template_error_to_issue("Missing required algorithm param: 'smoothing'")
    assert issue["field"] == "algorithm_params.smoothing", (
        "algorithm param must map to algorithm_params.<param>"
    )


def test_template_error_to_issue_algorithm_param_value():
    """'algorithm param' prefix errors also map to algorithm_params."""
    issue = _template_error_to_issue("algorithm param 'threshold' must be positive")
    assert issue["field"] == "algorithm_params.threshold", (
        "algorithm param value error must map to algorithm_params.<param>"
    )


def test_template_error_to_issue_task_type():
    """task_type errors map to the task_type field."""
    issue = _template_error_to_issue("task_type is not allowed: forbidden_op")
    assert issue["field"] == "task_type", "task_type errors must map to task_type field"


def test_template_error_to_issue_unknown_falls_back():
    """Unrecognized errors fall back to the _unknown field."""
    issue = _template_error_to_issue("something completely unexpected")
    assert issue["field"] == "_unknown", "unrecognized errors must map to _unknown"
    assert issue["message"] == "something completely unexpected", (
        "message must be preserved for unknown errors"
    )


# ---------------------------------------------------------------------------
# _analysis_exclusivity_key
# ---------------------------------------------------------------------------


def test_analysis_exclusivity_key_extracts_value():
    """The exclusivity key is read from payload parameters."""
    payload = _payload(parameters={"analysis_exclusivity_key": "  zone-A  "})
    assert WorkflowSubmissionService._analysis_exclusivity_key(payload) == "zone-A", (
        "key must be stripped of surrounding whitespace"
    )


def test_analysis_exclusivity_key_none_when_absent():
    """A missing or empty key returns None."""
    assert WorkflowSubmissionService._analysis_exclusivity_key(_payload()) is None, (
        "absent key must return None"
    )
    assert WorkflowSubmissionService._analysis_exclusivity_key(
        _payload(parameters={"analysis_exclusivity_key": "   "})
    ) is None, "whitespace-only key must return None"


def test_analysis_exclusivity_key_handles_non_dict_parameters():
    """Non-dict parameters do not crash; they return None."""
    payload = _payload()
    payload.parameters = "not-a-dict"  # type: ignore[assignment]
    assert WorkflowSubmissionService._analysis_exclusivity_key(payload) is None, (
        "non-dict parameters must yield None"
    )


# ---------------------------------------------------------------------------
# Lifecycle late binding
# ---------------------------------------------------------------------------


def test_lifecycle_property_raises_when_not_set():
    """Accessing .lifecycle before set_lifecycle_service raises RuntimeError."""
    svc = WorkflowSubmissionService(repository=MagicMock(), persistence=MagicMock())
    with pytest.raises(RuntimeError, match="Lifecycle service not set"):
        _ = svc.lifecycle


def test_set_lifecycle_service_binds_reference():
    """set_lifecycle_service makes .lifecycle return the bound instance."""
    svc = WorkflowSubmissionService(repository=MagicMock(), persistence=MagicMock())
    mock_lifecycle = MagicMock()
    svc.set_lifecycle_service(mock_lifecycle)
    assert svc.lifecycle is mock_lifecycle, "lifecycle must return the bound instance"


# ---------------------------------------------------------------------------
# Capacity / validation probes
# ---------------------------------------------------------------------------


def test_assert_workflow_capacity_ok_under_limit():
    """An empty repository is under capacity; no exception is raised."""
    with TemporaryDirectory() as tmpdir:
        repo = SQLiteWorkflowRepository(state_dir=tmpdir)
        persistence = WorkflowPersistenceService(repo)
        svc = WorkflowSubmissionService(repo, persistence)
        try:
            svc._assert_workflow_capacity()  # must not raise
        finally:
            repo.close()


def test_assert_workflow_capacity_raises_when_full():
    """When active runs >= limit, a ValueError is raised."""
    repo = MagicMock()
    repo.count_active_runs.return_value = 999
    persistence = MagicMock()
    persistence.get_effective_config_int.return_value = 4
    svc = WorkflowSubmissionService(repository=repo, persistence=persistence)
    with pytest.raises(ValueError, match="capacity reached"):
        svc._assert_workflow_capacity()


def test_validate_requested_outputs_exceeds_limit():
    """More requested outputs than the limit raises ValueError."""
    persistence = MagicMock()
    persistence.get_effective_config_int.return_value = 2
    svc = WorkflowSubmissionService(repository=MagicMock(), persistence=persistence)
    payload = _payload(requested_outputs=["json", "chart", "table"])
    with pytest.raises(ValueError, match="exceed limit"):
        svc._validate_requested_outputs(payload)


def test_user_concurrency_limit_admin_returns_none():
    """Admin role is exempt from per-user limits (None)."""
    svc = WorkflowSubmissionService(repository=MagicMock(), persistence=MagicMock())
    assert svc._user_concurrency_limit(user_id=1, role="admin") is None, (
        "admin must have no per-user limit"
    )


def test_user_concurrency_limit_no_user_returns_none():
    """No user_id or role yields None (no limit applies)."""
    svc = WorkflowSubmissionService(repository=MagicMock(), persistence=MagicMock())
    assert svc._user_concurrency_limit(user_id=None, role="standard") is None, (
        "missing user_id must yield None"
    )
    assert svc._user_concurrency_limit(user_id=1, role=None) is None, (
        "missing role must yield None"
    )


# ---------------------------------------------------------------------------
# process_workflow_run exception propagation (real repo + mock lifecycle)
# ---------------------------------------------------------------------------


def _real_services(tmpdir: str):
    repo = SQLiteWorkflowRepository(state_dir=tmpdir)
    persistence = WorkflowPersistenceService(repo)
    transitions = WorkflowTransitionBuilder()
    svc = WorkflowSubmissionService(repo, persistence, transitions)
    return repo, persistence, transitions, svc


@patch("app.services.workflow.submission_service.execute_workflow_task")
def test_process_workflow_run_skips_terminal_state(mock_execute):
    """A run already in a terminal state is not re-executed."""
    with TemporaryDirectory() as tmpdir:
        repo, persistence, transitions, svc = _real_services(tmpdir)
        try:
            now = datetime.now(UTC)
            persistence.save_run_status(
                run_status=transitions.build_execution_transition(
                    run_id="run-done",
                    payload=_payload(),
                    status=ExecutionStatus.succeeded,
                    progress=100,
                    message="done",
                    created_at=now,
                    updated_at=now,
                )
            )
            svc.set_lifecycle_service(MagicMock())

            svc.process_workflow_run("run-done", _payload())

            mock_execute.assert_not_called(), "terminal run must not trigger execution"
        finally:
            repo.close()


@patch("app.services.workflow.submission_service.execute_workflow_task")
def test_process_workflow_run_success_calls_finalize(mock_execute):
    """Successful execution calls lifecycle.finalize_workflow_success."""
    with TemporaryDirectory() as tmpdir:
        repo, persistence, transitions, svc = _real_services(tmpdir)
        try:
            execution = SimpleNamespace(
                result_refs=[], diagnostics=[], message="ok",
                follow_up_tasks=[], result_dto=None,
            )
            mock_execute.return_value = execution
            mock_lifecycle = MagicMock()
            svc.set_lifecycle_service(mock_lifecycle)

            svc.process_workflow_run("run-ok", _payload())

            mock_execute.assert_called_once(), "execute must run once"
            mock_lifecycle.finalize_workflow_success.assert_called_once(), (
                "success must trigger finalize_workflow_success"
            )
            # The run must have transitioned to running before execution.
            run = repo.get_run("run-ok")
            assert run is not None, "run must be persisted"
        finally:
            repo.close()


@patch("app.services.workflow.submission_service.execute_workflow_task")
def test_process_workflow_run_exception_calls_handle_failure(mock_execute):
    """A runtime error during execution routes to lifecycle.handle_workflow_failure."""
    with TemporaryDirectory() as tmpdir:
        repo, persistence, transitions, svc = _real_services(tmpdir)
        try:
            mock_execute.side_effect = RuntimeError("boom")
            mock_lifecycle = MagicMock()
            svc.set_lifecycle_service(mock_lifecycle)

            svc.process_workflow_run("run-fail", _payload())

            mock_lifecycle.handle_workflow_failure.assert_called_once(), (
                "runtime error must trigger handle_workflow_failure"
            )
            call_kwargs = mock_lifecycle.handle_workflow_failure.call_args.kwargs
            assert isinstance(call_kwargs["exc"], RuntimeError), (
                "the original exception must be forwarded"
            )
            assert str(call_kwargs["exc"]) == "boom", "exception message must be preserved"
        finally:
            repo.close()


@patch("app.services.workflow.submission_service.execute_workflow_task")
def test_process_workflow_run_soft_timeout_calls_handle_timeout(mock_execute):
    """A SoftTimeLimitExceeded routes to lifecycle.handle_workflow_timeout."""
    with TemporaryDirectory() as tmpdir:
        repo, persistence, transitions, svc = _real_services(tmpdir)
        try:
            mock_execute.side_effect = SoftTimeLimitExceeded()
            mock_lifecycle = MagicMock()
            svc.set_lifecycle_service(mock_lifecycle)

            svc.process_workflow_run("run-timeout", _payload())

            mock_lifecycle.handle_workflow_timeout.assert_called_once(), (
                "soft time limit must trigger handle_workflow_timeout"
            )
            mock_lifecycle.handle_workflow_failure.assert_not_called(), (
                "timeout must NOT also trigger the generic failure handler"
            )
        finally:
            repo.close()
