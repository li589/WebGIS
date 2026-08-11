"""Tests for CAS (Compare-And-Swap) optimistic locking in workflow_repository.py
and lifecycle_service's handling of ConcurrentModificationError.

Covers G2-02: Workflow CAS Locking + Lifecycle Failure Paths.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.workflow_repository import (
    ConcurrentModificationError,
    SQLiteWorkflowRepository,
)
from app.services.workflow.lifecycle_service import WorkflowLifecycleService
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.transition_builder import WorkflowTransitionBuilder
from shared.contracts.api_contracts import (
    ClientIdentity,
    ExecutionStatus,
    FailureCategory,
    RuntimeMapContext,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
)


# ---------------------------------------------------------------------------
# Helpers (mirrors the pattern in test_dual_pool_capacity.py)
# ---------------------------------------------------------------------------


def _status(
    run_id: str, status: ExecutionStatus = ExecutionStatus.running
) -> WorkflowRunStatusResponse:
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


def _payload() -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="cas test",
        priority=WorkflowPriority.normal,
        requested_outputs=[],
    )


def _make_running_run(
    repository: SQLiteWorkflowRepository,
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


class WorkflowCASLockingTests(unittest.TestCase):
    """CAS optimistic locking: repository.save_run_cas + lifecycle CAS conflict paths."""

    # --- repository.save_run_cas direct tests ---

    def test_save_run_cas_success(self) -> None:
        """CAS update from running→succeeded with expected_status=running succeeds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                repository.save_run(
                    _status("run-1", status=ExecutionStatus.running),
                    request_json="{}",
                )
                result = repository.save_run_cas(
                    _status("run-1", status=ExecutionStatus.succeeded),
                    expected_status=ExecutionStatus.running,
                )
                self.assertTrue(result)
                run = repository.get_run("run-1")
                self.assertIsNotNone(run)
                self.assertEqual(run.status, ExecutionStatus.succeeded)
            finally:
                repository.close()

    def test_save_run_cas_terminal_conflict_raises(self) -> None:
        """CAS update fails when run was externally changed to a terminal state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                repository.save_run(
                    _status("run-2", status=ExecutionStatus.running),
                    request_json="{}",
                )
                # Externally update to succeeded (terminal)
                repository.save_run(
                    _status("run-2", status=ExecutionStatus.succeeded),
                )
                # CAS update to failed with expected_status=running should raise
                with self.assertRaises(ConcurrentModificationError):
                    repository.save_run_cas(
                        _status("run-2", status=ExecutionStatus.failed),
                        expected_status=ExecutionStatus.running,
                    )
            finally:
                repository.close()

    def test_save_run_cas_non_terminal_conflict_retries(self) -> None:
        """CAS retries when status is non-terminal but different from expected.

        Run is created with status=queued. CAS update with expected_status=running
        fails on the first attempt (DB is queued, not running). The method re-reads
        the status (queued, non-terminal), updates expected to queued, and retries
        successfully on the second attempt.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                repository.save_run(
                    _status("run-3", status=ExecutionStatus.queued),
                    request_json="{}",
                )
                result = repository.save_run_cas(
                    _status("run-3", status=ExecutionStatus.succeeded),
                    expected_status=ExecutionStatus.running,
                )
                self.assertTrue(result)
                run = repository.get_run("run-3")
                self.assertIsNotNone(run)
                self.assertEqual(run.status, ExecutionStatus.succeeded)
            finally:
                repository.close()

    def test_save_run_cas_retries_exhausted_raises(self) -> None:
        """CAS raises after max_retries when status keeps changing (simulated via mock).

        The DB status stays 'queued' throughout. Mocked get_run cycles through
        non-terminal statuses [accepted, running] so that `expected` never matches
        the DB. After max_retries, ConcurrentModificationError is raised.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                repository.save_run(
                    _status("run-4", status=ExecutionStatus.queued),
                    request_json="{}",
                )
                cycle = [ExecutionStatus.accepted, ExecutionStatus.running]
                call_count = 0

                def mock_get_run(run_id: str):
                    nonlocal call_count
                    status = cycle[call_count % len(cycle)]
                    call_count += 1
                    return _status(run_id, status=status)

                with patch.object(repository, "get_run", side_effect=mock_get_run):
                    with self.assertRaises(ConcurrentModificationError):
                        repository.save_run_cas(
                            _status("run-4", status=ExecutionStatus.failed),
                            expected_status=ExecutionStatus.running,
                            max_retries=3,
                        )
            finally:
                repository.close()

    def test_save_run_cas_run_not_found_raises(self) -> None:
        """CAS update on a non-existent run_id raises ConcurrentModificationError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                with self.assertRaises(ConcurrentModificationError) as ctx:
                    repository.save_run_cas(
                        _status("nonexistent-run", status=ExecutionStatus.succeeded),
                        expected_status=ExecutionStatus.running,
                    )
                self.assertIn("not found", str(ctx.exception).lower())
            finally:
                repository.close()

    # --- persistence delegation ---

    def test_save_run_status_cas_delegates(self) -> None:
        """WorkflowPersistenceService.save_run_status_cas delegates to repository.save_run_cas."""
        mock_repo = MagicMock()
        mock_repo.save_run_cas.return_value = True
        persistence = WorkflowPersistenceService(mock_repo)

        run_status = _status("run-6", status=ExecutionStatus.succeeded)
        result = persistence.save_run_status_cas(
            run_status=run_status,
            expected_status=ExecutionStatus.running,
            request_json="{}",
            run_class="business",
        )

        self.assertTrue(result)
        mock_repo.save_run_cas.assert_called_once_with(
            run_status,
            expected_status=ExecutionStatus.running,
            request_json="{}",
            run_class="business",
            result_dto_override=None,
        )

    # --- lifecycle CAS conflict handling ---

    def test_lifecycle_finalize_success_cas_conflict_skips(self) -> None:
        """finalize_workflow_success catches ConcurrentModificationError and skips."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                persistence = WorkflowPersistenceService(repository)
                transitions = WorkflowTransitionBuilder()
                lifecycle = WorkflowLifecycleService(
                    repository, persistence, transitions
                )
                now = _make_running_run(
                    repository, persistence, transitions, "run-cas-success", _payload()
                )

                execution = SimpleNamespace(
                    result_refs=[],
                    diagnostics=[],
                    result_dto=None,
                    message="would have succeeded",
                    follow_up_tasks=[],
                )

                with patch.object(
                    persistence,
                    "save_run_status_cas",
                    side_effect=ConcurrentModificationError("CAS conflict test"),
                ):
                    # Should not raise — catches and returns
                    lifecycle.finalize_workflow_success(
                        run_id="run-cas-success",
                        payload=_payload(),
                        execution=execution,
                        requested_at=now,
                    )

                # Run should still be running (CAS conflict skipped)
                run = repository.get_run("run-cas-success")
                self.assertIsNotNone(run)
                self.assertEqual(run.status, ExecutionStatus.running)
            finally:
                repository.close()

    def test_lifecycle_finalize_failure_cas_conflict_skips(self) -> None:
        """finalize_workflow_failure catches ConcurrentModificationError and skips."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                persistence = WorkflowPersistenceService(repository)
                transitions = WorkflowTransitionBuilder()
                lifecycle = WorkflowLifecycleService(
                    repository, persistence, transitions
                )
                now = _make_running_run(
                    repository, persistence, transitions, "run-cas-failure", _payload()
                )

                with patch.object(
                    persistence,
                    "save_run_status_cas",
                    side_effect=ConcurrentModificationError("CAS conflict test"),
                ):
                    # Should not raise — catches and returns
                    lifecycle.finalize_workflow_failure(
                        run_id="run-cas-failure",
                        payload=_payload(),
                        created_at=now,
                        exc=RuntimeError("something went wrong"),
                        category=FailureCategory.terminal_failure,
                    )

                # Run should still be running (CAS conflict skipped)
                run = repository.get_run("run-cas-failure")
                self.assertIsNotNone(run)
                self.assertEqual(run.status, ExecutionStatus.running)
            finally:
                repository.close()

    def test_lifecycle_cancel_cas_conflict_raises_valueerror(self) -> None:
        """cancel_workflow_run raises ValueError when CAS conflict occurs.

        The CAS write fails (simulated), the handler re-reads the run and finds
        it non-terminal (still running), so raises ValueError with 'concurrently'.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                persistence = WorkflowPersistenceService(repository)
                transitions = WorkflowTransitionBuilder()
                lifecycle = WorkflowLifecycleService(
                    repository, persistence, transitions
                )
                _make_running_run(
                    repository, persistence, transitions, "run-cas-cancel", _payload()
                )

                with patch.object(
                    persistence,
                    "save_run_status_cas",
                    side_effect=ConcurrentModificationError("CAS conflict test"),
                ):
                    with self.assertRaises(ValueError) as ctx:
                        lifecycle.cancel_workflow_run("run-cas-cancel")
                    self.assertIn("concurrently", str(ctx.exception).lower())

                # Run should still be running (cancel was not persisted)
                run = repository.get_run("run-cas-cancel")
                self.assertIsNotNone(run)
                self.assertEqual(run.status, ExecutionStatus.running)
            finally:
                repository.close()

    # --- concurrent CAS ---

    def test_concurrent_cas_only_one_wins(self) -> None:
        """Two threads CAS the same run; only one succeeds, the other gets conflict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                repository.save_run(
                    _status("run-race", status=ExecutionStatus.running),
                    request_json="{}",
                )

                results: list[str] = []
                barrier = threading.Barrier(2)

                def cas_thread(target_status: ExecutionStatus) -> None:
                    barrier.wait(timeout=5)
                    try:
                        repository.save_run_cas(
                            _status("run-race", status=target_status),
                            expected_status=ExecutionStatus.running,
                        )
                        results.append("success")
                    except ConcurrentModificationError:
                        results.append("conflict")

                t1 = threading.Thread(
                    target=cas_thread, args=(ExecutionStatus.succeeded,)
                )
                t2 = threading.Thread(
                    target=cas_thread, args=(ExecutionStatus.failed,)
                )
                t1.start()
                t2.start()
                t1.join(timeout=30)
                t2.join(timeout=30)

                self.assertEqual(results.count("success"), 1)
                self.assertEqual(results.count("conflict"), 1)

                final = repository.get_run("run-race")
                self.assertIsNotNone(final)
                self.assertIn(
                    final.status,
                    (ExecutionStatus.succeeded, ExecutionStatus.failed),
                )
            finally:
                repository.close()


if __name__ == "__main__":
    unittest.main()
