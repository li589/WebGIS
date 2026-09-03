"""僵尸工作流 run 回收任务回归锁（2026-08-25「任务长期卡排队中」根治）。

场景：Redis/Docker 重启或 worker 停机时 Celery 队列任务丢失，run 状态
停在 accepted/queued 永不推进。回收任务扫描超时无推进的 stuck run 并
CAS 标记 failed（可重试）；未超时/已推进的不动。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.celery_app import celery_app, celery_available
from app.services.workflow_repository import SQLiteWorkflowRepository
from app.tasks.workflow_reclaim_tasks import reclaim_stuck_workflow_runs
from shared.contracts.api_contracts import (
    ClientIdentity,
    EventChannel,
    ExecutionStatus,
    LogLevel,
    WorkflowCommandType,
    WorkflowEvent,
    WorkflowRunStatusResponse,
)


def _make_run(run_id: str, status: ExecutionStatus, updated_at: datetime) -> WorkflowRunStatusResponse:
    return WorkflowRunStatusResponse(
        run_id=run_id,
        command_type=WorkflowCommandType.analysis,
        status=status,
        progress=10,
        message="test",
        created_at=updated_at,
        updated_at=updated_at,
        client=ClientIdentity(),
    )


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """隔离的 SQLite 仓库（避免触碰真实 .data 库）。"""
    repository = SQLiteWorkflowRepository(state_dir=tmp_path)
    monkeypatch.setattr(
        "app.tasks.workflow_reclaim_tasks.SQLiteWorkflowRepository",
        lambda: repository,
    )
    return repository


def test_reclaim_task_registered_in_celery_app() -> None:
    """Beat 调度的 reclaim 任务须在 worker include 中注册，避免 unregistered task 丢弃。"""
    if not celery_available:
        pytest.skip("Celery not installed")
    assert "app.tasks.workflow_reclaim_tasks.reclaim_stuck_workflow_runs" in celery_app.tasks


def test_reclaims_stuck_accepted_run(repo, monkeypatch):
    """accepted 超时无推进 → CAS 标记 failed + 可重试消息。"""
    stuck_at = datetime.now(UTC) - timedelta(seconds=3600)
    repo.save_run(_make_run("run-stuck-1", ExecutionStatus.accepted, stuck_at))
    # 未超时的 queued run 不应被回收
    fresh_at = datetime.now(UTC) - timedelta(seconds=60)
    repo.save_run(_make_run("run-fresh-1", ExecutionStatus.queued, fresh_at))

    # settings 为 frozen dataclass；默认阈值即 1800s，无需 patch
    result = reclaim_stuck_workflow_runs()

    assert result["reclaimed"] == ["run-stuck-1"]
    reclaimed = repo.get_run("run-stuck-1")
    assert reclaimed.status == ExecutionStatus.failed
    assert "任务派发丢失" in reclaimed.message
    # 未超时 run 保持 queued
    assert repo.get_run("run-fresh-1").status == ExecutionStatus.queued


def test_terminal_runs_untouched(repo, monkeypatch):
    """终态 run（succeeded/failed/cancelled）不参与回收。"""
    old = datetime.now(UTC) - timedelta(seconds=7200)
    repo.save_run(_make_run("run-done", ExecutionStatus.succeeded, old))
    repo.save_run(_make_run("run-dead", ExecutionStatus.failed, old))

    # settings 为 frozen dataclass；默认阈值即 1800s，无需 patch
    result = reclaim_stuck_workflow_runs()

    assert result["reclaimed"] == []
    assert repo.get_run("run-done").status == ExecutionStatus.succeeded
    assert repo.get_run("run-dead").status == ExecutionStatus.failed


def test_running_runs_not_stuck_classified(repo, monkeypatch):
    """running 状态不属 stuck 集（长任务运行中由别的超时机制管）。"""
    old = datetime.now(UTC) - timedelta(seconds=7200)
    repo.save_run(_make_run("run-long", ExecutionStatus.running, old))

    # settings 为 frozen dataclass；默认阈值即 1800s，无需 patch
    result = reclaim_stuck_workflow_runs()

    assert result["reclaimed"] == []
    assert repo.get_run("run-long").status == ExecutionStatus.running


def test_reclaim_skips_queued_with_recent_events(repo):
    """queued 但 events 仍在推进 → 不算派发丢失（与 docstring「无事件推进」一致）。"""
    stuck_at = datetime.now(UTC) - timedelta(seconds=3600)
    repo.save_run(_make_run("run-events-alive", ExecutionStatus.queued, stuck_at))
    now = datetime.now(UTC)
    repo.append_event(
        WorkflowEvent(
            event_id="evt-recent-1",
            run_id="run-events-alive",
            channel=EventChannel.system,
            level=LogLevel.info,
            message="chunk progress",
            created_at=now - timedelta(seconds=30),
            progress=28,
            payload={},
        )
    )

    result = reclaim_stuck_workflow_runs()

    assert result["reclaimed"] == []
    assert repo.get_run("run-events-alive").status == ExecutionStatus.queued


def test_reclaim_does_not_overwrite_running_after_race(repo):
    """TOCTOU：list 时仍是 queued，CAS 前已推进到 running → 不得强写 failed。

    旧实现 save_run_cas(max_retries=3) 会把 expected 刷新为 running 后再覆盖，
    误杀正在执行的 heavy 长任务（SMAP ω 反演）。
    """
    stuck_at = datetime.now(UTC) - timedelta(seconds=3600)
    repo.save_run(_make_run("run-race-1", ExecutionStatus.queued, stuck_at))

    real_list = repo.list_runs

    def list_then_advance_to_running():
        runs = real_list()
        # 模拟 Beat reclaim 读完快照后、CAS 前，worker 已接手
        for run in runs:
            if run.run_id == "run-race-1":
                advanced = run.model_copy(deep=True)
                advanced.status = ExecutionStatus.running
                advanced.updated_at = datetime.now(UTC)
                advanced.message = "任务层开始调用业务服务。"
                repo.save_run(advanced)
        return runs

    repo.list_runs = list_then_advance_to_running  # type: ignore[method-assign]

    result = reclaim_stuck_workflow_runs()

    assert result["reclaimed"] == []
    live = repo.get_run("run-race-1")
    assert live is not None
    assert live.status == ExecutionStatus.running
    assert "任务派发丢失" not in (live.message or "")
