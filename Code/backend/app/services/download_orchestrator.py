"""Download orchestrator: planning + source URI resolution.

Extracted from the original ``download_service.py`` god class. Owns the
"prepare" phase of the download workflow:

- Resolves cache status (warm/cold) for a given layer + requested hour.
- Resolves source_refs (real ``source_uri`` templates or ``demo://``
  fallbacks) from ``settings.download_source_uri_map``.
- Builds the follow-up policy, job state, and source fetch summary that
  downstream consumers (progress tracker, manifest writer) consume.
- Materialises the manifest artifact via :class:`DownloadManifestWriter`
  on cache miss.
- Persists the resulting plan in the cache via ``cache_service``.

``prepare_download`` and ``build_follow_up_task`` form the input side of
the download workflow; the output side (fetch execution + manifest
replacement) lives in :mod:`download_progress_tracker`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services.cache_service import CacheEntry, cache_service
from app.services.download_manifest_writer import (
    DownloadManifestWriter,
    download_manifest_writer,
)
from app.services.download_utils import coerce_int, coerce_str_list
from shared.contracts.api_contracts import WorkflowResultReference

logger = logging.getLogger(__name__)


@dataclass
class DownloadPlan:
    """Output of :meth:`DownloadOrchestrator.prepare_download`.

    Bundles every downstream consumer's inputs (cache entry, source refs,
    manifest ref, job state, follow-up policy, etc.) so the orchestrator
    stays the single source of truth for plan-level state.
    """

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


class DownloadOrchestrator:
    """Plans a download workflow run and persists its plan in the cache."""

    def __init__(
        self,
        *,
        manifest_writer: DownloadManifestWriter | None = None,
    ) -> None:
        # Injected to allow tests to swap the manifest writer; defaults to
        # the module-level singleton to preserve original behaviour.
        self._manifest_writer = manifest_writer or download_manifest_writer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        """Build a :class:`DownloadPlan`, materialising the manifest artifact.

        On cache hit (``cache_status == "warm"``), the manifest result ref
        is reconstructed from cache metadata; on cache miss, a fresh
        artifact is created via :class:`DownloadManifestWriter`.
        """
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
        cached_manifest_ref = self._manifest_writer.build_cached_manifest_result_ref(
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
        manifest_result_ref = (
            cached_manifest_ref
            or self._manifest_writer.build_manifest_result_ref(
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
        )
        cache_entry = cache_service.upsert_entry(
            cache_key=cache_key,
            scope="download-plan",
            ttl_seconds=ttl_seconds,
            status=cache_status,
            metadata=self._build_plan_cache_metadata(
                layer_id=layer_id,
                requested_hour=requested_hour,
                refresh_policy=refresh_policy,
                snapshot=snapshot,
                source_refs=source_refs,
                download_ticket_id=download_ticket_id,
                execution_status=execution_status,
                job_state=job_state,
                source_fetch_summary=source_fetch_summary,
                manifest_result_ref=manifest_result_ref,
            ),
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

    def build_follow_up_task(
        self,
        *,
        run_id: str,
        plan: DownloadPlan,
        summary_result_id: str,
    ) -> dict[str, Any]:
        """Materialise a follow-up task descriptor for Celery dispatch.

        The returned dict is consumed by
        :meth:`FollowUpDispatchService.dispatch_follow_up_tasks` and round-trips
        back into :meth:`DownloadProgressTracker.complete_follow_up_task` via
        ``task_data``.
        """
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

    # ------------------------------------------------------------------
    # TTL / ticket / policy / state helpers
    # ------------------------------------------------------------------

    def _resolve_ttl_seconds(
        self, realtime_preferred: bool, payload_parameters: dict[str, Any]
    ) -> int:
        ttl_value = coerce_int(payload_parameters.get("cache_ttl_seconds"))
        if ttl_value is not None:
            return max(1, ttl_value)
        if realtime_preferred:
            return min(settings.cache_default_ttl_seconds, 300)
        return settings.cache_default_ttl_seconds

    def _resolve_download_ticket_id(
        self, cache_entry: CacheEntry | None, cache_status: str
    ) -> str:
        if cache_status == "warm" and cache_entry is not None:
            ticket_id = cache_entry.metadata.get("download_ticket_id")
            if isinstance(ticket_id, str) and ticket_id:
                return ticket_id
        return f"download-{uuid4().hex[:12]}"

    def _build_follow_up_policy(
        self, *, payload_parameters: dict[str, Any]
    ) -> dict[str, Any]:
        partial_failure_ref_ids = coerce_str_list(
            payload_parameters.get("partial_failure_ref_ids")
        )
        max_attempts = max(1, coerce_int(payload_parameters.get("max_attempts")) or 3)
        simulate_fail_attempts = max(
            0, coerce_int(payload_parameters.get("simulate_fail_attempts")) or 0
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

    # ------------------------------------------------------------------
    # Source URI resolution
    # ------------------------------------------------------------------

    def _resolve_source_refs(
        self,
        layer_id: str,
        requested_hour: float,
        refresh_policy: str,
        cache_status: str,
    ) -> list[dict[str, Any]]:
        """Resolve the layer's source_refs.

        Prefer real ``source_uri`` templates from
        ``settings.download_source_uri_map``; fall back to ``demo://``
        placeholders for backward compatibility.
        """
        base_ref = {
            "kind": "demo_snapshot",
            "layer_id": layer_id,
            "requested_hour": requested_hour,
            "refresh_policy": refresh_policy,
        }
        real_snapshot_uri = self._resolve_real_source_uri(layer_id, requested_hour)
        snapshot_source_kind = "snapshot"
        snapshot_estimated_bytes = 65536
        if real_snapshot_uri:
            snapshot_source_kind = "real_source"
            # Real sources cannot pre-declare byte size; keep the estimate
            # only for cache metadata accounting.
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
        """Read the layer's real ``source_uri`` template from settings.

        Supports two configuration forms:

        1. Direct JSON object string (small layer counts).
        2. ``@/path/to/file.json`` — load JSON from an external file
           (recommended for maintainability; supports ``//`` and ``#``
           line comments).

        Supports ``{layer_id}`` / ``{hour}`` / ``{hour_float}`` placeholders.
        Returns ``None`` when unconfigured, in which case the caller falls
        back to ``demo://`` scheme.
        """
        if not settings.download_real_fetch_enabled:
            return None
        uri_map_raw = settings.download_source_uri_map.strip()
        if not uri_map_raw:
            return None

        # @file:// form: load external JSON (with // and # comment stripping)
        if uri_map_raw.startswith("@"):
            file_path_str = uri_map_raw[1:].strip()
            map_file = Path(file_path_str)
            # Relative paths resolve against the backend root
            if not map_file.is_absolute():
                from app.core.config import BACKEND_ROOT

                map_file = BACKEND_ROOT / file_path_str
            try:
                with open(map_file, encoding="utf-8") as f:
                    raw = f.read()
                # Strip // and # comment lines for human-edited JSON config
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
        # Placeholder substitution
        hour_int = int(requested_hour)
        try:
            return template.format(
                layer_id=layer_id, hour=hour_int, hour_float=requested_hour
            )
        except (KeyError, IndexError):
            return template

    # ------------------------------------------------------------------
    # Cache metadata assembly
    # ------------------------------------------------------------------

    def _build_plan_cache_metadata(
        self,
        *,
        layer_id: str,
        requested_hour: float,
        refresh_policy: str,
        snapshot,
        source_refs: list[dict[str, Any]],
        download_ticket_id: str,
        execution_status: str,
        job_state: dict[str, Any],
        source_fetch_summary: dict[str, Any],
        manifest_result_ref: WorkflowResultReference,
    ) -> dict[str, Any]:
        """Assemble the cache entry metadata written by ``prepare_download``.

        Extracted as a helper so the metadata structure is documented in one
        place; mirrors the original ``download_service.py`` field set exactly
        to preserve cache-shape compatibility with existing entries.
        """
        return {
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
        }


# Module-level singleton: orchestrator is stateless apart from the injected
# manifest_writer singleton, so a single shared instance mirrors the
# original download_service behaviour.
download_orchestrator = DownloadOrchestrator()
