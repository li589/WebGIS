from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ExecutionStatus,
    EventChannel,
    ResultKind,
    WorkflowAnalysisResultDto,
    WorkflowEvent,
    WorkflowPriority,
    WorkflowResultReference,
    WorkflowRunStatusResponse,
    WorkflowCommandType,
    RuntimeMapContext,
    ClientIdentity,
)


class WorkflowRepositoryTests(unittest.TestCase):
    def test_save_and_load_workflow_run_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                now = datetime.now(timezone.utc)
                payload = WorkflowRunStatusResponse(
                    run_id="run-test",
                    status_url="/workflow-runs/run-test",
                    events_url="/workflow-runs/run-test/events",
                    command_type=WorkflowCommandType.analysis,
                    layer_id="wind-field",
                    priority=WorkflowPriority.normal,
                    status=ExecutionStatus.running,
                    progress=35,
                    message="running",
                    created_at=now,
                    updated_at=now,
                    client=ClientIdentity(client_id="client-1"),
                    map_context=RuntimeMapContext(active_layer_id="wind-field"),
                    result_dto=WorkflowAnalysisResultDto(
                        workflow_entry_name="analysis_workflow",
                        layer_id="wind-field",
                        requested_hour=12.0,
                        metric_label="NDVI",
                        metric_value=0.7,
                        metric_unit="index",
                        hotspot_count=2,
                    ),
                    result_refs=[
                        WorkflowResultReference(
                            result_id="ref-1",
                            result_kind=ResultKind.json,
                            title="result",
                            mime_type="application/json",
                            inline_data={"ok": True},
                            updated_at=now,
                        )
                    ],
                    diagnostics=["ok"],
                )

                repository.save_run(payload, request_json="{}")
                loaded = repository.get_run("run-test")
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.run_id, payload.run_id)
                self.assertEqual(loaded.status, payload.status)
                self.assertEqual(
                    loaded.result_dto.workflow_entry_name, "analysis_workflow"
                )
                self.assertEqual(repository.get_run_request_json("run-test"), "{}")
            finally:
                # Windows: 必须在 TemporaryDirectory 清理前关闭连接池，否则文件句柄占用导致 PermissionError
                repository.close()

    def test_append_and_list_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                now = datetime.now(timezone.utc)
                event = WorkflowEvent(
                    event_id="evt-1",
                    run_id="run-test",
                    channel=EventChannel.status,
                    message="created",
                    created_at=now,
                )
                repository.append_event(event)

                events = repository.list_events("run-test")
                self.assertIsNotNone(events)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].event_id, "evt-1")
                self.assertEqual(events[0].channel, EventChannel.status)
            finally:
                repository.close()

    def test_list_events_supports_after_event_id_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                now = datetime.now(timezone.utc)
                repository.append_event(
                    WorkflowEvent(
                        event_id="evt-1",
                        run_id="run-test",
                        channel=EventChannel.status,
                        message="accepted",
                        created_at=now,
                    )
                )
                repository.append_event(
                    WorkflowEvent(
                        event_id="evt-2",
                        run_id="run-test",
                        channel=EventChannel.system,
                        message="running",
                        created_at=now,
                    )
                )

                events = repository.list_events("run-test", after_event_id="evt-1")
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].event_id, "evt-2")
            finally:
                repository.close()


def _make_run(
    run_id: str,
    status: ExecutionStatus,
    *,
    executor_metadata: dict | None = None,
) -> WorkflowRunStatusResponse:
    """构造最小合法 run 状态（终态守卫测试用）。"""
    now = datetime.now(timezone.utc)
    return WorkflowRunStatusResponse(
        run_id=run_id,
        command_type=WorkflowCommandType.analysis,
        status=status,
        progress=100 if status != ExecutionStatus.running else 50,
        message=status.value,
        created_at=now,
        updated_at=now,
        executor_metadata=executor_metadata or {},
    )


class WorkflowRunTerminalGuardTests(unittest.TestCase):
    """C4：SQL 层终态守卫——cancelled / watchdog-failed 拒绝任何覆盖写（防状态回滚）。"""

    def _with_repo(self, fn) -> None:  # type: ignore[no-untyped-def]
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            try:
                fn(repository)
            finally:
                repository.close()

    def test_cancelled_blocks_late_worker_running_write(self) -> None:
        def scenario(repo: SQLiteWorkflowRepository) -> None:
            repo.save_run(_make_run("r1", ExecutionStatus.running))
            repo.save_run(_make_run("r1", ExecutionStatus.cancelled))
            # worker 迟到心跳回写 running → 应被 SQL 守卫拒绝
            repo.save_run(_make_run("r1", ExecutionStatus.running))
            loaded = repo.get_run("r1")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.status, ExecutionStatus.cancelled)

        self._with_repo(scenario)

    def test_cancelled_blocks_terminal_overwrite(self) -> None:
        """与应用层 BUG-2 语义一致：cancelled 后 succeeded/failed 收口也不允许覆盖。"""

        def scenario(repo: SQLiteWorkflowRepository) -> None:
            repo.save_run(_make_run("r2", ExecutionStatus.running))
            repo.save_run(_make_run("r2", ExecutionStatus.cancelled))
            repo.save_run(_make_run("r2", ExecutionStatus.succeeded))
            loaded = repo.get_run("r2")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.status, ExecutionStatus.cancelled)

        self._with_repo(scenario)

    def test_watchdog_failed_blocks_overwrite(self) -> None:
        def scenario(repo: SQLiteWorkflowRepository) -> None:
            repo.save_run(_make_run("r3", ExecutionStatus.running))
            repo.save_run(
                _make_run(
                    "r3",
                    ExecutionStatus.failed,
                    executor_metadata={"cleanup_reason": "stuck_running_watchdog"},
                )
            )
            # worker 迟到的成功回写 → 拒绝
            repo.save_run(_make_run("r3", ExecutionStatus.succeeded))
            loaded = repo.get_run("r3")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.status, ExecutionStatus.failed)

        self._with_repo(scenario)

    def test_normal_failed_allows_overwrite(self) -> None:
        """普通 failed（非 watchdog）不受保护——后续状态可正常写入。"""

        def scenario(repo: SQLiteWorkflowRepository) -> None:
            repo.save_run(_make_run("r4", ExecutionStatus.running))
            repo.save_run(_make_run("r4", ExecutionStatus.failed))
            repo.save_run(_make_run("r4", ExecutionStatus.succeeded))
            loaded = repo.get_run("r4")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.status, ExecutionStatus.succeeded)

        self._with_repo(scenario)

    def test_cancel_from_running_allowed(self) -> None:
        """cancel 主路径不受守卫影响：running → cancelled 正常写入。"""

        def scenario(repo: SQLiteWorkflowRepository) -> None:
            repo.save_run(_make_run("r5", ExecutionStatus.queued))
            repo.save_run(_make_run("r5", ExecutionStatus.running))
            repo.save_run(_make_run("r5", ExecutionStatus.cancelled))
            loaded = repo.get_run("r5")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.status, ExecutionStatus.cancelled)

        self._with_repo(scenario)

    def test_insert_new_run_unaffected_by_guard(self) -> None:
        """INSERT 新行（含 request_json 分支）不受 WHERE 守卫影响。"""

        def scenario(repo: SQLiteWorkflowRepository) -> None:
            repo.save_run(
                _make_run("r6", ExecutionStatus.accepted), request_json="{}"
            )
            loaded = repo.get_run("r6")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.status, ExecutionStatus.accepted)
            self.assertEqual(repo.get_run_request_json("r6"), "{}")

        self._with_repo(scenario)


if __name__ == "__main__":
    unittest.main()
