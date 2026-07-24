"""Manifest writer for the download service.

Extracted from the original ``download_service.py`` god class. Owns the
construction and replacement of the download manifest artifact
(:class:`WorkflowResultReference`), and the derivation of a manifest payload
from a follow-up summary payload.

Responsibilities:
- Build a cached manifest result ref from a warm ``CacheEntry`` (cache hit
  path, no new artifact created).
- Build a fresh manifest result ref by invoking
  :meth:`result_storage_service.create_artifact_result_ref` (cache miss path).
- Rebuild a manifest payload from the summary payload when follow-up
  completion needs to overwrite the stored artifact via
  :meth:`result_storage_service.replace_artifact_result_ref`.

Does NOT touch cache upsert logic or fetch state machines — those live in
:mod:`download_orchestrator` and :mod:`download_progress_tracker` respectively.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services.cache_service import CacheEntry
from app.services.result_storage import result_storage_service
from app.services.download_utils import coerce_int
from shared.contracts.api_contracts import ResultKind, WorkflowResultReference


class DownloadManifestWriter:
    """Builds and replaces download manifest artifact result references.

    Stateless apart from the injected ``result_storage_service`` singleton;
    constructed once per ``DownloadService`` instance.
    """

    def build_cached_manifest_result_ref(
        self,
        *,
        cache_entry: CacheEntry | None,
        requested_at: datetime,
    ) -> WorkflowResultReference | None:
        """Reconstruct a manifest result ref from a warm cache entry.

        Returns ``None`` when the cache entry is missing, stale, or lacks the
        required ``resource_key`` / ``resource_url`` metadata — caller should
        then fall back to :meth:`build_manifest_result_ref` to create a fresh
        artifact.
        """
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
            resource_size_bytes=coerce_int(
                metadata.get("artifact_resource_size_bytes")
            ),
            updated_at=requested_at,
        )

    def build_manifest_result_ref(
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
        """Create a fresh manifest artifact via ``result_storage_service``.

        Used on cache miss (``prepare_download``) to materialise a new
        artifact in object storage and obtain its ``resource_key`` / URL.
        """
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

    def build_manifest_payload_from_summary(
        self,
        *,
        run_id: str,
        summary_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Derive a fresh manifest payload from a follow-up summary payload.

        Used by :meth:`DownloadProgressTracker.complete_follow_up_task` when
        overwriting the stored manifest artifact after a fetch attempt.
        """
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

    def replace_manifest_result_ref(
        self,
        *,
        run_id: str,
        existing_ref: WorkflowResultReference,
        updated_at: datetime,
        summary_payload: dict[str, Any],
    ) -> WorkflowResultReference:
        """Overwrite the stored manifest artifact with a freshly derived payload.

        Thin wrapper around ``result_storage_service.replace_artifact_result_ref``
        so the progress tracker does not need to know the manifest payload
        structure.
        """
        return result_storage_service.replace_artifact_result_ref(
            run_id=run_id,
            existing_ref=existing_ref,
            updated_at=updated_at,
            payload=self.build_manifest_payload_from_summary(
                run_id=run_id, summary_payload=summary_payload
            ),
        )


# Module-level singleton: manifest writer is stateless aside from the
# injected result_storage_service singleton, so a single shared instance
# mirrors the original download_service behaviour.
download_manifest_writer = DownloadManifestWriter()
