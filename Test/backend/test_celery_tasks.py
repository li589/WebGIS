"""Celery 任务层集成测试（发布就绪 P1-9）。

app/tasks/ 的 weather_tasks / workflow_timer_tasks / import_tasks / cleanup_tasks 此前
0% 覆盖。本文件对各任务的 execute_* 入口与 Celery 包装器做 mock 级集成测试：
- 验证 execute_* 正确调用底层服务并返回结构化结果；
- 验证 Celery 包装器在底层抛异常时捕获并返回错误 dict（不向上炸）。
"""

from __future__ import annotations

from unittest import mock

import pytest

from app.tasks import cleanup_tasks, workflow_timer_tasks


# ── cleanup_tasks.execute_workflow_runs_cleanup ─────────────────────────────
def test_execute_workflow_runs_cleanup_calls_repository() -> None:
    with mock.patch(
        "app.services.workflow_repository.SQLiteWorkflowRepository"
    ) as repo_cls:
        repo_cls.return_value.cleanup_old_runs.return_value = {
            "runs_deleted": 3,
            "events_deleted": 9,
        }
        out = cleanup_tasks.execute_workflow_runs_cleanup(
            retention_days=15, vacuum=True
        )
    repo_cls.return_value.cleanup_old_runs.assert_called_once_with(
        retention_days=15, vacuum=True
    )
    assert out["runs_deleted"] == 3
    assert out["retention_days"] == 15


# ── cleanup_tasks.execute_cache_cleanup ─────────────────────────────────────
def test_execute_cache_cleanup_calls_cache_service() -> None:
    with mock.patch(
        "app.services.cache_service.cache_service"
    ) as cache_service:
        cache_service.cleanup_expired.return_value = {"removed": 5}
        out = cleanup_tasks.execute_cache_cleanup()
    cache_service.cleanup_expired.assert_called_once_with()
    assert out["removed"] == 5


# ── cleanup_tasks.execute_stuck_workflow_watchdog（P1-4 看门狗）─────────────
def test_execute_stuck_workflow_watchdog_calls_service() -> None:
    with mock.patch(
        "app.services.workflow.service_container.follow_up_dispatch_service"
    ) as svc, mock.patch(
        "app.tasks.cleanup_tasks.settings"
    ) as st:
        st.workflow_stuck_watchdog_seconds = 8100
        svc.fail_stuck_running_workflows.return_value = 2
        out = cleanup_tasks.execute_stuck_workflow_watchdog()
    svc.fail_stuck_running_workflows.assert_called_once_with(
        max_running_seconds=8100
    )
    assert out["marked_failed"] == 2
    assert out["threshold_seconds"] == 8100


# ── workflow_timer_tasks.execute_timer_tick ─────────────────────────────────
def test_execute_timer_tick_calls_tick() -> None:
    with mock.patch("app.services.workflow_timer_service.tick") as tick:
        tick.return_value = {"checked": 4, "fired": 1, "failed": 0, "skipped": 0}
        out = workflow_timer_tasks.execute_timer_tick()
    tick.assert_called_once_with()
    assert out["fired"] == 1


# ── Celery 包装器：底层抛异常时捕获并返回错误 dict ──────────────────────────
@pytest.mark.skipif(
    cleanup_tasks.celery_app is None, reason="celery not available"
)
def test_cleanup_cache_files_task_wrapper_catches_exception() -> None:
    with mock.patch(
        "app.tasks.cleanup_tasks.execute_cache_cleanup",
        side_effect=RuntimeError("boom"),
    ):
        out = cleanup_tasks.cleanup_cache_files()
    assert out == {"error": "cleanup_failed"}


@pytest.mark.skipif(
    workflow_timer_tasks.celery_app is None, reason="celery not available"
)
def test_tick_workflow_timers_task_wrapper_catches_exception() -> None:
    with mock.patch(
        "app.tasks.workflow_timer_tasks.execute_timer_tick",
        side_effect=RuntimeError("boom"),
    ):
        out = workflow_timer_tasks.tick_workflow_timers()
    assert out["error"] == "tick_failed"
    assert out["checked"] == 0
