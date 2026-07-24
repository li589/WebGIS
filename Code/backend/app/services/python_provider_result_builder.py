"""Python provider result builder: post-submit result ref construction.

Extracted from the original ``python_provider_bridge_service.py`` god class.
Owns all "after ``service.submit_job()`` returns" concerns:

- :meth:`build_result_refs` assembles the canonical json result_ref
  (always emitted), the text summary ref (when ``ResultKind.text`` is
  requested), and artifact refs for manifest / metadata / log artifacts.
- :meth:`_build_artifact_ref` resolves artifact URIs to local files
  (spilling to object storage via ``result_storage_service`` when the
  file exists locally) or returns external URL-backed refs.
- :meth:`_uri_to_local_path` converts ``file://`` / bare-path URIs to
  :class:`Path` instances, with Windows drive-letter normalization.

The bridge service calls :meth:`build_result_refs` after a successful
``submit_job``; this module is unaware of validation, dispatch, or
diagnostics — those live in :mod:`python_provider_request_builder` and
the bridge service itself.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app.services.result_storage import result_storage_service
from shared.contracts.api_contracts import (
    ResultKind,
    WorkflowResultReference,
    WorkflowSubmitRequest,
)

# MIME types for the three standard algorithm artifact kinds. Indexed by
# the artifact_name key used in result_dto.artifacts.
_ARTIFACT_MIME_TYPES: dict[str, str] = {
    "manifest": "application/json",
    "metadata": "application/json",
    "log": "text/plain",
}


def as_dict(value: Any) -> dict[str, Any]:
    """Coerce arbitrary input to ``dict``; return ``{}`` on non-dict input.

    Module-level utility shared by the bridge service (for parsing
    ``job_result`` / ``result_dto`` from the provider response) and the
    result builder (for parsing ``artifacts`` / ``manifest_summary``).
    """
    if isinstance(value, dict):
        return dict(value)
    return {}


class PythonProviderResultBuilder:
    """Builds workflow result_refs from a Python provider job result."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_result_refs(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        request_payload: dict[str, Any],
        job_result: dict[str, Any],
        result_dto: dict[str, Any],
    ) -> list[WorkflowResultReference]:
        """Assemble result_refs for the json / text / artifact kinds.

        Always emits a json result_ref (the canonical algorithm result
        carrying ``algorithm_request`` + ``job_result`` + ``result_dto``).
        Text and artifact refs are emitted based on
        ``payload.requested_outputs`` and ``result_dto.artifacts``.
        """
        requested_output_kinds = {
            item.value if isinstance(item, ResultKind) else str(item)
            for item in payload.requested_outputs
        }

        result_refs: list[WorkflowResultReference] = [
            WorkflowResultReference(
                result_id=f"algorithm-result-{run_id[-8:]}",
                result_kind=ResultKind.json,
                title="Algorithm Task Result",
                mime_type="application/json",
                inline_data={
                    "workflow": {
                        "run_id": run_id,
                        "command_type": payload.command_type.value,
                        "layer_id": payload.layer_id,
                    },
                    "algorithm_request": request_payload,
                    "job_result": job_result,
                    "result_dto": result_dto,
                },
                updated_at=requested_at,
            )
        ]

        if ResultKind.text.value in requested_output_kinds:
            summary = self._build_text_summary(
                request_payload=request_payload,
                job_result=job_result,
                result_dto=result_dto,
            )
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"algorithm-summary-{run_id[-8:]}",
                    result_kind=ResultKind.text,
                    title="Algorithm Task Summary",
                    mime_type="text/plain",
                    inline_data={"text": summary},
                    updated_at=requested_at,
                )
            )

        result_refs.extend(
            self._build_artifact_refs(
                run_id=run_id,
                requested_at=requested_at,
                result_dto=result_dto,
            )
        )
        return result_refs

    # ------------------------------------------------------------------
    # Text summary
    # ------------------------------------------------------------------

    def _build_text_summary(
        self,
        *,
        request_payload: dict[str, Any],
        job_result: dict[str, Any],
        result_dto: dict[str, Any],
    ) -> str:
        """Build a one-line human-readable summary of the algorithm result."""
        entry_name = (
            request_payload.get("workflow_name")
            or request_payload.get("module_name")
            or "workflow_definition"
        )
        manifest_summary = as_dict(result_dto.get("manifest_summary"))
        return (
            f"算法任务 {entry_name} 已执行完成，"
            f"job_status={job_result.get('status')}，"
            f"manifest_loaded={bool(result_dto.get('manifest_loaded'))}，"
            f"products={manifest_summary.get('product_count', 0)}。"
        )

    # ------------------------------------------------------------------
    # Artifact refs (manifest / metadata / log)
    # ------------------------------------------------------------------

    def _build_artifact_refs(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        result_dto: dict[str, Any],
    ) -> list[WorkflowResultReference]:
        """Iterate the three standard artifact kinds and build refs for each.

        Skips artifact kinds that are absent from ``result_dto.artifacts``
        or whose URIs resolve to nothing.
        """
        artifacts = as_dict(result_dto.get("artifacts"))
        artifact_refs: list[WorkflowResultReference] = []
        for artifact_name in ("manifest", "metadata", "log"):
            artifact_view = as_dict(artifacts.get(artifact_name))
            if not artifact_view:
                continue
            artifact_ref = self._build_artifact_ref(
                run_id=run_id,
                requested_at=requested_at,
                artifact_name=artifact_name,
                artifact_view=artifact_view,
            )
            if artifact_ref is not None:
                artifact_refs.append(artifact_ref)
        return artifact_refs

    def _build_artifact_ref(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        artifact_name: str,
        artifact_view: dict[str, Any],
    ) -> WorkflowResultReference | None:
        """Build a single artifact ref, preferring local-file spill when available.

        Resolution order for the artifact URI:
        1. ``download_url``
        2. ``preview_url``
        3. ``uri``

        If the URI resolves to a local file that exists, the file is
        spilled to object storage via ``result_storage_service`` and a
        file-kind ref is returned. Otherwise, an external URL-backed ref
        is returned carrying ``resource_url`` / ``resource_backend`` /
        ``resource_key``.
        """
        title = f"Algorithm {artifact_name}"
        uri = str(
            artifact_view.get("download_url")
            or artifact_view.get("preview_url")
            or artifact_view.get("uri")
            or ""
        ).strip()
        if not uri:
            return None

        local_path = self._uri_to_local_path(uri)
        if local_path is not None and local_path.exists() and local_path.is_file():
            payload = local_path.read_bytes()
            return result_storage_service.create_artifact_result_ref(
                run_id=run_id,
                result_id=f"algorithm-{artifact_name}-{local_path.stem}",
                result_kind=ResultKind.file,
                title=title,
                mime_type=_ARTIFACT_MIME_TYPES[artifact_name],
                updated_at=requested_at,
                payload=payload,
            )

        parsed = urlparse(uri)
        resource_backend = str(
            artifact_view.get("storage_backend") or parsed.scheme or "external"
        )
        resource_key = str(artifact_view.get("object_key") or parsed.path or uri)
        if resource_backend == "file" and not resource_key.startswith("/"):
            resource_key = f"/{resource_key.lstrip('/')}"
        return WorkflowResultReference(
            result_id=f"algorithm-{artifact_name}-{run_id[-8:]}",
            result_kind=ResultKind.file,
            title=title,
            mime_type=_ARTIFACT_MIME_TYPES[artifact_name],
            resource_url=uri,
            resource_backend=resource_backend,
            resource_key=resource_key,
            updated_at=requested_at,
        )

    # ------------------------------------------------------------------
    # URI → local path resolution
    # ------------------------------------------------------------------

    def _uri_to_local_path(self, uri: str) -> Path | None:
        """Convert a ``file://`` or bare-path URI to a :class:`Path`.

        Returns ``None`` for non-file schemes (http, https, s3, etc.).
        Handles Windows drive-letter quirk where ``file:///C:/path``
        parses to ``/C:/path`` (leading slash stripped).
        """
        parsed = urlparse(uri)
        if parsed.scheme not in {"", "file"}:
            return None
        if parsed.scheme == "file":
            raw_path = unquote(f"{parsed.netloc}{parsed.path}")
        else:
            raw_path = unquote(uri)
        if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
            raw_path = raw_path[1:]
        if not raw_path:
            return None
        return Path(raw_path)


# Module-level singleton: result builder is stateless apart from the
# result_storage_service singleton, so a single shared instance mirrors
# the original bridge service behaviour.
python_provider_result_builder = PythonProviderResultBuilder()
