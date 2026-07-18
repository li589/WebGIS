from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from app.core.config import settings
from app.services._sqlite_pool import SQLiteConnectionPool
from shared.contracts.api_contracts import (
    ExecutionStatus,
    RuntimeConfigPatch,
    WorkflowEvent,
    WorkflowRunStatusResponse,
)

DEFAULT_CONFIG_SNAPSHOT: dict[str, dict[str, object]] = {
    "frontend": {
        "demo_source_mode": "local",
        "timeline_granularity": "hour",
        "ui_density": "compact",
    },
    "backend": {
        "task_executor": "celery" if settings.workflow_executor == "celery" else "in_memory",
        "demo_snapshot_provider": "local_catalog",
    },
    "workflow": {
        "default_queue": "demo",
        "result_retention": "session",
    },
}


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

    def save_run(
        self,
        run_status: WorkflowRunStatusResponse,
        request_json: str | None = None,
        run_class: str | None = None,
    ) -> None:
        payload = json.dumps(run_status.model_dump(mode="json"), ensure_ascii=False)
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
                    """,
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
                    """,
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

    def list_runs(self) -> list[WorkflowRunStatusResponse]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM workflow_runs ORDER BY updated_at DESC"
            ).fetchall()
        return [WorkflowRunStatusResponse.model_validate(json.loads(row[0])) for row in rows]

    def append_event(self, event: WorkflowEvent) -> None:
        payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_events (event_id, run_id, created_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (event.event_id, event.run_id, event.created_at.isoformat(), payload),
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
                    (item.scope.value, item.key, json.dumps(item.value, ensure_ascii=False)),
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
        active_statuses = (
            ExecutionStatus.accepted.value,
            ExecutionStatus.queued.value,
            ExecutionStatus.running.value,
        )
        with self._connect() as connection:
            if run_class is None:
                row = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM workflow_runs
                    WHERE status IN (?, ?, ?)
                    """,
                    active_statuses,
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM workflow_runs
                    WHERE status IN (?, ?, ?)
                      AND COALESCE(run_class, 'business') = ?
                    """,
                    (*active_statuses, run_class),
                ).fetchone()
        return int(row[0]) if row is not None else 0

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

    def _migrate_schema(self) -> None:
        with self._connect() as connection:
            cursor = connection.execute("PRAGMA table_info(workflow_runs)")
            columns = {row[1] for row in cursor.fetchall()}
            if "request_json" not in columns:
                connection.execute("ALTER TABLE workflow_runs ADD COLUMN request_json TEXT")
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

    def _clone_default_config(self) -> dict[str, dict[str, object]]:
        import copy
        return copy.deepcopy(DEFAULT_CONFIG_SNAPSHOT)
