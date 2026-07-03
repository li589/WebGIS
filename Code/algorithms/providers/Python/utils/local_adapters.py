from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from contracts.data import DataBundle, DataRequest
from contracts.job import JobRequest, JobResult
from contracts.product import ProductManifest, ProductRef


class LocalSchedulerAdapter:
    def get_run_context(self, request: JobRequest) -> dict[str, Any]:
        return {"job_id": request.job_id}

    def update_status(
        self,
        job_id: str,
        run_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        _ = (job_id, run_id, status, detail)

    def complete(self, result: JobResult) -> None:
        _ = result


class LocalDataSourceAdapter:
    def discover(self, request: DataRequest) -> list[Any]:
        _ = request
        return []

    def resolve(self, request: DataRequest) -> DataBundle:
        return DataBundle(
            bundle_id=request.dataset_name,
            dataset_name=request.dataset_name,
            variables=request.variables,
            time_range=request.time_range,
            storage_mode=request.acquire_mode,
        )

    def acquire(self, bundle: DataBundle) -> DataBundle:
        return bundle

    def materialize(self, bundle: DataBundle) -> DataBundle:
        bundle.is_materialized = True
        return bundle


class ConsoleLoggerAdapter:
    def __init__(self) -> None:
        self._job_id: str | None = None
        self._run_id: str | None = None

    def _emit(self, event_type: str, stage: str, message: str, **extra: Any) -> None:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "stage": stage,
            "message": message,
        }
        if self._job_id is not None:
            payload["job_id"] = self._job_id
        if self._run_id is not None:
            payload["run_id"] = self._run_id
        payload.update(extra)
        print(json.dumps(payload, ensure_ascii=False))

    def bind_context(self, job_id: str, run_id: str) -> None:
        self._job_id = job_id
        self._run_id = run_id
        self._emit("bind", "dispatch", "Bind logging context")

    def emit_stage_start(self, stage: str, message: str) -> None:
        self._emit("stage_start", stage, message)

    def emit_progress(self, stage: str, progress: float, message: str) -> None:
        self._emit("progress", stage, message, progress=progress)

    def emit_warning(
        self,
        stage: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._emit("warning", stage, message, extra=extra or {})

    def emit_error(
        self,
        stage: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._emit("error", stage, message, extra=extra or {})

    def emit_artifact(self, stage: str, artifact_uri: str, artifact_type: str) -> None:
        self._emit("artifact", stage, "Artifact emitted", artifact_uri=artifact_uri, artifact_type=artifact_type)

    def emit_stage_end(self, stage: str, message: str) -> None:
        self._emit("stage_end", stage, message)


class LocalProductSink:
    def __init__(self, manifest_dir: str | Path | None = None) -> None:
        self.manifest_dir = Path(manifest_dir or Path.cwd() / "products" / "manifests")
        self.manifest_dir.mkdir(parents=True, exist_ok=True)

    def write_raster(self, product: Any) -> ProductRef:
        return ProductRef(name=product.name, type="raster", uri=product.uri, variable=product.variable)

    def write_table(self, product: Any) -> ProductRef:
        return ProductRef(name=product.name, type="table", uri=product.uri)

    def write_manifest(self, manifest: ProductManifest) -> str:
        output_path = self.manifest_dir / f"{manifest.run_id}.json"
        payload = _serialize_product_manifest(manifest)
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        return str(output_path)


def _serialize_product_ref(product: ProductRef) -> dict[str, Any]:
    return {
        "name": product.name,
        "type": product.type,
        "uri": product.uri,
        "variable": product.variable,
        "tags": dict(product.tags),
    }


def _serialize_product_manifest(manifest: ProductManifest) -> dict[str, Any]:
    return {
        "job_id": manifest.job_id,
        "run_id": manifest.run_id,
        "products": [_serialize_product_ref(product) for product in manifest.products],
        "main_layers": list(manifest.main_layers),
        "qc_layers": list(manifest.qc_layers),
        "tables": list(manifest.tables),
        "metadata_uri": manifest.metadata_uri,
        "created_at": manifest.created_at.isoformat(),
        "extra": dict(manifest.extra),
    }
