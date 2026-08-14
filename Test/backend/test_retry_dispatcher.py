"""Tests for app.services.workflow.retry_dispatcher.RetryDispatcher.

The dispatcher re-submits a prior workflow run as a new run and tags the
new run with ``retry_of_run_id`` metadata. Tests use a mock repository and
submit_fn to isolate the orchestration logic.
"""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import pytest

from app.services.workflow.retry_dispatcher import RetryDispatcher
from app.services.workflow.transition_builder import WorkflowTransitionBuilder
from shared.contracts.api_contracts import (
    ExecutionStatus,
    WorkflowAcceptedResponse,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowSubmitRequest,
)


def _payload(command_label: str = "retry test") -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label=command_label,
        priority=WorkflowPriority.high,
        requested_outputs=[],
    )


def _build_run_status(run_id: str, status: ExecutionStatus) -> object:
    """Build a real WorkflowRunStatusResponse for mock repository returns."""
    transitions = WorkflowTransitionBuilder()
    now = datetime.now(UTC)
    return transitions.build_execution_transition(
        run_id=run_id,
        payload=_payload(),
        status=status,
        progress=100 if status in (ExecutionStatus.failed, ExecutionStatus.succeeded) else 3,
        message=str(status.value),
        created_at=now,
        updated_at=now,
    )


def _accepted_response(run_id: str = "run-new") -> WorkflowAcceptedResponse:
    return WorkflowAcceptedResponse(
        run_id=run_id,
        status=ExecutionStatus.accepted,
        status_url=f"/workflow-runs/{run_id}",
        events_url=f"/workflow-runs/{run_id}/events",
        created_at=datetime.now(UTC),
        message="re-submitted",
    )


# ---------------------------------------------------------------------------
# Exception: missing request
# ---------------------------------------------------------------------------


def test_retry_raises_when_no_request_json():
    """A run with no persisted request JSON cannot be retried."""
    repo = MagicMock()
    repo.get_run_request_json.return_value = None
    dispatcher = RetryDispatcher(repo, MagicMock(), MagicMock(), MagicMock())

    with pytest.raises(ValueError, match="no request"):
        dispatcher.retry_workflow_run("run-missing")

    # submit_fn must never be called when validation fails.
    dispatcher._submit_fn.assert_not_called(), (
        "submit must not run when request JSON is missing"
    )


# ---------------------------------------------------------------------------
# Normal: re-submit + tagging
# ---------------------------------------------------------------------------


def test_retry_submits_new_run_and_tags_retry_of():
    """A valid retry re-submits and tags the new run with retry_of_run_id."""
    transitions = WorkflowTransitionBuilder()
    repo = MagicMock()
    payload = _payload()
    repo.get_run_request_json.return_value = payload.model_dump_json()

    base_run = _build_run_status("run-old", ExecutionStatus.failed)
    new_run = _build_run_status("run-new", ExecutionStatus.accepted)
    repo.get_run.side_effect = [base_run, new_run]
    repo.get_run_payload.return_value = None

    persistence = MagicMock()
    submit_fn = MagicMock(return_value=_accepted_response("run-new"))
    dispatcher = RetryDispatcher(repo, persistence, transitions, submit_fn)

    response = dispatcher.retry_workflow_run("run-old")

    assert response.run_id == "run-new", "must return the new run id"
    submit_fn.assert_called_once(), "submit_fn must be invoked exactly once"
    persistence.save_run_status.assert_called_once(), (
        "new run must be re-saved with retry metadata"
    )
    saved = persistence.save_run_status.call_args.kwargs["run_status"]
    assert saved.executor_metadata["retry_of_run_id"] == "run-old", (
        "new run metadata must reference the original run id"
    )


