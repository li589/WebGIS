"""Download progress tracker: follow-up fetch execution + state machine.

Extracted from the original ``download_service.py`` god class. Owns the
"execute" phase of the download follow-up task:

- Iterates ``source_refs`` and dispatches real fetches through
  ``source_fetcher_registry`` (or simulates failures for the retryable
  skeleton test path).
- Classifies per-source outcomes into ``ready`` / ``retry_pending`` /
  ``failed`` and aggregates them into a ``source_fetch_summary``.
- Builds the next ``job_state`` based on the aggregate outcome
  (``fulfilled`` / ``partial_ready`` / ``fetch_retry_pending`` / ``failed``).
- Replaces the manifest artifact in object storage via
  :class:`DownloadManifestWriter` and refreshes the cache entry.
- Returns updated result_refs, diagnostic lines, and a task report for
  the Celery task to persist.

``complete_follow_up_task`` is the single externally-called method on the
download service family (invoked from ``app/tasks/download_tasks.py``);
``prepare_download`` and ``build_follow_up_task`` (in
:mod:`download_orchestrator`) feed it via task_data round-tripped through
Celery.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.services.cache_service import CacheEntry, cache_service
from app.services.download_manifest_writer import (
    DownloadManifestWriter,
    download_manifest_writer,
)
from app.services.download_utils import clone_payload, coerce_int, coerce_str_list
from app.services.source_fetcher import source_fetcher_registry
from shared.contracts.api_contracts import ResultKind, WorkflowResultReference

logger = logging.getLogger(__name__)


class DownloadProgressTracker:
    """Executes a download follow-up fetch attempt and aggregates results."""

    def __init__(
        self,
        *,
        manifest_writer: DownloadManifestWriter | None = None,
    ) -> None:
        self._manifest_writer = manifest_writer or download_manifest_writer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        """Run one fetch attempt and write back updated result_refs.

        Returns ``(updated_result_refs, diagnostic_lines, task_report)``.
        The Celery task in ``download_tasks.py`` persists these into the
        workflow run.
        """
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

        summary_payload = clone_payload(summary_ref.inline_data)
        execution_payload = summary_payload.setdefault("execution", {})
        existing_job_state = execution_payload.setdefault("job_state", {})
        follow_up_policy = execution_payload.setdefault(
            "follow_up_policy",
            {
                "max_attempts": max(1, coerce_int(task_data.get("max_attempts")) or 3),
                "retryable": True,
                "simulate_fail_attempts": max(
                    0, coerce_int(task_data.get("simulate_fail_attempts")) or 0
                ),
                "partial_failure_ref_ids": coerce_str_list(
                    task_data.get("partial_failure_ref_ids")
                ),
            },
        )
        source_refs = clone_payload(
            summary_payload.get("download_plan", {}).get("source_refs", [])
        )
        # Prefer task_data source_refs (passed by build_follow_up_task; more reliable)
        task_source_refs = task_data.get("source_refs")
        if isinstance(task_source_refs, list) and task_source_refs:
            source_refs = clone_payload(task_source_refs)

        attempt_number = (
            max(0, coerce_int(existing_job_state.get("fetch_attempts")) or 0) + 1
        )
        max_attempts = max(
            1,
            coerce_int(task_data.get("max_attempts"))
            or coerce_int(follow_up_policy.get("max_attempts"))
            or 3,
        )
        simulate_fail_attempts = max(
            0,
            coerce_int(task_data.get("simulate_fail_attempts"))
            or coerce_int(follow_up_policy.get("simulate_fail_attempts"))
            or 0,
        )
        partial_failure_ref_ids = set(
            coerce_str_list(task_data.get("partial_failure_ref_ids"))
            or coerce_str_list(follow_up_policy.get("partial_failure_ref_ids"))
        )
        forced_full_failure = attempt_number <= simulate_fail_attempts

        fetch_outcome = self._execute_source_fetches(
            source_refs=source_refs,
            run_id=run_id,
            attempt_number=attempt_number,
            max_attempts=max_attempts,
            forced_full_failure=forced_full_failure,
            updated_at=updated_at,
        )

        # Derive aggregate fetch_status + job_state + execution_status
        source_fetch_summary = self._build_follow_up_source_fetch_summary(
            fetch_outcome=fetch_outcome,
            updated_at=updated_at,
        )
        if source_fetch_summary["status"] == "failed":
            job_state = self._build_failed_job_state(
                existing_job_state=existing_job_state,
                attempt_number=attempt_number,
                max_attempts=max_attempts,
                last_error=fetch_outcome.last_error,
                updated_at=updated_at,
            )
            execution_status = "failed"
        elif source_fetch_summary["retry_recommended"]:
            partial_success = source_fetch_summary["partial_success"]
            job_state = self._build_retry_job_state(
                existing_job_state=existing_job_state,
                partial_success=partial_success,
                attempt_number=attempt_number,
                max_attempts=max_attempts,
                last_error=fetch_outcome.last_error,
                completed_at_value=source_fetch_summary["completed_at"],
                updated_at=updated_at,
            )
            execution_status = "partial_success" if partial_success else "retry_pending"
        else:
            job_state = self._build_fulfilled_job_state(
                existing_job_state=existing_job_state,
                attempt_number=attempt_number,
                max_attempts=max_attempts,
                updated_at=updated_at,
            )
            execution_status = "fetched"

        # Write back to summary_payload
        summary_payload["download_plan"]["source_refs"] = (
            fetch_outcome.updated_source_refs
        )
        summary_payload["source_fetch"] = source_fetch_summary
        execution_payload["status"] = execution_status
        execution_payload["job_state"] = job_state
        execution_payload["follow_up_policy"] = {
            "max_attempts": max_attempts,
            "retryable": True,
            "simulate_fail_attempts": simulate_fail_attempts,
            "partial_failure_ref_ids": list(partial_failure_ref_ids),
        }

        # Replace manifest artifact in object storage
        updated_manifest_ref = self._manifest_writer.replace_manifest_result_ref(
            run_id=run_id,
            existing_ref=manifest_ref,
            updated_at=updated_at,
            summary_payload=summary_payload,
        )

        # Refresh cache entry
        cache_entry = self._refresh_cache_entry(
            cache_key=cache_key,
            execution_status=execution_status,
            job_state=job_state,
            source_fetch_summary=source_fetch_summary,
            updated_manifest_ref=updated_manifest_ref,
            summary_payload=summary_payload,
            updated_at=updated_at,
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

        updated_result_refs = self._assemble_updated_result_refs(
            result_refs=result_refs,
            summary_result_id=summary_result_id,
            manifest_result_id=manifest_result_id,
            summary_payload=summary_payload,
            updated_manifest_ref=updated_manifest_ref,
            cache_entry=cache_entry,
            job_state=job_state,
            source_fetch_summary=source_fetch_summary,
            attempt_number=attempt_number,
            max_attempts=max_attempts,
            updated_at=updated_at,
        )

        task_report = {
            "download_ticket_id": summary_payload["execution"]["download_ticket_id"],
            "execution_status": execution_status,
            "job_phase": job_state["phase"],
            "fetch_attempts": attempt_number,
            "max_attempts": max_attempts,
            "retry_recommended": source_fetch_summary["retry_recommended"],
            "partial_success": source_fetch_summary["partial_success"],
            "source_fetch_status": source_fetch_summary["status"],
            "ready_sources": fetch_outcome.ready_count,
            "pending_sources": fetch_outcome.pending_count,
            "failed_sources": fetch_outcome.failed_count,
            "last_error": fetch_outcome.last_error,
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

    # ------------------------------------------------------------------
    # Fetch loop
    # ------------------------------------------------------------------

    def _execute_source_fetches(
        self,
        *,
        source_refs: list[dict[str, Any]],
        run_id: str,
        attempt_number: int,
        max_attempts: int,
        forced_full_failure: bool,
        updated_at: datetime,
    ) -> "_FetchOutcome":
        """Iterate ``source_refs`` and dispatch real or simulated fetches.

        Returns a :class:`_FetchOutcome` aggregating per-source statuses
        and counters; the caller derives the aggregate ``fetch_status``
        and next ``job_state`` from it.
        """
        ready_count = 0
        pending_count = 0
        failed_count = 0
        transient_failure_count = 0
        last_error: str | None = None
        completed_at_value: str | None = None
        updated_source_refs: list[dict[str, Any]] = []
        # Real fetch artifact key prefix, used by source_fetcher_registry
        # when writing to object_store.
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
                # Already cached/ready: preserve status, no re-fetch
                source_item["fetch_status"] = (
                    "cached" if previous_status == "cached" else "ready"
                )
                source_item["fetch_stage"] = source_item.get(
                    "fetch_stage", "metadata_attached"
                )
                ready_count += 1
                updated_source_refs.append(source_item)
                continue

            # Simulated failure path (retryable skeleton test only)
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

            # Real fetch via source_fetcher_registry
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
                # Failure classification fix: retryable is independent of
                # forced_partial — forced_partial only injects simulated
                # failures, it does not override max_attempts gating.
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

        return _FetchOutcome(
            updated_source_refs=updated_source_refs,
            ready_count=ready_count,
            pending_count=pending_count,
            failed_count=failed_count,
            transient_failure_count=transient_failure_count,
            last_error=last_error,
            completed_at_value=completed_at_value,
        )

    # ------------------------------------------------------------------
    # Aggregate state derivation
    # ------------------------------------------------------------------

    def _build_follow_up_source_fetch_summary(
        self,
        *,
        fetch_outcome: "_FetchOutcome",
        updated_at: datetime,
    ) -> dict[str, Any]:
        """Derive the aggregate ``source_fetch_summary`` from per-source outcomes.

        Also computes ``retry_recommended`` / ``partial_success`` / ``status``
        flags consumed by the job_state builder. Mirrors the original
        ``download_service.py`` aggregation rules:

        - ``failed`` if any source terminally failed.
        - ``partial_success`` if some sources are retryable AND some are ready.
        - ``retry_pending`` if some sources are retryable but none ready.
        - ``fetched`` otherwise (all ready, no failures).

        On ``fetched``, ``completed_at`` is overridden to ``updated_at`` (the
        Celery task's wall clock); on other branches, the last successful
        source's ``completed_at`` is preserved (may be ``None`` if no source
        succeeded in this attempt).
        """
        updated_source_refs = fetch_outcome.updated_source_refs
        if fetch_outcome.failed_count:
            fetch_status = "failed"
        elif fetch_outcome.transient_failure_count and fetch_outcome.ready_count:
            fetch_status = "partial_success"
        elif fetch_outcome.transient_failure_count:
            fetch_status = "retry_pending"
        else:
            fetch_status = "fetched"

        partial_success = fetch_status == "partial_success"
        retry_recommended = fetch_outcome.transient_failure_count > 0
        # On full success, override completed_at with the task's wall clock
        # (matches original behaviour: loop's completed_at_value is only the
        # last source's timestamp, but a fully-fetched plan is considered
        # completed at the task's updated_at).
        if fetch_status == "fetched":
            completed_at_value = updated_at.astimezone(timezone.utc).isoformat()
        else:
            completed_at_value = fetch_outcome.completed_at_value

        return {
            "status": fetch_status,
            "total_sources": len(updated_source_refs),
            "pending_sources": fetch_outcome.pending_count,
            "fetched_total_bytes": sum(
                int(item.get("fetched_bytes", 0) or item.get("estimated_bytes", 0))
                for item in updated_source_refs
            ),
            "estimated_total_bytes": sum(
                int(item.get("estimated_bytes", 0)) for item in updated_source_refs
            ),
            "ready_sources": fetch_outcome.ready_count,
            "failed_sources": fetch_outcome.failed_count,
            "partial_success": partial_success,
            "retry_recommended": retry_recommended,
            "completed_at": completed_at_value,
            "last_error": fetch_outcome.last_error,
        }

    def _build_failed_job_state(
        self,
        *,
        existing_job_state: dict[str, Any],
        attempt_number: int,
        max_attempts: int,
        last_error: str | None,
        updated_at: datetime,
    ) -> dict[str, Any]:
        return {
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

    def _build_retry_job_state(
        self,
        *,
        existing_job_state: dict[str, Any],
        partial_success: bool,
        attempt_number: int,
        max_attempts: int,
        last_error: str | None,
        completed_at_value: str | None,
        updated_at: datetime,
    ) -> dict[str, Any]:
        return {
            **existing_job_state,
            "phase": "partial_ready" if partial_success else "fetch_retry_pending",
            "status": "partial_success" if partial_success else "retry_pending",
            "progress": 86 if partial_success else 72,
            "requires_fetch": True,
            "artifact_status": "partial" if partial_success else "stale_pending_retry",
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

    def _build_fulfilled_job_state(
        self,
        *,
        existing_job_state: dict[str, Any],
        attempt_number: int,
        max_attempts: int,
        updated_at: datetime,
    ) -> dict[str, Any]:
        return {
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

    # ------------------------------------------------------------------
    # Cache + result ref assembly
    # ------------------------------------------------------------------

    def _refresh_cache_entry(
        self,
        *,
        cache_key: str,
        execution_status: str,
        job_state: dict[str, Any],
        source_fetch_summary: dict[str, Any],
        updated_manifest_ref: WorkflowResultReference,
        summary_payload: dict[str, Any],
        updated_at: datetime,
    ) -> CacheEntry:
        """Upsert the cache entry with refreshed metadata after a fetch attempt."""
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
            "source_fetch_status": source_fetch_summary["status"],
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
        return cache_service.upsert_entry(
            cache_key=cache_key,
            scope=current_cache.scope if current_cache is not None else "download-plan",
            ttl_seconds=ttl_seconds,
            status="warm" if execution_status == "fetched" else "degraded",
            metadata=cache_metadata,
        )

    def _assemble_updated_result_refs(
        self,
        *,
        result_refs: list[WorkflowResultReference],
        summary_result_id: str,
        manifest_result_id: str,
        summary_payload: dict[str, Any],
        updated_manifest_ref: WorkflowResultReference,
        cache_entry: CacheEntry,
        job_state: dict[str, Any],
        source_fetch_summary: dict[str, Any],
        attempt_number: int,
        max_attempts: int,
        updated_at: datetime,
    ) -> list[WorkflowResultReference]:
        """Rebuild the result_refs list with updated summary/manifest/text entries."""
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
        return updated_result_refs

    def _resolve_follow_up_ttl_seconds(
        self, *, current_cache: CacheEntry | None, now: datetime
    ) -> int:
        """Preserve remaining TTL on follow-up; fall back to default on cold cache."""
        if current_cache is None:
            return settings.cache_default_ttl_seconds
        remaining_seconds = int((current_cache.expires_at - now).total_seconds())
        return max(1, remaining_seconds)


class _FetchOutcome:
    """Internal aggregate of per-source fetch results.

    Extracted as a small value object so :meth:`_execute_source_fetches`
    can return a typed bundle instead of a long tuple, and the summary
    builder / job_state builder can read named fields.
    """

    __slots__ = (
        "updated_source_refs",
        "ready_count",
        "pending_count",
        "failed_count",
        "transient_failure_count",
        "last_error",
        "completed_at_value",
    )

    def __init__(
        self,
        *,
        updated_source_refs: list[dict[str, Any]],
        ready_count: int,
        pending_count: int,
        failed_count: int,
        transient_failure_count: int,
        last_error: str | None,
        completed_at_value: str | None,
    ) -> None:
        self.updated_source_refs = updated_source_refs
        self.ready_count = ready_count
        self.pending_count = pending_count
        self.failed_count = failed_count
        self.transient_failure_count = transient_failure_count
        self.last_error = last_error
        self.completed_at_value = completed_at_value


# Module-level singleton: tracker is stateless apart from the injected
# manifest_writer singleton, so a single shared instance mirrors the
# original download_service behaviour.
download_progress_tracker = DownloadProgressTracker()
