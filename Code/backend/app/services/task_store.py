from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.core.config import settings
from app.core.logging import log_context
from app.services.workflow.service_container import submission_service
from shared.contracts.api_contracts import (
    ClientIdentity,
    ExecutionStatus,
    MapMode,
    ResultKind,
    RuntimeMapContext,
    TaskAcceptedResponse,
    TaskResultReference,
    TaskStatus,
    TaskStatusResponse,
    TaskSubmitRequest,
    TaskType,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowResourceProfile,
    WorkflowResultReference,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
)

logger = logging.getLogger(__name__)


class SQLiteTaskStore:
    def __init__(self, state_dir: str | Path | None = None) -> None:
        self._state_dir = Path(state_dir or settings.workflow_state_dir)
        self._db_path = self._state_dir / "workflow_state.sqlite3"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def create_task(self, payload: TaskSubmitRequest) -> TaskAcceptedResponse:
        now = datetime.now(timezone.utc)
        task_id = f"task-{uuid4().hex[:12]}"
        status_url = f"/tasks/{task_id}"
        workflow_payload = self._to_workflow_request(payload)
        payload_json = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)

        with log_context(task_id=task_id):
            accepted = submission_service.submit_workflow(workflow_payload)
            with log_context(run_id=accepted.run_id):
                logger.info("Legacy task endpoint bridged to workflow-runs")
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO tasks (task_id, run_id, layer_id, task_type, created_at, updated_at, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        run_id = excluded.run_id,
                        layer_id = excluded.layer_id,
                        task_type = excluded.task_type,
                        updated_at = excluded.updated_at,
                        payload_json = excluded.payload_json
                    """,
                    (
                        task_id,
                        accepted.run_id,
                        payload.layer_id,
                        payload.task_type.value,
                        now.isoformat(),
                        now.isoformat(),
                        payload_json,
                    ),
                )

            return TaskAcceptedResponse(
                task_id=task_id,
                status=TaskStatus.queued,
                status_url=status_url,
                created_at=now,
                message="任务已提交；该 legacy tasks 兼容入口已软下线，内部自动桥接到 workflow-runs 主链。",
            )

    def get_task(self, task_id: str) -> TaskStatusResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT run_id, layer_id, task_type, created_at
                FROM tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        run_id, layer_id, task_type, created_at = row
        workflow_run = submission_service.get_workflow_run(run_id)
        if workflow_run is None:
            return None
        return self._to_task_status(
            task_id=task_id,
            layer_id=layer_id or workflow_run.layer_id or "",
            task_type=TaskType(task_type),
            created_at=datetime.fromisoformat(created_at) if created_at else workflow_run.created_at,
            workflow_run=workflow_run,
        )

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    layer_id TEXT,
                    task_type TEXT,
                    created_at TEXT,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT
                )
                """
            )
            self._ensure_column(connection, "tasks", "run_id", "TEXT")
            self._ensure_column(connection, "tasks", "layer_id", "TEXT")
            self._ensure_column(connection, "tasks", "task_type", "TEXT")
            self._ensure_column(connection, "tasks", "created_at", "TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_run_id ON tasks(run_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_task_type_updated_at ON tasks(task_type, updated_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _ensure_column(self, connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
        existing_columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in existing_columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def _to_workflow_request(self, payload: TaskSubmitRequest) -> WorkflowSubmitRequest:
        command_type = {
            TaskType.analysis: WorkflowCommandType.analysis,
            TaskType.layer_preview: WorkflowCommandType.layer_preview,
            TaskType.export: WorkflowCommandType.export,
        }[payload.task_type]
        client_context = payload.client_context
        return WorkflowSubmitRequest(
            command_type=command_type,
            command_label=f"legacy-task:{payload.task_type.value}",
            layer_id=payload.layer_id,
            priority=self._resolve_priority(payload.task_type),
            resource_profile=self._resolve_resource_profile(payload.task_type),
            realtime_preferred=payload.task_type == TaskType.layer_preview,
            spatial_filter=payload.spatial_filter,
            time_range=payload.time_range,
            parameters=payload.parameters,
            requested_outputs=[self._to_result_kind(value) for value in payload.requested_outputs],
            client=ClientIdentity(
                client_id=client_context.get("client_id"),
                session_id=client_context.get("session_id"),
                page=client_context.get("page"),
                view_id=client_context.get("view_id"),
                user_agent=client_context.get("user_agent"),
            ),
            map_context=RuntimeMapContext(
                active_layer_id=payload.layer_id,
                map_mode=payload.map_mode if isinstance(payload.map_mode, MapMode) else MapMode.mode_2d,
            ),
            correlation_id=client_context.get("correlation_id"),
        )

    def _to_result_kind(self, output_name: str) -> ResultKind | str:
        try:
            return ResultKind(output_name)
        except ValueError:
            return output_name

    def _resolve_priority(self, task_type: TaskType) -> WorkflowPriority:
        return {
            TaskType.layer_preview: WorkflowPriority.high,
            TaskType.analysis: WorkflowPriority.normal,
            TaskType.export: WorkflowPriority.low,
        }[task_type]

    def _resolve_resource_profile(self, task_type: TaskType) -> WorkflowResourceProfile:
        return {
            TaskType.layer_preview: WorkflowResourceProfile.light,
            TaskType.analysis: WorkflowResourceProfile.standard,
            TaskType.export: WorkflowResourceProfile.batch,
        }[task_type]

    def _to_task_status(
        self,
        *,
        task_id: str,
        layer_id: str,
        task_type: TaskType,
        created_at: datetime,
        workflow_run: WorkflowRunStatusResponse,
    ) -> TaskStatusResponse:
        return TaskStatusResponse(
            task_id=task_id,
            layer_id=layer_id,
            task_type=task_type,
            status=self._map_execution_status(workflow_run.status),
            progress=workflow_run.progress,
            message=workflow_run.message,
            created_at=created_at,
            updated_at=workflow_run.updated_at,
            spatial_filter=workflow_run.spatial_filter,
            time_range=workflow_run.time_range,
            requested_outputs=[
                item.value if hasattr(item, "value") else str(item) for item in workflow_run.requested_outputs
            ],
            result_refs=[self._map_result_ref(item) for item in workflow_run.result_refs],
            diagnostics=[
                f"bridged_run_id={workflow_run.run_id}",
                "legacy_tasks_endpoint=true",
                "compat_status=soft-offline",
                *workflow_run.diagnostics,
            ],
        )

    def _map_execution_status(self, status: ExecutionStatus) -> TaskStatus:
        if status in {ExecutionStatus.accepted, ExecutionStatus.queued}:
            return TaskStatus.queued
        if status == ExecutionStatus.running:
            return TaskStatus.running
        if status == ExecutionStatus.succeeded:
            return TaskStatus.succeeded
        if status == ExecutionStatus.cancelled:
            return TaskStatus.cancelled
        return TaskStatus.failed

    def _map_result_ref(self, result_ref: WorkflowResultReference) -> TaskResultReference:
        return TaskResultReference(
            result_type=result_ref.result_kind.value,
            mime_type=result_ref.mime_type,
            inline_data=result_ref.inline_data,
            resource_url=result_ref.resource_url,
        )

task_store = SQLiteTaskStore()