def test_retry_passes_original_command_type_to_submit():
    """The re-submitted payload preserves the original command_type/priority."""
    transitions = WorkflowTransitionBuilder()
    repo = MagicMock()
    payload = _payload("preserve fields")
    repo.get_run_request_json.return_value = payload.model_dump_json()
    repo.get_run.side_effect = [
        _build_run_status("run-old", ExecutionStatus.failed),
        _build_run_status("run-new", ExecutionStatus.accepted),
    ]
    repo.get_run_payload.return_value = None

    submit_fn = MagicMock(return_value=_accepted_response())
    dispatcher = RetryDispatcher(repo, MagicMock(), transitions, submit_fn)

    dispatcher.retry_workflow_run("run-old")

    submitted_payload = submit_fn.call_args.args[0]
    assert submitted_payload.command_type == WorkflowCommandType.analysis, (
        "command_type must be preserved on retry"
    )
    assert submitted_payload.priority == WorkflowPriority.high, (
        "priority must be preserved on retry"
    )
    assert submitted_payload.command_label == "preserve fields", (
        "command_label must be preserved on retry"
    )


# ---------------------------------------------------------------------------
# Boundary: new run not found
# ---------------------------------------------------------------------------


def test_retry_returns_response_when_new_run_not_persisted():
    """If the new run cannot be fetched, the response is still returned (no tag save)."""
    transitions = WorkflowTransitionBuilder()
    repo = MagicMock()
    payload = _payload()
    repo.get_run_request_json.return_value = payload.model_dump_json()
    # resolve_reuse_output_dir gets base_run; then get_run(new_run_id) -> None.
    repo.get_run.side_effect = [_build_run_status("run-old", ExecutionStatus.failed), None]
    repo.get_run_payload.return_value = None

    persistence = MagicMock()
    submit_fn = MagicMock(return_value=_accepted_response("run-orphan"))
    dispatcher = RetryDispatcher(repo, persistence, transitions, submit_fn)

    response = dispatcher.retry_workflow_run("run-old")

    assert response.run_id == "run-orphan", "response must still be returned"
    persistence.save_run_status.assert_not_called(), (
        "no re-save when the new run is absent"
    )


# ---------------------------------------------------------------------------
# Reuse cache injection wiring
# ---------------------------------------------------------------------------


def test_retry_injects_reuse_params_when_output_dir_resolved():
    """When a reuse output dir is resolved, inject_retry_reuse_params is invoked."""
    with TemporaryDirectory() as tmpdir:
        transitions = WorkflowTransitionBuilder()
        repo = MagicMock()
        payload = _payload()
        # Give the payload an algorithm_request dict so reuse injection has a target.
        payload = payload.model_copy(
            update={"algorithm_request": {"algorithm_params": {}}}
        )
        repo.get_run_request_json.return_value = payload.model_dump_json()
        repo.get_run.side_effect = [
            _build_run_status("run-old", ExecutionStatus.failed),
            _build_run_status("run-new", ExecutionStatus.accepted),
        ]
        repo.get_run_payload.return_value = None

        submit_fn = MagicMock(return_value=_accepted_response())
        dispatcher = RetryDispatcher(repo, MagicMock(), transitions, submit_fn)

        # Force a reuse dir that actually exists on disk.
        reuse_dir = Path(tmpdir) / "products" / "omega_sf"
        reuse_dir.mkdir(parents=True)
        with patch(
            "app.services.workflow.retry_dispatcher.resolve_reuse_output_dir",
            lambda repository, run_id: (str(reuse_dir), "omega_sf"),
        ):
            dispatcher.retry_workflow_run("run-old")

        submitted_payload = submit_fn.call_args.args[0]
        algo = submitted_payload.algorithm_request
        params = algo.get("algorithm_params") if isinstance(algo, dict) else getattr(algo, "algorithm_params", None)
        if isinstance(params, dict):
            assert params.get("reuse_block_cache") is True, (
                "reuse_block_cache must be injected when output dir is resolved"
            )
            assert params.get("reuse_output_dir") == str(reuse_dir), (
                "reuse_output_dir must be injected"
            )
