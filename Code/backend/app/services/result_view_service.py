from __future__ import annotations

from dataclasses import dataclass

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
        dto = run.result_dto
        dto_record = dto.model_dump(mode="json") if hasattr(dto, "model_dump") else (dto if isinstance(dto, dict) else {})
        category = str(dto_record.get("result_category") or dto_record.get("workflow_entry_name") or "result")
        title = str(dto_record.get("workflow_entry_name") or run.command_label or run.layer_id or "结果概览")
        subtitle = str(run.layer_id or category)
        status_text = str(dto_record.get("status_label") or run.message or run.status.value)
        progress_text = f"{run.progress}%"
        result_url = next((item.resource_url for item in run.result_refs if item.resource_url), None)
        summary = str(dto_record.get("summary") or run.message)
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

    def _build_metric_rows(self, dto_record: dict[str, object]) -> list[WorkflowRunViewSummaryRow]:
        rows: list[WorkflowRunViewSummaryRow] = []

        def push(label: str, value: object) -> None:
            if value is None:
                return
            if isinstance(value, (str, int, float)):
                text = str(value)
                if text:
                    rows.append(WorkflowRunViewSummaryRow(label=label, value=text))

        push("入口", dto_record.get("workflow_entry_name"))
        push("图层", dto_record.get("layer_id"))
        push("状态", dto_record.get("status_label") or dto_record.get("job_status") or dto_record.get("execution_status"))
        push("指标", dto_record.get("metric_label"))
        metric_value = dto_record.get("metric_value")
        metric_unit = dto_record.get("metric_unit")
        if metric_value is not None:
            text = f"{metric_value}{metric_unit or ''}"
            push("数值", text)
        push("数量", dto_record.get("hotspot_count") or dto_record.get("series_point_count"))
        push("缓存", dto_record.get("cache_status"))
        push("阶段", dto_record.get("job_phase"))
        push("下载单", dto_record.get("download_ticket_id"))
        return rows[:6]


result_view_service = ResultViewService()
