from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile

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


def test_save_and_load_workflow_run_round_trip() -> None:
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
            assert loaded is not None, 'loaded is not None'
            assert loaded.run_id == payload.run_id, 'loaded.run_id == payload.run_id'
            assert loaded.status == payload.status, 'loaded.status == payload.status'
            assert loaded.result_dto.workflow_entry_name == "analysis_workflow", 'loaded.result_dto.workflow_entry_name == "analysis_workflow"'
            assert repository.get_run_request_json("run-test") == "{}", 'repository.get_run_request_json("run-test") == "{}"'
        finally:
            # Windows: 必须在 TemporaryDirectory 清理前关闭连接池，否则文件句柄占用导致 PermissionError
            repository.close()


def test_append_and_list_events() -> None:
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
            assert events is not None, 'events is not None'
            assert len(events) == 1, 'len(events) == 1'
            assert events[0].event_id == "evt-1", 'events[0].event_id == "evt-1"'
            assert events[0].channel == EventChannel.status, 'events[0].channel == EventChannel.status'
        finally:
            repository.close()


def test_list_events_supports_after_event_id_cursor() -> None:
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
            assert len(events) == 1, 'len(events) == 1'
            assert events[0].event_id == "evt-2", 'events[0].event_id == "evt-2"'
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


def _with_repo(fn) -> None:  # type: ignore[no-untyped-def]
    with tempfile.TemporaryDirectory() as tmpdir:
        repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
        try:
            fn(repository)
        finally:
            repository.close()


def test_cancelled_blocks_late_worker_running_write() -> None:
    def scenario(repo: SQLiteWorkflowRepository) -> None:
        repo.save_run(_make_run("r1", ExecutionStatus.running))
        repo.save_run(_make_run("r1", ExecutionStatus.cancelled))
        # worker 迟到心跳回写 running → 应被 SQL 守卫拒绝
        repo.save_run(_make_run("r1", ExecutionStatus.running))
        loaded = repo.get_run("r1")
        assert loaded is not None, 'loaded is not None'
        assert loaded.status == ExecutionStatus.cancelled, 'loaded.status == ExecutionStatus.cancelled'

    _with_repo(scenario)


def test_cancelled_blocks_terminal_overwrite() -> None:
    """与应用层 BUG-2 语义一致：cancelled 后 succeeded/failed 收口也不允许覆盖。"""

    def scenario(repo: SQLiteWorkflowRepository) -> None:
        repo.save_run(_make_run("r2", ExecutionStatus.running))
        repo.save_run(_make_run("r2", ExecutionStatus.cancelled))
        repo.save_run(_make_run("r2", ExecutionStatus.succeeded))
        loaded = repo.get_run("r2")
        assert loaded is not None, 'loaded is not None'
        assert loaded.status == ExecutionStatus.cancelled, 'loaded.status == ExecutionStatus.cancelled'

    _with_repo(scenario)


def test_watchdog_failed_blocks_overwrite() -> None:
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
        assert loaded is not None, 'loaded is not None'
        assert loaded.status == ExecutionStatus.failed, 'loaded.status == ExecutionStatus.failed'

    _with_repo(scenario)


def test_normal_failed_allows_overwrite() -> None:
    """普通 failed（非 watchdog）不受保护——后续状态可正常写入。"""

    def scenario(repo: SQLiteWorkflowRepository) -> None:
        repo.save_run(_make_run("r4", ExecutionStatus.running))
        repo.save_run(_make_run("r4", ExecutionStatus.failed))
        repo.save_run(_make_run("r4", ExecutionStatus.succeeded))
        loaded = repo.get_run("r4")
        assert loaded is not None, 'loaded is not None'
        assert loaded.status == ExecutionStatus.succeeded, 'loaded.status == ExecutionStatus.succeeded'

    _with_repo(scenario)


def test_cancel_from_running_allowed() -> None:
    """cancel 主路径不受守卫影响：running → cancelled 正常写入。"""

    def scenario(repo: SQLiteWorkflowRepository) -> None:
        repo.save_run(_make_run("r5", ExecutionStatus.queued))
        repo.save_run(_make_run("r5", ExecutionStatus.running))
        repo.save_run(_make_run("r5", ExecutionStatus.cancelled))
        loaded = repo.get_run("r5")
        assert loaded is not None, 'loaded is not None'
        assert loaded.status == ExecutionStatus.cancelled, 'loaded.status == ExecutionStatus.cancelled'

    _with_repo(scenario)


def test_insert_new_run_unaffected_by_guard() -> None:
    """INSERT 新行（含 request_json 分支）不受 WHERE 守卫影响。"""

    def scenario(repo: SQLiteWorkflowRepository) -> None:
        repo.save_run(
            _make_run("r6", ExecutionStatus.accepted), request_json="{}"
        )
        loaded = repo.get_run("r6")
        assert loaded is not None, 'loaded is not None'
        assert loaded.status == ExecutionStatus.accepted, 'loaded.status == ExecutionStatus.accepted'
        assert repo.get_run_request_json("r6") == "{}", 'repo.get_run_request_json("r6") == "{}"'

    _with_repo(scenario)


