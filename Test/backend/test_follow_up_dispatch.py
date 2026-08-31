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
    """A running run with no activity older than the idle threshold is marked failed."""
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


def test_fail_stuck_running_skips_when_events_show_activity():
    """Stale updated_at must not kill a run that still emits progress events.

    Mid-run progress often only appends workflow_events and never bumps
    workflow_runs.updated_at (e.g. long NSIDC downloads). Idle watchdog must
    treat the latest event timestamp as activity.
    """
    from shared.contracts.api_contracts import EventChannel, LogLevel, WorkflowEvent

    with TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, svc = _real_services(tmpdir)
        try:
            past = datetime.now(UTC) - timedelta(hours=3)
            now = datetime.now(UTC)
            payload = _payload()
            repository.save_run(
                transitions.build_execution_transition(
                    run_id="run-alive-download",
                    payload=payload,
                    status=ExecutionStatus.running,
                    progress=7,
                    message="下载中",
                    created_at=past,
                    updated_at=past,
                )
            )
            repository.append_event(
                WorkflowEvent(
                    event_id="evt-progress-alive",
                    run_id="run-alive-download",
                    channel=EventChannel.log,
                    level=LogLevel.info,
                    message="文件 21/31 · 已下载 288.00 MB · 256 KB/s",
                    progress=7,
                    payload={"node_progress": {"node_id": "nsidc_smap_download"}},
                    created_at=now,
                )
            )

            failed = svc.fail_stuck_running_workflows(max_running_seconds=60)

            assert failed == 0, "active progress events must keep the run running"
            run = repository.get_run("run-alive-download")
            assert run is not None and run.status == ExecutionStatus.running
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
        FollowUpDispatchService, "_collect_live_celery_tasks", lambda self: (set(), set())
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


def test_cleanup_stale_keeps_run_with_queue_resident_message(monkeypatch):
    """排队驻留在 broker 队列里的 run（worker 忙碌积压）不得被误标 orphaned。

    回归：原实现只查 active/reserved/unacked，队列驻留消息不可见；worker 被
    长任务占用时合法 run 会在 FastAPI 重启后被启动清理误杀。run_id 级匹配
    还覆盖 task_id 副本与 metadata 记录不一致（重派发去重后）的场景。
    """
    monkeypatch.setattr(
        FollowUpDispatchService,
        "_collect_live_celery_tasks",
        lambda self: (set(), {"run-queued-live"}),
    )
    with TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, svc = _real_services(tmpdir)
        try:
            past = datetime.now(UTC) - timedelta(hours=3)
            payload = _payload()
            repository.save_run(
                transitions.build_execution_transition(
                    run_id="run-queued-live",
                    payload=payload,
                    status=ExecutionStatus.queued,
                    progress=18,
                    message="queued",
                    created_at=past,
                    updated_at=past,
                    executor_metadata={"task_id": "removed-duplicate-task"},
                )
            )
            assert svc.cleanup_stale_workflow_runs() == 0, (
                "queue-resident run must be treated as live"
            )
            run = repository.get_run("run-queued-live")
            assert run.status == ExecutionStatus.queued, "live queued run must survive"
        finally:
            repository.close()


def test_cleanup_stale_fails_orphaned_queued_run(monkeypatch):
    """超宽限且 broker 中确无对应消息（task_id 与 run_id 均不命中）的 run 被清理。"""
    monkeypatch.setattr(
        FollowUpDispatchService, "_collect_live_celery_tasks", lambda self: (set(), set())
    )
    with TemporaryDirectory() as tmpdir:
        repository, persistence, transitions, svc = _real_services(tmpdir)
        try:
            past = datetime.now(UTC) - timedelta(hours=3)
            payload = _payload()
            repository.save_run(
                transitions.build_execution_transition(
                    run_id="run-orphaned",
                    payload=payload,
                    status=ExecutionStatus.queued,
                    progress=18,
                    message="queued",
                    created_at=past,
                    updated_at=past,
                    executor_metadata={"task_id": "vanished-task"},
                )
            )
            assert svc.cleanup_stale_workflow_runs() == 1, (
                "orphaned queued run must be cleaned"
            )
            run = repository.get_run("run-orphaned")
            assert run.status == ExecutionStatus.failed, "orphaned run must be failed"
        finally:
            repository.close()
