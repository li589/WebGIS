from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.services.download_service import download_service
from app.services.demo_snapshots import get_demo_layer_snapshot
from app.services.workflow_execution import WorkflowExecutionResult
from shared.contracts.api_contracts import ResultKind, WorkflowResultReference, WorkflowSubmitRequest


class DownloadWorkflowService:
    def execute(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        event_factory,
    ) -> WorkflowExecutionResult:
        layer_id = payload.layer_id or payload.map_context.active_layer_id or "wind-field"
        requested_hour = self._resolve_requested_hour(payload)
        snapshot = get_demo_layer_snapshot(layer_id, requested_hour)
        if snapshot is None:
            raise ValueError(f"Unsupported download workflow layer: {layer_id}")
        plan = download_service.prepare_download(
            run_id=run_id,
            layer_id=layer_id,
            requested_hour=requested_hour,
            realtime_preferred=payload.realtime_preferred,
            snapshot=snapshot,
            payload_parameters=payload.parameters,
            requested_at=requested_at,
        )

        manifest = {
            "workflow": {
                "run_id": run_id,
                "command_type": payload.command_type.value,
                "layer_id": layer_id,
            },
            "execution": {
                "download_ticket_id": plan.download_ticket_id,
                "status": plan.execution_status,
                "job_state": plan.job_state,
                "follow_up_policy": plan.follow_up_policy,
                "manifest_result_id": plan.manifest_result_ref.result_id,
                "artifact_resource_key": plan.manifest_result_ref.resource_key,
                "artifact_resource_url": plan.manifest_result_ref.resource_url,
                "artifact_resource_size_bytes": plan.manifest_result_ref.resource_size_bytes,
            },
            "download_plan": {
                "channel": plan.channel,
                "source_mode": plan.source_mode,
                "requested_hour": plan.requested_hour,
                "target_dataset": plan.target_dataset,
                "refresh_policy": plan.refresh_policy,
                "recommended_cache_ttl_seconds": plan.recommended_cache_ttl_seconds,
                "source_refs": plan.source_refs,
            },
            "source_fetch": plan.source_fetch_summary,
            "cache": {
                "cache_key": plan.cache_entry.cache_key,
                "status": plan.cache_entry.status,
                "expires_at": plan.cache_entry.expires_at.isoformat(),
            },
            "preview": {
                "summary": snapshot.summary,
                "status_label": snapshot.status_label,
                "availability_state": snapshot.availability_state.value,
            },
        }

        summary_result_id = f"download-{uuid4().hex[:10]}"
        result_refs = [
            WorkflowResultReference(
                result_id=summary_result_id,
                result_kind=ResultKind.json,
                title=f"{snapshot.display_name} 下载计划",
                mime_type="application/json",
                inline_data=manifest,
                updated_at=requested_at,
            ),
            plan.manifest_result_ref,
        ]
        follow_up_tasks = []
        if plan.job_state["requires_fetch"]:
            follow_up_tasks.append(
                download_service.build_follow_up_task(
                    run_id=run_id,
                    plan=plan,
                    summary_result_id=summary_result_id,
                )
            )

        requested_output_kinds = {
            item.value if isinstance(item, ResultKind) else str(item)
            for item in payload.requested_outputs
        }
        if ResultKind.text.value in requested_output_kinds:
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"download-text-{uuid4().hex[:10]}",
                    result_kind=ResultKind.text,
                    title=f"{snapshot.display_name} 下载摘要",
                    mime_type="text/plain",
                    inline_data={
                        "text": (
                            f"{snapshot.display_name} 下载任务已完成执行清单准备，"
                            f"当前数据状态 {snapshot.data_state_label}，"
                            f"缓存状态 {plan.cache_entry.status}，"
                            f"执行阶段 {plan.job_state['phase']}，"
                            f"source fetch 状态 {plan.source_fetch_summary['status']}。"
                        )
                    },
                    updated_at=requested_at,
                )
            )

        events = [
            event_factory(
                channel="system",
                message="兼容下载服务已生成 Demo/legacy 数据拉取计划。",
                progress=68,
                payload={
                    "service": "download_workflow_service",
                    "compatibility_mode": "legacy-demo",
                    "layer_id": layer_id,
                    "channel": plan.channel,
                    "refresh_policy": plan.refresh_policy,
                    "download_ticket_id": plan.download_ticket_id,
                    "execution_status": plan.execution_status,
                    "job_phase": plan.job_state["phase"],
                    "next_action": plan.job_state["next_action"],
                    "fetch_attempts": plan.job_state["fetch_attempts"],
                    "max_attempts": plan.job_state["max_attempts"],
                    "cache_key": plan.cache_entry.cache_key,
                    "cache_status": plan.cache_entry.status,
                },
            ),
            event_factory(
                channel="data",
                message="下载计划结果已生成。",
                progress=90,
                payload={
                    "result_count": len(result_refs),
                    "source_mode": snapshot.data_state_mode.value,
                    "cache_status": plan.cache_entry.status,
                    "source_fetch_status": plan.source_fetch_summary["status"],
                    "pending_sources": plan.source_fetch_summary["pending_sources"],
                    "manifest_resource_key": plan.manifest_result_ref.resource_key,
                },
            ),
        ]

        diagnostics = [
            "download_workflow_service 属于 legacy/demo 兼容实现，不应视为 workflow-runs 主业务事实源。",
            "legacy_demo_service=true",
            "download_service 已升级为可执行下载骨架，可生成并复用 manifest artifact。",
            "cache_service 已记录下载计划缓存元数据与 artifact 指针。",
            f"resolved_layer_id={layer_id}",
            f"resolved_hour={requested_hour}",
            f"refresh_policy={plan.refresh_policy}",
            f"download_ticket_id={plan.download_ticket_id}",
            f"execution_status={plan.execution_status}",
            f"job_phase={plan.job_state['phase']}",
            f"fetch_attempts={plan.job_state['fetch_attempts']}",
            f"max_attempts={plan.job_state['max_attempts']}",
            f"source_fetch_status={plan.source_fetch_summary['status']}",
            f"cache_key={plan.cache_entry.cache_key}",
            f"cache_status={plan.cache_entry.status}",
            f"manifest_resource_key={plan.manifest_result_ref.resource_key}",
        ]

        algorithm_request = payload.algorithm_request if isinstance(payload.algorithm_request, dict) else payload.algorithm_request.model_dump(mode="json")
        workflow_entry_name = (
            str(algorithm_request.get("workflow_name") or algorithm_request.get("module_name") or "download_workflow")
        )

        return WorkflowExecutionResult(
            message=f"{snapshot.display_name} 下载工作流执行完成，已生成 {len(result_refs)} 个结果引用。",
            result_refs=result_refs,
            result_dto={
                "workflow_entry_name": workflow_entry_name,
                "layer_id": layer_id,
                "requested_hour": requested_hour,
                "compatibility_mode": "legacy-demo",
                "summary": snapshot.summary,
                "status_label": snapshot.status_label,
                "availability_state": snapshot.availability_state.value,
                "data_state_mode": snapshot.data_state_mode.value,
                "download_ticket_id": plan.download_ticket_id,
                "execution_status": plan.execution_status,
                "job_state": plan.job_state,
                "follow_up_policy": plan.follow_up_policy,
                "source_mode": plan.source_mode,
                "refresh_policy": plan.refresh_policy,
                "cache_status": plan.cache_entry.status,
                "cache_key": plan.cache_entry.cache_key,
                "manifest_result_id": plan.manifest_result_ref.result_id,
                "result_category": "download",
                "results": {
                    "json_result_id": summary_result_id,
                    "text_result_id": next((item.result_id for item in result_refs if item.result_kind == ResultKind.text), None),
                    "manifest_result_id": plan.manifest_result_ref.result_id,
                },
            },
            diagnostics=diagnostics,
            events=events,
            follow_up_tasks=follow_up_tasks,
        )

    def _resolve_requested_hour(self, payload: WorkflowSubmitRequest) -> float:
        hour_override = payload.parameters.get("hour")
        if isinstance(hour_override, (int, float)):
            return float(hour_override)
        if payload.time_range is None:
            return 12.0
        return payload.time_range.start_at.hour + payload.time_range.start_at.minute / 60


download_workflow_service = DownloadWorkflowService()
