"""Workflow persistence service.

Handles repository persistence (save_run_status, append_event) and event/diagnostic
construction. Extracted from interaction_hub.py to separate storage concerns from
orchestration logic.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4

from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    EventChannel,
    LogLevel,
    WorkflowEvent,
    WorkflowRunStatusResponse,
)

logger = logging.getLogger(__name__)


class WorkflowPersistenceService:
    """Persists workflow run status and events to the repository.

    Also provides event construction (make_event) and exception diagnostic
    extraction utilities used by submission and lifecycle services.
    """

    def __init__(self, repository: SQLiteWorkflowRepository | None = None) -> None:
        self._repository = repository or SQLiteWorkflowRepository()

    def save_run_status(
        self,
        *,
        run_status: WorkflowRunStatusResponse,
        request_json: str | None = None,
    ) -> None:
        self._repository.save_run(run_status, request_json=request_json)

    def record_event(
        self,
        event: WorkflowEvent | None = None,
        *,
        run_id: str | None = None,
        channel: EventChannel | str | None = None,
        message: str | None = None,
        progress: int | None = None,
        payload: dict[str, object] | None = None,
        level: LogLevel | str = LogLevel.info,
        created_at: datetime | None = None,
    ) -> None:
        if event is None:
            if run_id is None or channel is None or message is None:
                raise ValueError("run_id, channel and message are required when event is not provided")
            event = self.make_event(
                run_id=run_id,
                channel=channel,
                message=message,
                progress=progress,
                payload=payload,
                level=level,
                created_at=created_at,
            )
        self._repository.append_event(event)

    def make_event(
        self,
        *,
        run_id: str,
        channel: EventChannel | str,
        message: str,
        progress: int | None = None,
        payload: dict[str, object] | None = None,
        level: LogLevel | str = LogLevel.info,
        created_at: datetime | None = None,
    ) -> WorkflowEvent:
        resolved_channel = channel if isinstance(channel, EventChannel) else EventChannel(channel)
        resolved_level = level if isinstance(level, LogLevel) else LogLevel(level)
        return WorkflowEvent(
            event_id=f"evt-{uuid4().hex[:10]}",
            run_id=run_id,
            channel=resolved_channel,
            level=resolved_level,
            message=message,
            created_at=created_at or datetime.now(timezone.utc),
            progress=progress,
            payload=payload or {},
        )

    def extract_exception_diagnostics(self, exc: Exception) -> list[str]:
        """Extract structured diagnostics from BridgeExecutionError."""
        from app.services.bridge_protocol import BridgeExecutionError

        if not isinstance(exc, BridgeExecutionError):
            return []

        details = exc.details if isinstance(exc.details, dict) else {}
        resolution = details.get("resolution_diagnostics")
        if not isinstance(resolution, dict):
            return []

        diagnostics: list[str] = []
        for key in ("layer_id", "module_name", "task_type", "layer_status"):
            value = resolution.get(key)
            if value:
                diagnostics.append(f"validation_{key}={value}")

        explicit_datasets = resolution.get("explicit_data_access_datasets")
        if isinstance(explicit_datasets, list) and explicit_datasets:
            diagnostics.append(f"validation_explicit_data_access_datasets={'|'.join(str(item) for item in explicit_datasets)}")

        unresolved_datasets = resolution.get("unresolved_default_datasets")
        if isinstance(unresolved_datasets, list):
            for item in unresolved_datasets:
                if not isinstance(item, dict):
                    continue
                dataset_name = item.get("dataset_name")
                if not dataset_name:
                    continue
                diagnostics.append(f"validation_dataset_missing={dataset_name}")
                candidate_sources = item.get("candidate_sources")
                if isinstance(candidate_sources, list) and candidate_sources:
                    diagnostics.append(
                        f"validation_dataset_candidates.{dataset_name}={'|'.join(str(source) for source in candidate_sources)}"
                    )

        return diagnostics

    def augment_result_dto(
        self,
        result_dto: dict[str, object] | None,
        **extra_fields: object,
    ) -> dict[str, object] | None:
        if not result_dto:
            return result_dto
        return {**result_dto, **extra_fields}

    def get_effective_config_int(self, scope: str, key: str, default: int) -> int:
        """Get an int config value from DB runtime config, falling back to default."""
        try:
            snapshot = self._repository.get_config_snapshot()
            value = snapshot.get(scope, {}).get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        except Exception:
            pass
        return default
