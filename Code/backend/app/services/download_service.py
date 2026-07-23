from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services.cache_service import CacheEntry, cache_service
from app.services.result_storage import result_storage_service
from app.services.source_fetcher import source_fetcher_registry
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
    follow_up_policy: dict[str, Any]
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
        cache_status = (
            "warm"
            if current_entry and current_entry.is_fresh and cached_manifest_ref
            else "cold"
        )
        source_refs = self._resolve_source_refs(
            layer_id, requested_hour, refresh_policy, cache_status
        )
        download_ticket_id = self._resolve_download_ticket_id(
            current_entry, cache_status
        )
        follow_up_policy = self._build_follow_up_policy(
            payload_parameters=payload_parameters
        )
        execution_status = "cache_hit" if cache_status == "warm" else "prepared"
        job_state = self._build_job_state(
            download_ticket_id=download_ticket_id,
            cache_status=cache_status,
            realtime_preferred=realtime_preferred,
            refresh_policy=refresh_policy,
            follow_up_policy=follow_up_policy,
            requested_at=requested_at,
        )
        source_fetch_summary = self._build_source_fetch_summary(
            source_refs=source_refs,
            cache_status=cache_status,
            follow_up_policy=follow_up_policy,
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
            follow_up_policy=follow_up_policy,
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
                "fetch_attempts": job_state["fetch_attempts"],
                "max_attempts": job_state["max_attempts"],
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
            follow_up_policy=follow_up_policy,
            manifest_result_ref=manifest_result_ref,
        )

    def _resolve_ttl_seconds(
        self, realtime_preferred: bool, payload_parameters: dict[str, Any]
    ) -> int:
        ttl_value = self._coerce_int(payload_parameters.get("cache_ttl_seconds"))
        if ttl_value is not None:
            return max(1, ttl_value)
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
            "task_type": "download_fetch",
            "run_id": run_id,
            "download_ticket_id": plan.download_ticket_id,
            "cache_key": plan.cache_entry.cache_key,
            "summary_result_id": summary_result_id,
            "manifest_result_id": plan.manifest_result_ref.result_id,
            "artifact_resource_key": plan.manifest_result_ref.resource_key,
            "source_refs": plan.source_refs,
            "max_attempts": plan.follow_up_policy["max_attempts"],
            "simulate_fail_attempts": plan.follow_up_policy["simulate_fail_attempts"],
            "partial_failure_ref_ids": plan.follow_up_policy["partial_failure_ref_ids"],
        }

    def complete_follow_up_task(
        self,
        *,
        run_id: str,
        result_refs: list[WorkflowResultReference],
        task_data: dict[str, Any],
        cache_key: str,
        summary_result_id: str,
        manifest_result_id: str,
        updated_at: datetime,
    ) -> tuple[list[WorkflowResultReference], list[str], dict[str, Any]]:
        summary_ref = next(
            (item for item in result_refs if item.result_id == summary_result_id), None
        )
        manifest_ref = next(
            (item for item in result_refs if item.result_id == manifest_result_id), None
        )
        if summary_ref is None or summary_ref.inline_data is None:
            raise ValueError("Download summary result is missing for follow-up task.")
        if manifest_ref is None:
            raise ValueError("Download manifest result is missing for follow-up task.")
        if manifest_ref.resource_key is None:
            raise ValueError(
                "Download manifest artifact is missing resource_key for follow-up task."
            )

        summary_payload = self._clone_payload(summary_ref.inline_data)
        execution_payload = summary_payload.setdefault("execution", {})
        existing_job_state = execution_payload.setdefault("job_state", {})
        follow_up_policy = execution_payload.setdefault(
            "follow_up_policy",
            {
                "max_attempts": max(
                    1, self._coerce_int(task_data.get("max_attempts")) or 3
                ),
                "retryable": True,
                "simulate_fail_attempts": max(
                    0, self._coerce_int(task_data.get("simulate_fail_attempts")) or 0
                ),
                "partial_failure_ref_ids": self._coerce_str_list(
                    task_data.get("partial_failure_ref_ids")
                ),
            },
        )
        source_refs = self._clone_payload(
            summary_payload.get("download_plan", {}).get("source_refs", [])
        )
        # 优先使用 task_data 中的 source_refs（由 build_follow_up_task 传入，更可靠）
        task_source_refs = task_data.get("source_refs")
        if isinstance(task_source_refs, list) and task_source_refs:
            source_refs = self._clone_payload(task_source_refs)
        attempt_number = (
            max(0, self._coerce_int(existing_job_state.get("fetch_attempts")) or 0) + 1
        )
        max_attempts = max(
            1,
            self._coerce_int(task_data.get("max_attempts"))
            or self._coerce_int(follow_up_policy.get("max_attempts"))
            or 3,
        )
        simulate_fail_attempts = max(
            0,
            self._coerce_int(task_data.get("simulate_fail_attempts"))
            or self._coerce_int(follow_up_policy.get("simulate_fail_attempts"))
            or 0,
        )
        partial_failure_ref_ids = set(
            self._coerce_str_list(task_data.get("partial_failure_ref_ids"))
            or self._coerce_str_list(follow_up_policy.get("partial_failure_ref_ids"))
        )
        forced_full_failure = attempt_number <= simulate_fail_attempts
        ready_count = 0
        pending_count = 0
        failed_count = 0
        transient_failure_count = 0
        last_error: str | None = None
        completed_at_value: str | None = None
        updated_source_refs: list[dict[str, Any]] = []
        # 真实抓取的 artifact key 前缀，用于 source_fetcher_registry 写入 object_store
        artifact_key_prefix = f"download-fetch/{run_id}/{attempt_number}"

        for item in source_refs:
            source_item = {**item}
            previous_status = str(source_item.get("fetch_status", "pending"))
            source_item["attempt_count"] = attempt_number
            source_item["last_attempt_at"] = updated_at.astimezone(
                timezone.utc
            ).isoformat()
            source_item.setdefault("artifact_locator", None)
            source_item.setdefault("completed_at", None)
            source_item.setdefault("last_error", None)
            source_item.setdefault("fetched_bytes", 0)

            is_fetch_target = previous_status not in {"cached", "ready"}
            if not is_fetch_target:
                # 已 cached/ready 的 source 直接保留状态
                source_item["fetch_status"] = (
                    "cached" if previous_status == "cached" else "ready"
                )
                source_item["fetch_stage"] = source_item.get(
                    "fetch_stage", "metadata_attached"
                )
                ready_count += 1
                updated_source_refs.append(source_item)
                continue

            # 强制模拟失败（仅用于测试重试骨架）
            if forced_full_failure:
                retryable = attempt_number < max_attempts
                source_item["fetch_status"] = "retry_pending" if retryable else "failed"
                source_item["fetch_stage"] = (
                    "awaiting_retry" if retryable else "failed_terminal"
                )
                source_item["last_error"] = (
                    "Simulated download source fetch failure for retryable skeleton."
                )
                source_item["completed_at"] = None
                source_item["artifact_locator"] = None
                pending_count += 1 if retryable else 0
                failed_count += 0 if retryable else 1
                transient_failure_count += 1 if retryable else 0
                last_error = source_item["last_error"]
                updated_source_refs.append(source_item)
                continue

            # 真实抓取：调用 source_fetcher_registry
            ref_id = str(source_item.get("ref_id", "unknown"))
            source_uri = str(source_item.get("source_uri", ""))
            fetch_result = source_fetcher_registry.fetch(
                ref_id=ref_id,
                source_uri=source_uri,
                artifact_key_prefix=artifact_key_prefix,
            )
            source_item["last_attempt_at"] = (
                fetch_result.fetched_at
                or updated_at.astimezone(timezone.utc).isoformat()
            )

            if fetch_result.success:
                source_item["fetch_status"] = "ready"
                source_item["fetch_stage"] = "fetched_to_artifact"
                source_item["last_error"] = None
                source_item["completed_at"] = (
                    fetch_result.fetched_at
                    or updated_at.astimezone(timezone.utc).isoformat()
                )
                source_item["artifact_locator"] = fetch_result.artifact_key
                source_item["fetched_bytes"] = fetch_result.fetched_bytes
                source_item["content_type"] = fetch_result.content_type
                if fetch_result.local_path:
                    source_item["local_path"] = fetch_result.local_path
                ready_count += 1
                completed_at_value = source_item["completed_at"]
            else:
                # 失败分类修复：修复 partial_failure_ref_ids 逻辑漏洞
                # 修复前：retryable = (attempt_number < max_attempts) or forced_partial
                #   → forced_partial=True 时即使超过 max_attempts 仍 retry_pending，永不转终态
                # 修复后：retryable = attempt_number < max_attempts（与 forced_partial 无关）
                #   forced_partial 仅影响是否注入模拟失败，不影响重试判定
                retryable = attempt_number < max_attempts
                source_item["fetch_status"] = "retry_pending" if retryable else "failed"
                source_item["fetch_stage"] = (
                    "awaiting_retry" if retryable else "failed_terminal"
                )
                source_item["last_error"] = (
                    fetch_result.error or "Unknown fetch failure"
                )
                source_item["completed_at"] = None
                source_item["artifact_locator"] = None
                pending_count += 1 if retryable else 0
                failed_count += 0 if retryable else 1
                transient_failure_count += 1 if retryable else 0
                last_error = source_item["last_error"]

            updated_source_refs.append(source_item)

        if failed_count:
            fetch_status = "failed"
        elif transient_failure_count and ready_count:
            fetch_status = "partial_success"
        elif transient_failure_count:
            fetch_status = "retry_pending"
        else:
            fetch_status = "fetched"
            completed_at_value = updated_at.astimezone(timezone.utc).isoformat()

        total_bytes = sum(
            int(item.get("fetched_bytes", 0) or item.get("estimated_bytes", 0))
            for item in updated_source_refs
        )
        partial_success = fetch_status == "partial_success"
        retry_recommended = transient_failure_count > 0
        source_fetch_summary = {
            "status": fetch_status,
            "total_sources": len(updated_source_refs),
            "pending_sources": pending_count,
            "fetched_total_bytes": total_bytes,
            "estimated_total_bytes": sum(
                int(item.get("estimated_bytes", 0)) for item in updated_source_refs
            ),
            "ready_sources": ready_count,
            "failed_sources": failed_count,
            "partial_success": partial_success,
            "completed_at": completed_at_value,
            "last_error": last_error,
        }
        if fetch_status == "failed":
            job_state = {
                **existing_job_state,
                "phase": "failed",
                "status": "failed",
                "progress": 100,
                "requires_fetch": False,
                "artifact_status": "stale",
                "next_action": "mark_download_failed",
                "fetch_attempts": attempt_number,
                "max_attempts": max_attempts,
                "retryable": True,
                "retry_recommended": False,
                "partial_success": False,
                "last_error": last_error,
                "last_attempt_at": updated_at.astimezone(timezone.utc).isoformat(),
                "completed_at": updated_at.astimezone(timezone.utc).isoformat(),
            }
            execution_status = "failed"
        elif retry_recommended:
            job_state = {
                **existing_job_state,
                "phase": "partial_ready" if partial_success else "fetch_retry_pending",
                "status": "partial_success" if partial_success else "retry_pending",
                "progress": 86 if partial_success else 72,
                "requires_fetch": True,
                "artifact_status": "partial"
                if partial_success
                else "stale_pending_retry",
                "next_action": "retry_failed_sources",
                "fetch_attempts": attempt_number,
                "max_attempts": max_attempts,
                "retryable": True,
                "retry_recommended": True,
                "partial_success": partial_success,
                "last_error": last_error,
                "last_attempt_at": updated_at.astimezone(timezone.utc).isoformat(),
                "completed_at": completed_at_value,
            }
            execution_status = "partial_success" if partial_success else "retry_pending"
        else:
            job_state = {
                **existing_job_state,
                "phase": "fulfilled",
                "status": "fetched",
                "progress": 100,
                "requires_fetch": False,
                "artifact_status": "updated",
                "next_action": "publish_cached_manifest",
                "fetch_attempts": attempt_number,
                "max_attempts": max_attempts,
                "retryable": True,
                "retry_recommended": False,
                "partial_success": False,
                "last_error": None,
                "last_attempt_at": updated_at.astimezone(timezone.utc).isoformat(),
                "completed_at": updated_at.astimezone(timezone.utc).isoformat(),
            }
            execution_status = "fetched"

        summary_payload["download_plan"]["source_refs"] = updated_source_refs
        summary_payload["source_fetch"] = source_fetch_summary
        execution_payload["status"] = execution_status
        execution_payload["job_state"] = job_state
        execution_payload["follow_up_policy"] = {
            "max_attempts": max_attempts,
            "retryable": True,
            "simulate_fail_attempts": simulate_fail_attempts,
            "partial_failure_ref_ids": list(partial_failure_ref_ids),
        }

        updated_manifest_ref = result_storage_service.replace_artifact_result_ref(
            run_id=run_id,
            existing_ref=manifest_ref,
            updated_at=updated_at,
            payload=self._build_manifest_payload_from_summary(
                run_id=run_id, summary_payload=summary_payload
            ),
        )
        current_cache = cache_service.get_entry(cache_key)
        ttl_seconds = self._resolve_follow_up_ttl_seconds(
            current_cache=current_cache, now=updated_at
        )
        cache_metadata = {
            **(current_cache.metadata if current_cache is not None else {}),
            "download_ticket_id": summary_payload["execution"]["download_ticket_id"],
            "execution_status": execution_status,
            "job_phase": job_state["phase"],
            "job_progress": job_state["progress"],
            "source_fetch_status": summary_payload["source_fetch"]["status"],
            "fetch_attempts": job_state["fetch_attempts"],
            "max_attempts": job_state["max_attempts"],
            "last_error": job_state["last_error"],
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
            status="warm" if execution_status == "fetched" else "degraded",
            metadata=cache_metadata,
        )
        summary_payload["cache"]["status"] = cache_entry.status
        summary_payload["cache"]["expires_at"] = cache_entry.expires_at.isoformat()
        summary_payload["execution"]["artifact_resource_key"] = (
            updated_manifest_ref.resource_key
        )
        summary_payload["execution"]["artifact_resource_url"] = (
            updated_manifest_ref.resource_url
        )
        summary_payload["execution"]["artifact_resource_size_bytes"] = (
            updated_manifest_ref.resource_size_bytes
        )

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
                                f"{summary_payload['download_plan']['target_dataset']} 下载 follow-up task 已完成第 {attempt_number} 次抓取尝试，"
                                f"当前缓存状态 {cache_entry.status}，"
                                f"执行阶段 {job_state['phase']}，"
                                f"source fetch 状态 {source_fetch_summary['status']}。"
                            )
                        },
                        updated_at=updated_at,
                    )
                )
            else:
                updated_result_refs.append(item)

        task_report = {
            "download_ticket_id": summary_payload["execution"]["download_ticket_id"],
            "execution_status": execution_status,
            "job_phase": job_state["phase"],
            "fetch_attempts": attempt_number,
            "max_attempts": max_attempts,
            "retry_recommended": retry_recommended,
            "partial_success": partial_success,
            "source_fetch_status": source_fetch_summary["status"],
            "ready_sources": ready_count,
            "pending_sources": pending_count,
            "failed_sources": failed_count,
            "last_error": last_error,
            "artifact_resource_key": updated_manifest_ref.resource_key,
            "cache_status": cache_entry.status,
        }
        return (
            updated_result_refs,
            [
                f"download_follow_up_ticket={summary_payload['execution']['download_ticket_id']}",
                f"download_follow_up_status={execution_status}",
                f"download_follow_up_attempt={attempt_number}/{max_attempts}",
                f"download_follow_up_cache={cache_entry.status}",
                f"download_follow_up_source_fetch={source_fetch_summary['status']}",
                f"download_follow_up_artifact={updated_manifest_ref.resource_key}",
            ],
            task_report,
        )

    def _resolve_source_refs(
        self,
        layer_id: str,
        requested_hour: float,
        refresh_policy: str,
        cache_status: str,
    ) -> list[dict[str, Any]]:
        """解析图层的 source_refs。

        优先从 settings.download_source_uri_map 读取真实 source_uri 模板，
        若未配置则回退到 demo:// 占位（保持向后兼容）。
        """
        base_ref = {
            "kind": "demo_snapshot",
            "layer_id": layer_id,
            "requested_hour": requested_hour,
            "refresh_policy": refresh_policy,
        }
        # 尝试从配置读取真实 source_uri
        real_snapshot_uri = self._resolve_real_source_uri(layer_id, requested_hour)
        snapshot_source_kind = "snapshot"
        snapshot_estimated_bytes = 65536
        if real_snapshot_uri:
            snapshot_source_kind = "real_source"
            # 真实源无法预知字节大小，保留估算值用于 cache 元数据
            snapshot_estimated_bytes = 0

        return [
            {
                **base_ref,
                "ref_id": f"{layer_id}-snapshot",
                "priority": "high" if refresh_policy == "realtime" else "normal",
                "fetch_status": "cached" if cache_status == "warm" else "pending",
                "fetch_stage": "source_manifest_ready"
                if cache_status == "warm"
                else "awaiting_dispatch",
                "source_kind": snapshot_source_kind,
                "source_uri": real_snapshot_uri
                or f"demo://snapshots/{layer_id}?hour={requested_hour}",
                "estimated_bytes": snapshot_estimated_bytes,
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

    def _resolve_real_source_uri(
        self, layer_id: str, requested_hour: float
    ) -> str | None:
        """从 settings.download_source_uri_map 读取图层对应的真实 source_uri 模板。

        支持两种配置方式：
        1. 直接 JSON 对象字符串（适合少量图层）
        2. @/path/to/file.json 格式，从外部文件加载 JSON（推荐，方便维护）

        支持占位符：{layer_id} {hour}
        返回 None 表示未配置，调用方回退到 demo:// scheme。
        """
        if not settings.download_real_fetch_enabled:
            return None
        uri_map_raw = settings.download_source_uri_map.strip()
        if not uri_map_raw:
            return None

        # 支持 @file:// 方式加载外部 JSON 文件
        if uri_map_raw.startswith("@"):
            # @/absolute/path.json 或 @relative/path.json
            file_path_str = uri_map_raw[1:].strip()
            map_file = Path(file_path_str)
            # 相对路径相对于 backend 根目录
            if not map_file.is_absolute():
                from app.core.config import BACKEND_ROOT

                map_file = BACKEND_ROOT / file_path_str
            try:
                with open(map_file, encoding="utf-8") as f:
                    raw = f.read()
                # 移除 // 和 # 注释行，支持带注释的 JSON 配置文件
                lines = [
                    line
                    for line in raw.splitlines()
                    if not line.strip().startswith("//")
                    and not line.strip().startswith("#")
                ]
                cleaned = "\n".join(lines)
                uri_map = json.loads(cleaned)
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                return None
        else:
            try:
                uri_map = json.loads(uri_map_raw)
            except (json.JSONDecodeError, TypeError):
                return None

        if not isinstance(uri_map, dict):
            return None
        template = uri_map.get(layer_id)
        if not isinstance(template, str) or not template:
            return None
        # 支持 {layer_id} {hour} 占位符
        hour_int = int(requested_hour)
        try:
            return template.format(
                layer_id=layer_id, hour=hour_int, hour_float=requested_hour
            )
        except (KeyError, IndexError):
            return template

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
            result_id=str(
                metadata.get(
                    "manifest_result_id", f"download-manifest-{uuid4().hex[:10]}"
                )
            ),
            result_kind=ResultKind(result_kind),
            title=str(metadata.get("artifact_title", "Download Manifest")),
            mime_type=str(metadata.get("artifact_mime_type", "application/json")),
            inline_data=None,
            resource_url=str(resource_url),
            resource_backend=str(
                metadata.get("artifact_resource_backend", settings.object_store_backend)
            ),
            resource_key=str(resource_key),
            resource_size_bytes=self._coerce_int(
                metadata.get("artifact_resource_size_bytes")
            ),
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
        follow_up_policy: dict[str, Any],
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
                "follow_up_policy": follow_up_policy,
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
            title=f"{snapshot.display_name} Download Manifest",
            mime_type="application/json",
            updated_at=requested_at,
            payload=manifest_payload,
        )

    def _resolve_download_ticket_id(
        self, cache_entry: CacheEntry | None, cache_status: str
    ) -> str:
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
                "channel": summary_payload.get("download_plan", {}).get(
                    "channel", "download"
                ),
                "command_type": workflow_payload.get("command_type"),
                "layer_id": workflow_payload.get("layer_id"),
            },
            "dataset": {
                "layer_id": workflow_payload.get("layer_id"),
                "display_name": summary_payload.get("download_plan", {}).get(
                    "target_dataset"
                ),
                "requested_hour": summary_payload.get("download_plan", {}).get(
                    "requested_hour"
                ),
                "source_mode": summary_payload.get("download_plan", {}).get(
                    "source_mode"
                ),
                "availability_state": summary_payload.get("preview", {}).get(
                    "availability_state"
                ),
            },
            "execution": {
                "status": execution_payload.get("status"),
                "refresh_policy": summary_payload.get("download_plan", {}).get(
                    "refresh_policy"
                ),
                "executor": "download_follow_up_task",
                "job_state": execution_payload.get("job_state", {}),
                "follow_up_policy": execution_payload.get("follow_up_policy", {}),
            },
            "source_fetch": summary_payload.get("source_fetch", {}),
            "source_refs": summary_payload.get("download_plan", {}).get(
                "source_refs", []
            ),
            "cache": summary_payload.get("cache", {}),
            "preview": summary_payload.get("preview", {}),
        }

    def _resolve_follow_up_ttl_seconds(
        self, *, current_cache: CacheEntry | None, now: datetime
    ) -> int:
        if current_cache is None:
            return settings.cache_default_ttl_seconds
        remaining_seconds = int((current_cache.expires_at - now).total_seconds())
        return max(1, remaining_seconds)

    def _clone_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(payload, ensure_ascii=False))

    def _build_follow_up_policy(
        self, *, payload_parameters: dict[str, Any]
    ) -> dict[str, Any]:
        partial_failure_ref_ids = self._coerce_str_list(
            payload_parameters.get("partial_failure_ref_ids")
        )
        max_attempts = max(
            1, self._coerce_int(payload_parameters.get("max_attempts")) or 3
        )
        simulate_fail_attempts = max(
            0, self._coerce_int(payload_parameters.get("simulate_fail_attempts")) or 0
        )
        return {
            "max_attempts": max_attempts,
            "retryable": True,
            "simulate_fail_attempts": simulate_fail_attempts,
            "partial_failure_ref_ids": partial_failure_ref_ids,
        }

    def _build_job_state(
        self,
        *,
        download_ticket_id: str,
        cache_status: str,
        realtime_preferred: bool,
        refresh_policy: str,
        follow_up_policy: dict[str, Any],
        requested_at: datetime,
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
                "fetch_attempts": 0,
                "max_attempts": follow_up_policy["max_attempts"],
                "retryable": follow_up_policy["retryable"],
                "retry_recommended": False,
                "partial_success": False,
                "last_error": None,
                "last_attempt_at": None,
                "completed_at": requested_at.astimezone(timezone.utc).isoformat(),
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
            "fetch_attempts": 0,
            "max_attempts": follow_up_policy["max_attempts"],
            "retryable": follow_up_policy["retryable"],
            "retry_recommended": False,
            "partial_success": False,
            "last_error": None,
            "last_attempt_at": None,
            "completed_at": None,
        }

    def _build_source_fetch_summary(
        self,
        *,
        source_refs: list[dict[str, Any]],
        cache_status: str,
        follow_up_policy: dict[str, Any],
    ) -> dict[str, Any]:
        total_bytes = sum(int(item.get("estimated_bytes", 0)) for item in source_refs)
        pending_count = sum(
            1
            for item in source_refs
            if item.get("fetch_status") not in {"cached", "ready"}
        )
        if cache_status == "warm":
            return {
                "status": "cache_reused",
                "total_sources": len(source_refs),
                "pending_sources": 0,
                "estimated_total_bytes": total_bytes,
                "ready_sources": len(source_refs),
                "failed_sources": 0,
                "partial_success": False,
                "retryable": follow_up_policy["retryable"],
                "completed_at": None,
                "last_error": None,
            }
        return {
            "status": "awaiting_fetch",
            "total_sources": len(source_refs),
            "pending_sources": pending_count,
            "estimated_total_bytes": total_bytes,
            "ready_sources": len(source_refs) - pending_count,
            "failed_sources": 0,
            "partial_success": False,
            "retryable": follow_up_policy["retryable"],
            "completed_at": None,
            "last_error": None,
        }

    def _coerce_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _coerce_str_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            normalized = value.strip()
            return [normalized] if normalized else []
        if isinstance(value, list):
            items: list[str] = []
            for item in value:
                if isinstance(item, str):
                    normalized = item.strip()
                    if normalized:
                        items.append(normalized)
            return items
        return []


download_service = DownloadService()
