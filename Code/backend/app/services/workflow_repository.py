from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from app.core.config import settings
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
        self._initialize_schema()

    def save_run(self, run_status: WorkflowRunStatusResponse) -> None:
        payload = json.dumps(run_status.model_dump(mode="json"), ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_runs (run_id, status, updated_at, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (run_status.run_id, run_status.status.value, run_status.updated_at.isoformat(), payload),
            )

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

    def list_events(self, run_id: str) -> list[WorkflowEvent] | None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM workflow_events
                WHERE run_id = ?
                ORDER BY created_at ASC, event_id ASC
                """,
                (run_id,),
            ).fetchall()
        if not rows:
            return None
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

    def count_active_runs(self) -> int:
        active_statuses = (
            ExecutionStatus.accepted.value,
            ExecutionStatus.queued.value,
            ExecutionStatus.running.value,
        )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM workflow_runs
                WHERE status IN (?, ?, ?)
                """,
                active_statuses,
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
                    payload_json TEXT NOT NULL
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

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _clone_default_config(self) -> dict[str, dict[str, object]]:
        return json.loads(json.dumps(DEFAULT_CONFIG_SNAPSHOT))
