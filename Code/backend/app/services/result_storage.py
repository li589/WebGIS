from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import islice
import json
import logging
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from app.core.config import settings
from app.services.object_store import StoredObject, object_store
from shared.contracts.api_contracts import ResultKind, WorkflowResultReference

logger = logging.getLogger(__name__)


@dataclass
class StoredArtifact:
    artifact_id: str
    file_path: Path | None
    mime_type: str
    title: str
    content_length: int
    public_url: str | None = None


class ResultStorageService:
    def __init__(self) -> None:
        self._store = object_store

    def create_artifact_result_ref(
        self,
        *,
        run_id: str,
        result_id: str,
        result_kind: ResultKind,
        title: str,
        mime_type: str,
        updated_at: datetime,
        payload: dict[str, object] | str | bytes,
    ) -> WorkflowResultReference:
        if isinstance(payload, bytes):
            serialized = payload
        elif isinstance(payload, str):
            serialized = payload.encode("utf-8")
        else:
            serialized = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        artifact_id = f"artifact-{uuid4().hex[:12]}"
        stored_object = self._store.put_bytes(
            object_key=self._artifact_key(artifact_id),
            data=serialized,
            content_type=mime_type,
            metadata={
                "artifact_id": artifact_id,
                "run_id": run_id,
                "result_id": result_id,
                "title": title,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return WorkflowResultReference(
            result_id=result_id,
            result_kind=result_kind,
            title=title,
            mime_type=mime_type,
            inline_data=None,
            resource_url=stored_object.public_url or f"{settings.object_store_public_base}/{artifact_id}",
            resource_backend=settings.object_store_backend,
            resource_key=artifact_id,
            resource_size_bytes=stored_object.content_length,
            updated_at=updated_at,
        )

    def replace_artifact_result_ref(
        self,
        *,
        run_id: str,
        existing_ref: WorkflowResultReference,
        updated_at: datetime,
        payload: dict[str, object] | str | bytes,
    ) -> WorkflowResultReference:
        resource_key = existing_ref.resource_key
        if not resource_key:
            raise ValueError("Cannot replace artifact payload without resource_key.")
        if isinstance(payload, bytes):
            serialized = payload
        elif isinstance(payload, str):
            serialized = payload.encode("utf-8")
        else:
            serialized = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        stored_object = self._store.put_bytes(
            object_key=self._artifact_key(resource_key),
            data=serialized,
            content_type=existing_ref.mime_type,
            metadata={
                "artifact_id": resource_key,
                "run_id": run_id,
                "result_id": existing_ref.result_id,
                "title": existing_ref.title,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return WorkflowResultReference(
            result_id=existing_ref.result_id,
            result_kind=existing_ref.result_kind,
            title=existing_ref.title,
            mime_type=existing_ref.mime_type,
            inline_data=None,
            resource_url=stored_object.public_url or f"{settings.object_store_public_base}/{resource_key}",
            resource_backend=settings.object_store_backend,
            resource_key=resource_key,
            resource_size_bytes=stored_object.content_length,
            updated_at=updated_at,
        )

    def materialize_result_refs(
        self,
        *,
        run_id: str,
        result_refs: list[WorkflowResultReference],
    ) -> tuple[list[WorkflowResultReference], list[str]]:
        persisted: list[WorkflowResultReference] = []
        diagnostics: list[str] = []
        spill_count = 0

        for result_ref in result_refs:
            if result_ref.inline_data is None:
                persisted.append(result_ref)
                continue

            serialized = json.dumps(result_ref.inline_data, ensure_ascii=False).encode("utf-8")
            if len(serialized) <= settings.result_inline_max_bytes:
                persisted.append(result_ref)
                continue

            stored = self._write_artifact(
                run_id=run_id,
                result_ref=result_ref,
                serialized=serialized,
            )
            spill_count += 1
            diagnostics.append(
                f"result_spilled={result_ref.result_id}:{len(serialized)}bytes->{stored.artifact_id}"
            )
            persisted.append(
                WorkflowResultReference(
                    result_id=result_ref.result_id,
                    result_kind=result_ref.result_kind,
                    title=result_ref.title,
                    mime_type=result_ref.mime_type,
                    inline_data=None,
                    resource_url=f"{settings.object_store_public_base}/{stored.artifact_id}",
                    resource_backend=settings.object_store_backend,
                    resource_key=stored.artifact_id,
                    resource_size_bytes=stored.content_length,
                    updated_at=result_ref.updated_at,
                )
            )

        if spill_count:
            logger.info("Spilled %s workflow results to artifact storage", spill_count)
        return persisted, diagnostics

    def get_artifact(self, artifact_id: str) -> StoredArtifact | None:
        stored_object = self._store.get_object(self._artifact_key(artifact_id))
        if stored_object is None:
            return None
        return StoredArtifact(
            artifact_id=artifact_id,
            file_path=stored_object.file_path,
            mime_type=stored_object.content_type,
            title=str(stored_object.metadata.get("title", artifact_id)),
            content_length=stored_object.content_length,
            public_url=stored_object.public_url,
        )

    def build_chunked_reference(
        self,
        *,
        run_id: str,
        result_kind: ResultKind,
        title: str,
        mime_type: str,
        updated_at: datetime,
        items: Iterable[dict[str, object]],
        chunk_size: int,
        manifest_payload: dict[str, object],
    ) -> tuple[WorkflowResultReference, list[str]]:
        artifact_id = f"artifact-{uuid4().hex[:12]}"
        chunk_count = 0
        chunk_refs: list[dict[str, object]] = []
        total_items = 0
        item_iterator = iter(items)
        while True:
            chunk_items = list(islice(item_iterator, max(1, chunk_size)))
            if not chunk_items:
                break
            chunk_index = chunk_count
            chunk_count += 1
            total_items += len(chunk_items)
            chunk_object = self._store.put_bytes(
                object_key=self._artifact_key(f"{artifact_id}-chunk-{chunk_index}"),
                data=json.dumps({"items": chunk_items}, ensure_ascii=False).encode("utf-8"),
                content_type="application/json",
                metadata={
                    "run_id": run_id,
                    "title": f"{title} chunk {chunk_index}",
                    "chunk_index": chunk_index,
                    "item_count": len(chunk_items),
                    "artifact_id": f"{artifact_id}-chunk-{chunk_index}",
                },
            )
            chunk_refs.append(
                {
                    "chunk_index": chunk_index,
                    "item_count": len(chunk_items),
                    "resource_url": chunk_object.public_url
                    or f"{settings.object_store_public_base}/{chunk_object.metadata.get('artifact_id', chunk_object.object_key)}",
                    "resource_key": chunk_object.metadata.get("artifact_id", chunk_object.object_key),
                    "resource_backend": settings.object_store_backend,
                    "resource_size_bytes": chunk_object.content_length,
                }
            )

        manifest_data = {
            **manifest_payload,
            "chunked": True,
            "chunk_count": chunk_count,
            "item_count": total_items,
            "chunks": chunk_refs,
        }
        manifest_object = self._store.put_bytes(
            object_key=self._artifact_key(artifact_id),
            data=json.dumps(manifest_data, ensure_ascii=False).encode("utf-8"),
            content_type=mime_type,
            metadata={
                "artifact_id": artifact_id,
                "run_id": run_id,
                "title": title,
                "chunk_count": chunk_count,
                "item_count": total_items,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return (
            WorkflowResultReference(
                result_id=f"chunked-{uuid4().hex[:10]}",
                result_kind=result_kind,
                title=title,
                mime_type=mime_type,
                inline_data=manifest_data,
                resource_url=manifest_object.public_url or f"{settings.object_store_public_base}/{artifact_id}",
                resource_backend=settings.object_store_backend,
                resource_key=artifact_id,
                resource_size_bytes=manifest_object.content_length,
                updated_at=updated_at,
            ),
            [f"chunked_result={title}:{total_items}items/{chunk_count}chunks"],
        )

    def _write_artifact(
        self,
        *,
        run_id: str,
        result_ref: WorkflowResultReference,
        serialized: bytes,
    ) -> StoredArtifact:
        artifact_id = f"artifact-{uuid4().hex[:12]}"
        stored_object = self._store.put_bytes(
            object_key=self._artifact_key(artifact_id),
            data=(
                str(result_ref.inline_data.get("text", "")).encode("utf-8")
                if result_ref.mime_type.startswith("text/plain") and result_ref.inline_data
                else serialized
            ),
            content_type=result_ref.mime_type,
            metadata={
                "artifact_id": artifact_id,
                "run_id": run_id,
                "result_id": result_ref.result_id,
                "title": result_ref.title,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return StoredArtifact(
            artifact_id=artifact_id,
            file_path=stored_object.file_path,
            mime_type=result_ref.mime_type,
            title=result_ref.title,
            content_length=stored_object.content_length,
            public_url=stored_object.public_url,
        )

    def _artifact_key(self, artifact_name: str) -> str:
        return artifact_name


result_storage_service = ResultStorageService()
