from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    WorkflowRunStatusResponse,
    WorkflowRunViewResponse,
    WorkflowRunViewSummaryRow,
)


@dataclass(slots=True)
class ResultViewModel:
    category: str
    title: str
    subtitle: str
    status_text: str
    progress_text: str
    summary: str | None
    metric_rows: list[WorkflowRunViewSummaryRow]
    result_url: str | None
    artifact_refs: list
    can_show_link: bool
    updated_at: object | None


class ResultViewService:
    def __init__(self, repository: SQLiteWorkflowRepository | None = None) -> None:
        self._repository = repository or SQLiteWorkflowRepository()

    def get_workflow_run_view(self, run_id: str) -> WorkflowRunViewResponse | None:
        run = self._repository.get_run(run_id)
        if run is None:
            return None
        return self._build_view(run)

    def _build_view(self, run: WorkflowRunStatusResponse) -> WorkflowRunViewResponse:
        dto_record = self._as_record(run.result_dto)
        category = self._resolve_category(dto_record, run)
        title = str(dto_record.get("workflow_entry_name") or run.command_label or run.layer_id or "result")
        subtitle = str(run.layer_id or category)
        status_text = str(dto_record.get("status_label") or run.message or run.status.value)
        progress_text = f"{run.progress}%"
        result_url = self._resolve_result_url(run)
        summary = self._resolve_summary(dto_record, run)
        metric_rows = self._build_metric_rows(dto_record)
        return WorkflowRunViewResponse(
            run_id=run.run_id,
            category=category,
            title=title,
            subtitle=subtitle,
            status_text=status_text,
            progress_text=progress_text,
            summary=summary,
            metric_rows=metric_rows,
            result_url=result_url,
            artifact_refs=run.result_refs,
            can_show_link=bool(result_url),
            updated_at=run.updated_at,
        )

    def _build_metric_rows(self, dto_record: dict[str, Any]) -> list[WorkflowRunViewSummaryRow]:
        rows: list[WorkflowRunViewSummaryRow] = []

        def push(label: str, value: object) -> None:
            if value is None:
                return
            if isinstance(value, (str, int, float)):
                text = str(value)
                if text.strip():
                    rows.append(WorkflowRunViewSummaryRow(label=label, value=text))

        push("Entry", dto_record.get("workflow_entry_name"))
        push("Layer", dto_record.get("layer_id"))
        push("Status", dto_record.get("status_label") or dto_record.get("job_status") or dto_record.get("execution_status"))
        push("Metric", dto_record.get("metric_label"))
        metric_value = dto_record.get("metric_value")
        metric_unit = dto_record.get("metric_unit")
        if metric_value is not None:
            push("Value", f"{metric_value}{metric_unit or ''}")
        quantity = dto_record.get("hotspot_count")
        if quantity is None:
            quantity = dto_record.get("series_point_count")
        push("Count", quantity)
        push("Cache", dto_record.get("cache_status"))
        push("Phase", dto_record.get("job_phase"))
        push("Ticket", dto_record.get("download_ticket_id"))
        return rows[:6]

    def _resolve_category(self, dto_record: dict[str, Any], run: WorkflowRunStatusResponse) -> str:
        category = dto_record.get("result_category")
        if isinstance(category, str) and category.strip():
            return category
        entry_name = dto_record.get("workflow_entry_name")
        if isinstance(entry_name, str) and entry_name.strip():
            return entry_name
        if run.command_label:
            return run.command_label
        return "result"

    def _resolve_result_url(self, run: WorkflowRunStatusResponse) -> str | None:
        preferred = ("json", "file", "text")
        for kind in preferred:
            for item in run.result_refs:
                if item.resource_url and item.result_kind.value == kind:
                    return item.resource_url
        return next((item.resource_url for item in run.result_refs if item.resource_url), None)

    def _resolve_summary(self, dto_record: dict[str, Any], run: WorkflowRunStatusResponse) -> str | None:
        summary = dto_record.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary
        if run.message and run.message.strip():
            return run.message
        return None

    def _as_record(self, dto: object) -> dict[str, Any]:
        if hasattr(dto, "model_dump"):
            return dto.model_dump(mode="json")
        if isinstance(dto, dict):
            return dto
        return {}


result_view_service = ResultViewService()
