from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services.cache_service import CacheEntry, cache_service
from app.services.result_storage import result_storage_service
from shared.contracts.api_contracts import ResultKind, WorkflowResultReference


@dataclass
class DownloadPlan:
    channel: str
    dataset_key: str
    requested_hour: float
    refresh_policy: str
    recommended_cache_ttl_seconds: int
    source_mode: str
    target_dataset: str
    source_refs: list[dict[str, Any]]
    cache_entry: CacheEntry
    download_ticket_id: str
    execution_status: str
    job_state: dict[str, Any]
    source_fetch_summary: dict[str, Any]
    manifest_result_ref: WorkflowResultReference


class DownloadService:
    def prepare_download(
        self,
        *,
        run_id: str,
        layer_id: str,
        requested_hour: float,
        realtime_preferred: bool,
        snapshot,
        payload_parameters: dict[str, Any],
        requested_at: datetime,
    ) -> DownloadPlan:
        refresh_policy = "realtime" if realtime_preferred else "scheduled"
        ttl_seconds = self._resolve_ttl_seconds(realtime_preferred, payload_parameters)
        cache_key = cache_service.build_cache_key(
            scope="download-plan",
            parts={
                "layer_id": layer_id,
                "requested_hour": requested_hour,
                "refresh_policy": refresh_policy,
                "source_mode": snapshot.data_state_mode.value,
            },
        )
        current_entry = cache_service.get_entry(cache_key)
        cached_manifest_ref = self._build_cached_manifest_result_ref(
            cache_entry=current_entry,
            requested_at=requested_at,
        )
        cache_status = "warm" if current_entry and current_entry.is_fresh and cached_manifest_ref else "cold"
        source_refs = self._resolve_source_refs(layer_id, requested_hour, refresh_policy, cache_status)
        download_ticket_id = self._resolve_download_ticket_id(current_entry, cache_status)
        execution_status = "cache_hit" if cache_status == "warm" else "prepared"
        job_state = self._build_job_state(
            download_ticket_id=download_ticket_id,
            cache_status=cache_status,
            realtime_preferred=realtime_preferred,
            refresh_policy=refresh_policy,
        )
        source_fetch_summary = self._build_source_fetch_summary(
            source_refs=source_refs,
            cache_status=cache_status,
        )
        manifest_result_ref = cached_manifest_ref or self._build_manifest_result_ref(
            run_id=run_id,
            layer_id=layer_id,
            requested_hour=requested_hour,
            refresh_policy=refresh_policy,
            snapshot=snapshot,
            source_refs=source_refs,
            requested_at=requested_at,
            download_ticket_id=download_ticket_id,
            payload_parameters=payload_parameters,
            job_state=job_state,
            source_fetch_summary=source_fetch_summary,
        )
        cache_entry = cache_service.upsert_entry(
            cache_key=cache_key,
            scope="download-plan",
            ttl_seconds=ttl_seconds,
            status=cache_status,
            metadata={
                "layer_id": layer_id,
                "requested_hour": requested_hour,
                "refresh_policy": refresh_policy,
                "source_mode": snapshot.data_state_mode.value,
                "source_ref_count": len(source_refs),
                "download_ticket_id": download_ticket_id,
                "execution_status": execution_status,
                "job_phase": job_state["phase"],
                "job_progress": job_state["progress"],
                "source_fetch_status": source_fetch_summary["status"],
                "manifest_result_id": manifest_result_ref.result_id,
                "manifest_result_kind": manifest_result_ref.result_kind.value,
                "artifact_title": manifest_result_ref.title,
                "artifact_mime_type": manifest_result_ref.mime_type,
                "artifact_resource_url": manifest_result_ref.resource_url,
                "artifact_resource_backend": manifest_result_ref.resource_backend,
                "artifact_resource_key": manifest_result_ref.resource_key,
                "artifact_resource_size_bytes": manifest_result_ref.resource_size_bytes,
            },
        )
        return DownloadPlan(
            channel="download",
            dataset_key=layer_id,
            requested_hour=requested_hour,
            refresh_policy=refresh_policy,
            recommended_cache_ttl_seconds=ttl_seconds,
            source_mode=snapshot.data_state_mode.value,
            target_dataset=snapshot.display_name,
            source_refs=source_refs,
            cache_entry=cache_entry,
            download_ticket_id=download_ticket_id,
            execution_status=execution_status,
            job_state=job_state,
            source_fetch_summary=source_fetch_summary,
            manifest_result_ref=manifest_result_ref,
        )

    def _resolve_ttl_seconds(self, realtime_preferred: bool, payload_parameters: dict[str, Any]) -> int:
        if isinstance(payload_parameters.get("cache_ttl_seconds"), int):
            return max(1, int(payload_parameters["cache_ttl_seconds"]))
        if realtime_preferred:
            return min(settings.cache_default_ttl_seconds, 300)
        return settings.cache_default_ttl_seconds

    def build_follow_up_task(
        self,
        *,
        run_id: str,
        plan: DownloadPlan,
        summary_result_id: str,
    ) -> dict[str, Any]:
        return {
            "task_type": "download_fetch_placeholder",
            "run_id": run_id,
            "download_ticket_id": plan.download_ticket_id,
            "cache_key": plan.cache_entry.cache_key,
            "summary_result_id": summary_result_id,
            "manifest_result_id": plan.manifest_result_ref.result_id,
            "artifact_resource_key": plan.manifest_result_ref.resource_key,
        }

    def complete_follow_up_task(
        self,
        *,
        run_id: str,
        result_refs: list[WorkflowResultReference],
        cache_key: str,
        summary_result_id: str,
        manifest_result_id: str,
        updated_at: datetime,
    ) -> tuple[list[WorkflowResultReference], list[str]]:
        summary_ref = next((item for item in result_refs if item.result_id == summary_result_id), None)
        manifest_ref = next((item for item in result_refs if item.result_id == manifest_result_id), None)
        if summary_ref is None or summary_ref.inline_data is None:
            raise ValueError("Download summary result is missing for follow-up task.")
        if manifest_ref is None:
            raise ValueError("Download manifest result is missing for follow-up task.")

        summary_payload = self._clone_payload(summary_ref.inline_data)
        source_refs = [
            {
                **item,
                "fetch_status": "ready" if item.get("fetch_status") == "pending" else item.get("fetch_status", "ready"),
                "fetch_stage": "fetched_to_artifact"
                if item.get("fetch_status") == "pending"
                else item.get("fetch_stage", "source_manifest_ready"),
            }
            for item in summary_payload.get("download_plan", {}).get("source_refs", [])
        ]
        summary_payload["download_plan"]["source_refs"] = source_refs
        total_bytes = sum(int(item.get("estimated_bytes", 0)) for item in source_refs)
        summary_payload["source_fetch"] = {
            "status": "fetched",
            "total_sources": len(source_refs),
            "pending_sources": 0,
            "estimated_total_bytes": total_bytes,
            "ready_sources": len(source_refs),
        }
        job_state = {
            **summary_payload.get("execution", {}).get("job_state", {}),
            "phase": "fulfilled",
            "status": "fetched",
            "progress": 100,
            "requires_fetch": False,
            "artifact_status": "updated",
            "next_action": "publish_cached_manifest",
            "completed_at": updated_at.astimezone(timezone.utc).isoformat(),
        }
        summary_payload["execution"]["status"] = "fetched"
        summary_payload["execution"]["job_state"] = job_state

        updated_manifest_ref = result_storage_service.replace_artifact_result_ref(
            run_id=run_id,
            existing_ref=manifest_ref,
            updated_at=updated_at,
            payload=self._build_manifest_payload_from_summary(run_id=run_id, summary_payload=summary_payload),
        )
        current_cache = cache_service.get_entry(cache_key)
        ttl_seconds = self._resolve_follow_up_ttl_seconds(current_cache=current_cache, now=updated_at)
        cache_metadata = {
            **(current_cache.metadata if current_cache is not None else {}),
            "download_ticket_id": summary_payload["execution"]["download_ticket_id"],
            "execution_status": "fetched",
            "job_phase": job_state["phase"],
            "job_progress": job_state["progress"],
            "source_fetch_status": summary_payload["source_fetch"]["status"],
            "manifest_result_id": updated_manifest_ref.result_id,
            "manifest_result_kind": updated_manifest_ref.result_kind.value,
            "artifact_title": updated_manifest_ref.title,
            "artifact_mime_type": updated_manifest_ref.mime_type,
            "artifact_resource_url": updated_manifest_ref.resource_url,
            "artifact_resource_backend": updated_manifest_ref.resource_backend,
            "artifact_resource_key": updated_manifest_ref.resource_key,
            "artifact_resource_size_bytes": updated_manifest_ref.resource_size_bytes,
        }
        cache_entry = cache_service.upsert_entry(
            cache_key=cache_key,
            scope=current_cache.scope if current_cache is not None else "download-plan",
            ttl_seconds=ttl_seconds,
            status="warm",
            metadata=cache_metadata,
        )
        summary_payload["cache"]["status"] = cache_entry.status
        summary_payload["cache"]["expires_at"] = cache_entry.expires_at.isoformat()
        summary_payload["execution"]["artifact_resource_key"] = updated_manifest_ref.resource_key
        summary_payload["execution"]["artifact_resource_url"] = updated_manifest_ref.resource_url
        summary_payload["execution"]["artifact_resource_size_bytes"] = updated_manifest_ref.resource_size_bytes

        updated_result_refs: list[WorkflowResultReference] = []
        for item in result_refs:
            if item.result_id == summary_result_id:
                updated_result_refs.append(
                    WorkflowResultReference(
                        result_id=item.result_id,
                        result_kind=item.result_kind,
                        title=item.title,
                        mime_type=item.mime_type,
                        inline_data=summary_payload,
                        updated_at=updated_at,
                    )
                )
            elif item.result_id == manifest_result_id:
                updated_result_refs.append(updated_manifest_ref)
            elif item.result_kind == ResultKind.text and item.inline_data:
                updated_result_refs.append(
                    WorkflowResultReference(
                        result_id=item.result_id,
                        result_kind=item.result_kind,
                        title=item.title,
                        mime_type=item.mime_type,
                        inline_data={
                            "text": (
                                f"{summary_payload['download_plan']['target_dataset']} 下载占位任务已完成源抓取回写，"
                                f"当前缓存状态 {cache_entry.status}，"
                                f"执行阶段 {job_state['phase']}。"
                            )
                        },
                        updated_at=updated_at,
                    )
                )
            else:
                updated_result_refs.append(item)

        return updated_result_refs, [
            f"download_follow_up_ticket={summary_payload['execution']['download_ticket_id']}",
            "download_follow_up_status=fetched",
            f"download_follow_up_cache={cache_entry.status}",
            f"download_follow_up_artifact={updated_manifest_ref.resource_key}",
        ]

    def _resolve_source_refs(
        self,
        layer_id: str,
        requested_hour: float,
        refresh_policy: str,
        cache_status: str,
    ) -> list[dict[str, Any]]:
        base_ref = {
            "kind": "demo_snapshot",
            "layer_id": layer_id,
            "requested_hour": requested_hour,
            "refresh_policy": refresh_policy,
        }
        return [
            {
                **base_ref,
                "ref_id": f"{layer_id}-snapshot",
                "priority": "high" if refresh_policy == "realtime" else "normal",
                "fetch_status": "cached" if cache_status == "warm" else "pending",
                "fetch_stage": "source_manifest_ready" if cache_status == "warm" else "awaiting_dispatch",
                "source_kind": "snapshot",
                "source_uri": f"demo://snapshots/{layer_id}?hour={requested_hour}",
                "estimated_bytes": 65536,
            },
            {
                **base_ref,
                "ref_id": f"{layer_id}-catalog-metadata",
                "priority": "normal",
                "fetch_status": "cached",
                "fetch_stage": "metadata_attached",
                "source_kind": "catalog_metadata",
                "source_uri": f"demo://catalog/{layer_id}",
                "estimated_bytes": 4096,
            },
        ]

    def _build_cached_manifest_result_ref(
        self,
        *,
        cache_entry: CacheEntry | None,
        requested_at: datetime,
    ) -> WorkflowResultReference | None:
        if cache_entry is None or not cache_entry.is_fresh:
            return None
        metadata = cache_entry.metadata
        resource_key = metadata.get("artifact_resource_key")
        resource_url = metadata.get("artifact_resource_url")
        if not resource_key or not resource_url:
            return None
        result_kind = metadata.get("manifest_result_kind", ResultKind.file.value)
        return WorkflowResultReference(
            result_id=str(metadata.get("manifest_result_id", f"download-manifest-{uuid4().hex[:10]}")),
            result_kind=ResultKind(result_kind),
            title=str(metadata.get("artifact_title", "下载执行清单")),
            mime_type=str(metadata.get("artifact_mime_type", "application/json")),
            inline_data=None,
            resource_url=str(resource_url),
            resource_backend=str(metadata.get("artifact_resource_backend", settings.object_store_backend)),
            resource_key=str(resource_key),
            resource_size_bytes=self._coerce_int(metadata.get("artifact_resource_size_bytes")),
            updated_at=requested_at,
        )

    def _build_manifest_result_ref(
        self,
        *,
        run_id: str,
        layer_id: str,
        requested_hour: float,
        refresh_policy: str,
        snapshot,
        source_refs: list[dict[str, Any]],
        requested_at: datetime,
        download_ticket_id: str,
        payload_parameters: dict[str, Any],
        job_state: dict[str, Any],
        source_fetch_summary: dict[str, Any],
    ) -> WorkflowResultReference:
        manifest_payload = {
            "manifest_version": 1,
            "generated_at": requested_at.astimezone(timezone.utc).isoformat(),
            "workflow": {
                "run_id": run_id,
                "download_ticket_id": download_ticket_id,
                "channel": "download",
            },
            "dataset": {
                "layer_id": layer_id,
                "display_name": snapshot.display_name,
                "requested_hour": requested_hour,
                "source_mode": snapshot.data_state_mode.value,
                "availability_state": snapshot.availability_state.value,
            },
            "execution": {
                "status": job_state["status"],
                "refresh_policy": refresh_policy,
                "executor": "download_service",
                "job_state": job_state,
            },
            "source_fetch": source_fetch_summary,
            "source_refs": source_refs,
            "parameters": payload_parameters,
            "preview": {
                "summary": snapshot.summary,
                "status_label": snapshot.status_label,
                "data_state_label": snapshot.data_state_label,
            },
        }
        return result_storage_service.create_artifact_result_ref(
            run_id=run_id,
            result_id=f"download-file-{uuid4().hex[:10]}",
            result_kind=ResultKind.file,
            title=f"{snapshot.display_name} 下载执行清单",
            mime_type="application/json",
            updated_at=requested_at,
            payload=manifest_payload,
        )

    def _resolve_download_ticket_id(self, cache_entry: CacheEntry | None, cache_status: str) -> str:
        if cache_status == "warm" and cache_entry is not None:
            ticket_id = cache_entry.metadata.get("download_ticket_id")
            if isinstance(ticket_id, str) and ticket_id:
                return ticket_id
        return f"download-{uuid4().hex[:12]}"

    def _build_manifest_payload_from_summary(
        self,
        *,
        run_id: str,
        summary_payload: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_payload = summary_payload.get("workflow", {})
        execution_payload = summary_payload.get("execution", {})
        return {
            "manifest_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "workflow": {
                "run_id": run_id,
                "download_ticket_id": execution_payload.get("download_ticket_id"),
                "channel": summary_payload.get("download_plan", {}).get("channel", "download"),
                "command_type": workflow_payload.get("command_type"),
                "layer_id": workflow_payload.get("layer_id"),
            },
            "dataset": {
                "layer_id": workflow_payload.get("layer_id"),
                "display_name": summary_payload.get("download_plan", {}).get("target_dataset"),
                "requested_hour": summary_payload.get("download_plan", {}).get("requested_hour"),
                "source_mode": summary_payload.get("download_plan", {}).get("source_mode"),
                "availability_state": summary_payload.get("preview", {}).get("availability_state"),
            },
            "execution": {
                "status": execution_payload.get("status"),
                "refresh_policy": summary_payload.get("download_plan", {}).get("refresh_policy"),
                "executor": "download_follow_up_task",
                "job_state": execution_payload.get("job_state", {}),
            },
            "source_fetch": summary_payload.get("source_fetch", {}),
            "source_refs": summary_payload.get("download_plan", {}).get("source_refs", []),
            "cache": summary_payload.get("cache", {}),
            "preview": summary_payload.get("preview", {}),
        }

    def _resolve_follow_up_ttl_seconds(self, *, current_cache: CacheEntry | None, now: datetime) -> int:
        if current_cache is None:
            return settings.cache_default_ttl_seconds
        remaining_seconds = int((current_cache.expires_at - now).total_seconds())
        return max(1, remaining_seconds)

    def _clone_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(payload, ensure_ascii=False))

    def _build_job_state(
        self,
        *,
        download_ticket_id: str,
        cache_status: str,
        realtime_preferred: bool,
        refresh_policy: str,
    ) -> dict[str, Any]:
        if cache_status == "warm":
            return {
                "ticket_id": download_ticket_id,
                "phase": "fulfilled",
                "status": "cache_hit",
                "progress": 100,
                "cache_hit": True,
                "refresh_policy": refresh_policy,
                "realtime_preferred": realtime_preferred,
                "requires_fetch": False,
                "artifact_status": "reused",
                "next_action": "hydrate_result_from_artifact",
            }
        return {
            "ticket_id": download_ticket_id,
            "phase": "prepared",
            "status": "awaiting_fetch",
            "progress": 45,
            "cache_hit": False,
            "refresh_policy": refresh_policy,
            "realtime_preferred": realtime_preferred,
            "requires_fetch": True,
            "artifact_status": "created",
            "next_action": "dispatch_source_fetch",
        }

    def _build_source_fetch_summary(
        self,
        *,
        source_refs: list[dict[str, Any]],
        cache_status: str,
    ) -> dict[str, Any]:
        total_bytes = sum(int(item.get("estimated_bytes", 0)) for item in source_refs)
        pending_count = sum(1 for item in source_refs if item.get("fetch_status") not in {"cached", "ready"})
        if cache_status == "warm":
            return {
                "status": "cache_reused",
                "total_sources": len(source_refs),
                "pending_sources": 0,
                "estimated_total_bytes": total_bytes,
                "ready_sources": len(source_refs),
            }
        return {
            "status": "awaiting_fetch",
            "total_sources": len(source_refs),
            "pending_sources": pending_count,
            "estimated_total_bytes": total_bytes,
            "ready_sources": len(source_refs) - pending_count,
        }

    def _coerce_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


download_service = DownloadService()