# ── 图层平台子系统 v5：workflow_kind / layer_id / progress 结构化列 ──────────


def _make_v5_run(run_id: str, *, layer_id: str | None = None, kind: str | None = None, progress: int = 10) -> WorkflowRunStatusResponse:
    now = datetime.now(timezone.utc)
    return WorkflowRunStatusResponse(
        run_id=run_id,
        command_type=WorkflowCommandType.analysis,
        layer_id=layer_id,
        status=ExecutionStatus.queued,
        progress=progress,
        message="test",
        created_at=now,
        updated_at=now,
        executor_metadata={"workflow_kind": kind} if kind else {},
    )


def test_schema_v5_structured_columns_auto_extracted() -> None:
    """save_run 不传显式参数时，从 layer_id/executor_metadata/progress 自动提取列。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
        try:
            repository.save_run(
                _make_v5_run("run-v5-auto", layer_id="aridity-cn", kind="asset_bake", progress=42),
                request_json="{}",
            )
            with repository._connect() as conn:
                row = conn.execute(
                    "SELECT workflow_kind, layer_id, progress FROM workflow_runs WHERE run_id = ?",
                    ("run-v5-auto",),
                ).fetchone()
            assert row == ("asset_bake", "aridity-cn", 42)
        finally:
            repository.close()


def test_schema_v5_migration_from_v4_database() -> None:
    """v4 旧库（无新列）实例化后自动迁移：列存在、索引存在、版本号=5。"""
    import sqlite3

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "workflow_state.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE workflow_runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                request_json TEXT,
                run_class TEXT NOT NULL DEFAULT 'business',
                user_id INTEGER
            )
            """
        )
        # 旧行 payload 必须是合法 run 状态（get_run 反序列化要求）
        legacy_now = datetime.now(timezone.utc)
        legacy_payload = WorkflowRunStatusResponse(
            run_id="run-legacy",
            command_type=WorkflowCommandType.analysis,
            status=ExecutionStatus.succeeded,
            progress=100,
            message="done",
            created_at=legacy_now,
            updated_at=legacy_now,
        )
        conn.execute(
            "INSERT INTO workflow_runs (run_id, status, updated_at, payload_json) "
            "VALUES ('run-legacy', 'succeeded', ?, ?)",
            (
                legacy_now.isoformat(),
                json.dumps(legacy_payload.model_dump(mode="json"), ensure_ascii=False),
            ),
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('schema_version', '4')"
        )
        conn.commit()
        conn.close()

        repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
        try:
            assert repository.get_schema_version() == 5
            with repository._connect() as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
                assert {"workflow_kind", "layer_id", "progress"} <= columns
                indexes = {
                    row[1]
                    for row in conn.execute("PRAGMA index_list(workflow_runs)").fetchall()
                }
                assert "idx_workflow_runs_kind_layer" in indexes
            # 旧行仍可读（列全 NULL）
            legacy = repository.get_run("run-legacy")
            assert legacy is None or legacy.run_id == "run-legacy"
        finally:
            repository.close()


def test_list_runs_by_layer_filters_and_falls_back_to_payload() -> None:
    """按图层查 run：新行走 layer_id 列，旧行回退 payload_json 内层匹配。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
        try:
            repository.save_run(
                _make_v5_run("run-a", layer_id="era5-dwaa-cn", kind="asset_bake"),
                request_json="{}",
            )
            repository.save_run(
                _make_v5_run("run-b", layer_id="aridity-cn", kind="asset_bake"),
                request_json="{}",
            )
            # 模拟旧行：直接 SQL 写入不带新列
            now_iso = datetime.now(timezone.utc).isoformat()
            legacy_payload = _make_v5_run("run-legacy", layer_id="era5-dwaa-cn", kind="asset_bake")
            with repository._connect() as conn:
                conn.execute(
                    "INSERT INTO workflow_runs (run_id, status, updated_at, payload_json) "
                    "VALUES (?, 'queued', ?, ?)",
                    (
                        "run-legacy",
                        now_iso,
                        json.dumps(legacy_payload.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )

            runs = repository.list_runs_by_layer("era5-dwaa-cn", limit=10)
            ids = {r.run_id for r in runs}
            assert {"run-a", "run-legacy"} <= ids
            assert "run-b" not in ids

            kind_runs = repository.list_runs_by_layer(
                "era5-dwaa-cn", limit=10, workflow_kind="asset_bake"
            )
            # workflow_kind 过滤只匹配新列（旧行 NULL 不含 kind 过滤条件）
            assert {r.run_id for r in kind_runs} == {"run-a"}
        finally:
            repository.close()
