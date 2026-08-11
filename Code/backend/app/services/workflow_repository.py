from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services._sqlite_pool import SQLiteConnectionPool
from shared.contracts.api_contracts import (
    ExecutionStatus,
    RuntimeConfigPatch,
    WorkflowEvent,
    WorkflowRunStatusResponse,
)
import contextlib

DEFAULT_CONFIG_SNAPSHOT: dict[str, dict[str, object]] = {
    "frontend": {
        "demo_source_mode": "local",
        "timeline_granularity": "hour",
        "ui_density": "compact",
    },
    "backend": {
        "task_executor": "celery"
        if settings.workflow_executor == "celery"
        else "in_memory",
        "demo_snapshot_provider": "local_catalog",
    },
    "workflow": {
        "default_queue": "demo",
        "result_retention": "session",
    },
}


logger = logging.getLogger(__name__)


# 已完成的终态状态：这些状态的 run 可被清理
_TERMINAL_STATUSES = (
    ExecutionStatus.succeeded.value,
    ExecutionStatus.failed.value,
    ExecutionStatus.cancelled.value,
)

# 默认保留期：30 天前的已完成 run 将被清理
_DEFAULT_RETENTION_DAYS = 30

# P2-3：schema 版本跟踪（无 Alembic，用 schema_meta 表记录当前 schema 版本，
# 发版/升级时可检测代码与 DB 版本是否一致）。每次 schema 变更（加列/加表/加索引）
# 时递增此值并记录变更说明。
SCHEMA_VERSION = 3
SCHEMA_CHANGES: list[tuple[int, str]] = [
    (1, "初始 schema：workflow_runs / workflow_events / runtime_config"),
    (
        2,
        "workflow_runs 加 request_json / run_class 列 + idx_workflow_runs_class_status",
    ),
    (3, "新增 schema_meta 版本跟踪表（P2-3）"),
]


class ConcurrentModificationError(Exception):
    """Raised when a CAS (Compare-And-Swap) status update fails due to concurrent modification.

    The run's status was changed by another writer between the read and the write,
    and all retry attempts were exhausted.
    """

    pass


