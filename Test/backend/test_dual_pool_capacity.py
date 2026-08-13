"""Tests for dual-pool run_class capacity helpers and repository counting."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from app.services.workflow.run_class import (
    RUN_CLASS_BUSINESS,
    RUN_CLASS_WEATHER_TILE,
    resolve_workflow_run_class,
)
from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ClientIdentity,
    ExecutionStatus,
    RuntimeMapContext,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
)


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


def test_business_default() -> None:
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        layer_id="ref-smap-sm-202512-l3",
        requested_outputs=["json"],
    )
    assert resolve_workflow_run_class(payload) == RUN_CLASS_BUSINESS, 'resolve_workflow_run_class(payload) == RUN_CLASS_BUSINESS'


def test_weather_tile_node_classifies_as_weather_tile() -> None:
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        layer_id="wind-field",
        requested_outputs=["json"],
        weather_request={
            "workflow_id": "wf-tile",
            "workflow": {
                "workflow_id": "wf-tile",
                "nodes": [
                    {
                        "node_id": "tile-render",
                        "node_type": "weather_tile_render",
                        "params": {
                            "layer_id": "wind-field",
                            "z": 3,
                            "x": 1,
                            "y": 2,
                        },
                    }
                ],
                "edges": [],
            },
        },
    )
    assert resolve_workflow_run_class(payload) == RUN_CLASS_WEATHER_TILE, 'resolve_workflow_run_class(payload) == RUN_CLASS_WEATHER_TILE'


def test_count_active_runs_filters_by_run_class() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
        try:
            repository.save_run(
                _status("run-biz-1"),
                request_json="{}",
                run_class=RUN_CLASS_BUSINESS,
            )
            repository.save_run(
                _status("run-biz-2"),
                request_json="{}",
                run_class=RUN_CLASS_BUSINESS,
            )
            repository.save_run(
                _status("run-tile-1"),
                request_json="{}",
                run_class=RUN_CLASS_WEATHER_TILE,
            )
            repository.save_run(
                _status("run-done", status=ExecutionStatus.succeeded),
                request_json="{}",
                run_class=RUN_CLASS_BUSINESS,
            )

            assert repository.count_active_runs() == 3, 'repository.count_active_runs() == 3'
            assert repository.count_active_runs(run_class=RUN_CLASS_BUSINESS) == 2, 'repository.count_active_runs(run_class=RUN_CLASS_BUSINESS) == 2'
            assert repository.count_active_runs(run_class=RUN_CLASS_WEATHER_TILE) == 1, 'repository.count_active_runs(run_class=RUN_CLASS_WEATHER_TILE) == 1'
        finally:
            # Windows: 必须在 TemporaryDirectory 清理前关闭连接池，否则文件句柄占用导致 PermissionError
            repository.close()


def test_status_update_preserves_run_class() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
        try:
            repository.save_run(
                _status("run-tile"),
                request_json="{}",
                run_class=RUN_CLASS_WEATHER_TILE,
            )
            repository.save_run(_status("run-tile", status=ExecutionStatus.running))
            assert repository.count_active_runs(run_class=RUN_CLASS_WEATHER_TILE) == 1, 'repository.count_active_runs(run_class=RUN_CLASS_WEATHER_TILE) == 1'
            assert repository.count_active_runs(run_class=RUN_CLASS_BUSINESS) == 0, 'repository.count_active_runs(run_class=RUN_CLASS_BUSINESS) == 0'
        finally:
            repository.close()


def test_count_active_runs_includes_retry_pending() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
        try:
            repository.save_run(
                _status("run-retry", status=ExecutionStatus.retry_pending),
                request_json="{}",
                run_class=RUN_CLASS_BUSINESS,
            )
            assert repository.count_active_runs(run_class=RUN_CLASS_BUSINESS) == 1, 'repository.count_active_runs(run_class=RUN_CLASS_BUSINESS) == 1'
        finally:
            repository.close()


def test_save_run_under_capacity_rejects_when_full() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
        try:
            repository.save_run(
                _status("run-biz-1"),
                request_json="{}",
                run_class=RUN_CLASS_BUSINESS,
            )
            with pytest.raises(ValueError) as ctx:
                repository.save_run_under_capacity(
                    _status("run-biz-2"),
                    request_json="{}",
                    run_class=RUN_CLASS_BUSINESS,
                    limit=1,
                )
            assert "capacity reached" in str(ctx.value).lower(), '"capacity reached" in str(ctx.exception).lower()'
            assert repository.count_active_runs(run_class=RUN_CLASS_BUSINESS) == 1, 'repository.count_active_runs(run_class=RUN_CLASS_BUSINESS) == 1'
        finally:
            repository.close()


def test_save_run_under_capacity_accepts_within_limit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
        try:
            repository.save_run_under_capacity(
                _status("run-biz-1"),
                request_json="{}",
                run_class=RUN_CLASS_BUSINESS,
                limit=2,
            )
            repository.save_run_under_capacity(
                _status("run-biz-2"),
                request_json="{}",
                run_class=RUN_CLASS_BUSINESS,
                limit=2,
            )
            assert repository.count_active_runs(run_class=RUN_CLASS_BUSINESS) == 2, 'repository.count_active_runs(run_class=RUN_CLASS_BUSINESS) == 2'
        finally:
            repository.close()


def test_save_run_under_capacity_is_atomic_under_contention() -> None:
    import threading

    with tempfile.TemporaryDirectory() as tmpdir:
        repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
        try:
            results: list[str] = []
            barrier = threading.Barrier(8)

            def try_reserve(idx: int) -> None:
                barrier.wait(timeout=5)
                try:
                    repository.save_run_under_capacity(
                        _status(f"run-c-{idx}"),
                        request_json="{}",
                        run_class=RUN_CLASS_BUSINESS,
                        limit=3,
                    )
                    results.append("ok")
                except ValueError:
                    results.append("reject")

            threads = [
                threading.Thread(target=try_reserve, args=(i,)) for i in range(8)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            assert results.count("ok") == 3, 'results.count("ok") == 3'
            assert results.count("reject") == 5, 'results.count("reject") == 5'
            assert repository.count_active_runs(run_class=RUN_CLASS_BUSINESS) == 3, 'repository.count_active_runs(run_class=RUN_CLASS_BUSINESS) == 3'
        finally:
            repository.close()