class SQLiteWorkflowRepository:
    def __init__(self, state_dir: str | Path | None = None) -> None:
        self._state_dir = Path(state_dir or settings.workflow_state_dir)
        self._db_path = self._state_dir / "workflow_state.sqlite3"
        self._ensure_layout()
        # Sprint 3.5: 使用连接池替代每次新建连接（WAL + busy_timeout + 连接复用）。
        # row_factory=None 保持原有 tuple-style 行访问（row[0]/row[1]），避免破坏
        # get_run/list_events/get_config_snapshot 等依赖位置索引的代码。
        self._pool = SQLiteConnectionPool(self._db_path, row_factory=None)
        self._initialize_schema()
        self._migrate_schema()

    def _serialize_run_payload(
        self,
        run_status: WorkflowRunStatusResponse,
        *,
        result_dto_override: dict[str, Any] | None = None,
    ) -> str:
        """Serialize run status; optional override keeps provider fields (e.g. products)."""
        payload = run_status.model_dump(mode="json")
        if result_dto_override is not None:
            payload["result_dto"] = result_dto_override
        return json.dumps(payload, ensure_ascii=False)

    # C4 终态守卫（SQL 原子层，消除应用层 read-check-write 的 TOCTOU 窗口）：
    # cancelled 或 watchdog-failed（stuck_running_watchdog）的 run 拒绝任何覆盖写，
    # 与 lifecycle_service._is_protected_terminal 语义一致；INSERT 新行不受影响。
    _TERMINAL_GUARD_WHERE = """
        WHERE NOT (
            workflow_runs.status = 'cancelled'
            OR (
                workflow_runs.status = 'failed'
                AND COALESCE(
                    json_extract(
                        workflow_runs.payload_json,
                        '$.executor_metadata.cleanup_reason'
                    ),
                    ''
                ) = 'stuck_running_watchdog'
            )
        )
    """

    def save_run(
        self,
        run_status: WorkflowRunStatusResponse,
        request_json: str | None = None,
        run_class: str | None = None,
        *,
        result_dto_override: dict[str, Any] | None = None,
    ) -> None:
        payload = self._serialize_run_payload(
            run_status, result_dto_override=result_dto_override
        )
        with self._connect() as connection:
            if request_json is not None:
                connection.execute(
                    """
                    INSERT INTO workflow_runs (run_id, status, updated_at, payload_json, request_json, run_class)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        status = excluded.status,
                        updated_at = excluded.updated_at,
                        payload_json = excluded.payload_json,
                        request_json = COALESCE(excluded.request_json, request_json),
                        run_class = COALESCE(excluded.run_class, run_class)
                    """
                    + self._TERMINAL_GUARD_WHERE,
                    (
                        run_status.run_id,
                        run_status.status.value,
                        run_status.updated_at.isoformat(),
                        payload,
                        request_json,
                        run_class or "business",
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO workflow_runs (run_id, status, updated_at, payload_json, run_class)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        status = excluded.status,
                        updated_at = excluded.updated_at,
                        payload_json = excluded.payload_json,
                        run_class = COALESCE(workflow_runs.run_class, excluded.run_class)
                    """
                    + self._TERMINAL_GUARD_WHERE,
                    (
                        run_status.run_id,
                        run_status.status.value,
                        run_status.updated_at.isoformat(),
                        payload,
                        run_class or "business",
                    ),
                )

    def get_run_request_json(self, run_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_json FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return row[0] if row is not None else None

    def get_run(self, run_id: str) -> WorkflowRunStatusResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return WorkflowRunStatusResponse.model_validate(json.loads(row[0]))

    def get_run_payload(self, run_id: str) -> dict[str, Any] | None:
        """Return raw persisted run payload (preserves result_dto fields pydantic may strip)."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        parsed = json.loads(row[0])
        return parsed if isinstance(parsed, dict) else None

    def list_runs(self) -> list[WorkflowRunStatusResponse]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM workflow_runs ORDER BY updated_at DESC"
            ).fetchall()
        return [
            WorkflowRunStatusResponse.model_validate(json.loads(row[0])) for row in rows
        ]

    def append_event(self, event: WorkflowEvent) -> None:
        payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        with self._connect() as connection:
            # OR IGNORE：event_factory 可能已在执行中即时落库，lifecycle 收尾再写同 event_id 时忽略。
            # 额外吞掉 IntegrityError：旧 worker / 重复进程若仍跑无 OR IGNORE 的 SQL，
            # 或池连接异常路径下约束冲突，不应把已成功的算法 run 标成 failed。
            try:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO workflow_events (event_id, run_id, created_at, payload_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.run_id,
                        event.created_at.isoformat(),
                        payload,
                    ),
                )
            except sqlite3.IntegrityError:
                logger.debug(
                    "Ignoring duplicate workflow_events.event_id=%s run_id=%s",
                    event.event_id,
                    event.run_id,
                )

    def list_events(
        self,
        run_id: str,
        *,
        after_event_id: str | None = None,
        limit: int | None = None,
    ) -> list[WorkflowEvent]:
        query = [
            "SELECT payload_json",
            "FROM workflow_events",
            "WHERE run_id = ?",
        ]
        params: list[object] = [run_id]

        if after_event_id:
            query.extend(
                [
                    "AND (",
                    "  created_at > COALESCE((SELECT created_at FROM workflow_events WHERE event_id = ?), '')",
                    "  OR (",
                    "    created_at = COALESCE((SELECT created_at FROM workflow_events WHERE event_id = ?), '')",
                    "    AND event_id > ?",
                    "  )",
                    ")",
                ]
            )
            params.extend([after_event_id, after_event_id, after_event_id])

        query.append("ORDER BY created_at ASC, event_id ASC")
        if isinstance(limit, int) and limit > 0:
            query.append("LIMIT ?")
            params.append(limit)

        with self._connect() as connection:
            rows = connection.execute("\n".join(query), params).fetchall()
        return [WorkflowEvent.model_validate(json.loads(row[0])) for row in rows]

    def apply_runtime_config(self, items: list[RuntimeConfigPatch]) -> int:
        with self._connect() as connection:
            for item in items:
                connection.execute(
                    """
                    INSERT INTO runtime_config (scope, config_key, value_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(scope, config_key) DO UPDATE SET
                        value_json = excluded.value_json
                    """,
                    (
                        item.scope.value,
                        item.key,
                        json.dumps(item.value, ensure_ascii=False),
                    ),
                )
        return len(items)

    def get_config_snapshot(self) -> dict[str, dict[str, object]]:
        config_snapshot = self._clone_default_config()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT scope, config_key, value_json FROM runtime_config"
            ).fetchall()
        for scope, config_key, value_json in rows:
            scope_snapshot = config_snapshot.setdefault(scope, {})
            scope_snapshot[config_key] = json.loads(value_json)
        return config_snapshot

    def count_active_runs(self, run_class: str | None = None) -> int:
        # Include retry_pending so capacity cannot be bypassed via retries.
        active_statuses = (
            ExecutionStatus.accepted.value,
            ExecutionStatus.queued.value,
            ExecutionStatus.running.value,
            ExecutionStatus.retry_pending.value,
        )
        with self._connect() as connection:
            if run_class is None:
                row = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM workflow_runs
                    WHERE status IN (?, ?, ?, ?)
                    """,
                    active_statuses,
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM workflow_runs
                    WHERE status IN (?, ?, ?, ?)
                      AND COALESCE(run_class, 'business') = ?
                    """,
                    (*active_statuses, run_class),
                ).fetchone()
        return int(row[0]) if row is not None else 0

    def save_run_under_capacity(
        self,
        run_status: WorkflowRunStatusResponse,
        *,
        request_json: str,
        run_class: str,
        limit: int,
        result_dto_override: dict[str, Any] | None = None,
    ) -> None:
        """Atomically reserve a capacity slot and insert the accepted run.

        Uses ``BEGIN IMMEDIATE`` so concurrent submits cannot both pass a
        TOCTOU capacity check. Raises ``ValueError`` when the pool is full.
        """
        payload = self._serialize_run_payload(
            run_status, result_dto_override=result_dto_override
        )
        active_statuses = (
            ExecutionStatus.accepted.value,
            ExecutionStatus.queued.value,
            ExecutionStatus.running.value,
            ExecutionStatus.retry_pending.value,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM workflow_runs
                WHERE status IN (?, ?, ?, ?)
                  AND COALESCE(run_class, 'business') = ?
                """,
                (*active_statuses, run_class or "business"),
            ).fetchone()
            active = int(row[0]) if row is not None else 0
            if active >= limit:
                raise ValueError(
                    f"Workflow capacity reached: active_runs={active}, limit={limit}"
                )
            connection.execute(
                """
                INSERT INTO workflow_runs (run_id, status, updated_at, payload_json, request_json, run_class)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json,
                    request_json = COALESCE(excluded.request_json, request_json),
                    run_class = COALESCE(excluded.run_class, run_class)
                """
                + self._TERMINAL_GUARD_WHERE,
                (
                    run_status.run_id,
                    run_status.status.value,
                    run_status.updated_at.isoformat(),
                    payload,
                    request_json,
                    run_class or "business",
                ),
            )

    def save_run_cas(
        self,
        run_status: WorkflowRunStatusResponse,
        *,
        expected_status: ExecutionStatus | str,
        request_json: str | None = None,
        run_class: str | None = None,
        result_dto_override: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> bool:
        """Compare-And-Swap status update with retry.

        Atomically updates run status only if the current DB status matches
        ``expected_status``. If the status changed, re-reads the current status:
        - Terminal states (succeeded/failed/cancelled) → raise immediately.
        - Non-terminal but different → retry with updated expected_status.

        Closes the TOCTOU window in lifecycle_service._is_protected_terminal.

        Returns:
            True on success.

        Raises:
            ConcurrentModificationError: if all retries exhausted or run is terminal.
        """
        expected = (
            expected_status.value
            if isinstance(expected_status, ExecutionStatus)
            else str(expected_status)
        )
        payload = self._serialize_run_payload(
            run_status, result_dto_override=result_dto_override
        )

        for attempt in range(max_retries):
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE workflow_runs SET
                        status = ?,
                        updated_at = ?,
                        payload_json = ?,
                        request_json = COALESCE(?, request_json),
                        run_class = COALESCE(?, run_class)
                    WHERE run_id = ? AND status = ?
                    """,
                    (
                        run_status.status.value,
                        run_status.updated_at.isoformat(),
                        payload,
                        request_json,
                        run_class or "business",
                        run_status.run_id,
                        expected,
                    ),
                )
                if cursor.rowcount > 0:
                    return True

            # CAS failed — re-read current status to decide next action
            current = self.get_run(run_status.run_id)
            if current is None:
                raise ConcurrentModificationError(
                    f"CAS failed: run {run_status.run_id} not found"
                )
            if current.status in (
                ExecutionStatus.succeeded,
                ExecutionStatus.failed,
                ExecutionStatus.cancelled,
            ):
                raise ConcurrentModificationError(
                    f"CAS failed: run {run_status.run_id} is in terminal state "
                    f"{current.status.value}, expected {expected}"
                )
            # Non-terminal conflict — update expected and retry
            logger.debug(
                "CAS retry %d/%d for run %s: status changed from %s to %s",
                attempt + 1,
                max_retries,
                run_status.run_id,
                expected,
                current.status.value,
            )
            expected = current.status.value

        raise ConcurrentModificationError(
            f"CAS failed after {max_retries} retries: run {run_status.run_id} "
            f"expected {expected_status} but status kept changing"
        )

    def cleanup_old_runs(
        self,
        *,
        retention_days: int = _DEFAULT_RETENTION_DAYS,
        vacuum: bool = False,
    ) -> dict[str, int]:
        """清理超过保留期的已完成 run 及其 events，回收磁盘空间。

        仅清理终态状态（completed/failed/cancelled）且 updated_at 早于
        retention_days 天前的 run。对应的 workflow_events 会一并删除。

        Args:
            retention_days: 保留天数（默认 30）
            vacuum: 是否执行 VACUUM 回收磁盘空间（耗时，建议低峰期执行）

        Returns:
            {"runs_deleted": N, "events_deleted": M, "vacuumed": 0|1}
        """
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        stats = {"runs_deleted": 0, "events_deleted": 0, "vacuumed": 0}

        with self._connect() as connection:
            # 1. 先找出待删除的 run_id（用于级联删除 events）
            cursor = connection.execute(
                """
                SELECT run_id FROM workflow_runs
                WHERE status IN (?, ?, ?)
                  AND updated_at < ?
                """,
                (*_TERMINAL_STATUSES, cutoff),
            )
            run_ids = [row[0] for row in cursor.fetchall()]

            if not run_ids:
                logger.info(
                    "cleanup_old_runs: no runs older than %d days to delete",
                    retention_days,
                )
                return stats

            # 2. 删除 events（批量 IN 查询，分批避免 SQL 参数上限）
            placeholders = ",".join("?" * len(run_ids))
            events_cursor = connection.execute(
                f"DELETE FROM workflow_events WHERE run_id IN ({placeholders})",
                run_ids,
            )
            stats["events_deleted"] = events_cursor.rowcount or 0

            # 3. 删除 runs
            runs_cursor = connection.execute(
                f"DELETE FROM workflow_runs WHERE run_id IN ({placeholders})",
                run_ids,
            )
            stats["runs_deleted"] = runs_cursor.rowcount or 0

            logger.info(
                "cleanup_old_runs: deleted %d runs and %d events (retention=%d days)",
                stats["runs_deleted"],
                stats["events_deleted"],
                retention_days,
            )

        # 4. VACUUM 必须在事务外执行（SQLite 限制）
        if vacuum:
            try:
                # WAL checkpoint + VACUUM 回收磁盘空间
                with self._connect() as connection:
                    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    connection.execute("VACUUM")
                stats["vacuumed"] = 1
                logger.info("cleanup_old_runs: VACUUM completed")
            except Exception:
                logger.exception("cleanup_old_runs: VACUUM failed")

        return stats

    def _ensure_layout(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    request_json TEXT,
                    run_class TEXT NOT NULL DEFAULT 'business'
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_runs_status_updated_at ON workflow_runs(status, updated_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_events_run_created_at ON workflow_events(run_id, created_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_config (
                    scope TEXT NOT NULL,
                    config_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    PRIMARY KEY (scope, config_key)
                )
                """
            )
            for scope, items in self._clone_default_config().items():
                for config_key, value in items.items():
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO runtime_config (scope, config_key, value_json)
                        VALUES (?, ?, ?)
                        """,
                        (scope, config_key, json.dumps(value, ensure_ascii=False)),
                    )
            # P2-3：schema 版本跟踪表（无 Alembic，记录当前 schema 版本 + 变更日志）
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', ?)
                """,
                (str(SCHEMA_VERSION),),
            )
            # 若已存在的版本号低于代码版本，更新到代码版本（additive-only 迁移：
            # 仅向前加列/加表/加索引，不删不改类型——与 _migrate_schema 的 ALTER 策略一致）
            connection.execute(
                """
                UPDATE schema_meta SET value = ?
                WHERE key = 'schema_version' AND CAST(value AS INTEGER) < ?
                """,
                (str(SCHEMA_VERSION), SCHEMA_VERSION),
            )

    def get_schema_version(self) -> int:
        """返回 DB 中记录的 schema 版本（缺失则 0）。"""
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                )
                row = cursor.fetchone()
                return int(row[0]) if row else 0
        except sqlite3.OperationalError:
            return 0

    def _migrate_schema(self) -> None:
        with self._connect() as connection:
            cursor = connection.execute("PRAGMA table_info(workflow_runs)")
            columns = {row[1] for row in cursor.fetchall()}
            if "request_json" not in columns:
                connection.execute(
                    "ALTER TABLE workflow_runs ADD COLUMN request_json TEXT"
                )
            if "run_class" not in columns:
                connection.execute(
                    "ALTER TABLE workflow_runs ADD COLUMN run_class TEXT NOT NULL DEFAULT 'business'"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_runs_class_status ON workflow_runs(run_class, status)"
            )

    def _connect(self):
        """获取连接上下文管理器（从连接池获取，自动 commit/rollback + 归还）。

        原 _connect 手动管理连接生命周期（connect + commit/rollback + close），
        Sprint 3.5 后改为从连接池获取并归还。row_factory=None 保持 tuple-style 行访问。
        """
        return self._pool.connection()

    def close(self) -> None:
        """关闭连接池中所有空闲连接。

        测试场景下必须在删除 db 文件前调用（Windows 不允许删除被占用文件）。
        生产场景下连接池生命周期与进程一致，通常无需显式调用。
        """
        self._pool.close_all()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self._pool.close_all(quiet=True)

    def _clone_default_config(self) -> dict[str, dict[str, object]]:
        import copy

        return copy.deepcopy(DEFAULT_CONFIG_SNAPSHOT)
