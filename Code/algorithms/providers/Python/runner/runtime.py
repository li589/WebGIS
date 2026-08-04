from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from contracts.job import JobRequest
from contracts.runtime import RuntimeContext


def _build_storage_backend() -> "Any | None":
    """根据环境变量自动构建 storage backend。

    BACKEND_STORAGE_BACKEND:
        - "local"（默认）：本地文件系统
        - "minio"：MinIO 对象存储
    """
    import os

    backend_type = os.environ.get("BACKEND_STORAGE_BACKEND", "local").strip().lower()

    if backend_type == "minio":
        try:
            from storage.factory import get_output_storage_backend

            return get_output_storage_backend()
        except Exception:
            return None

    # local 模式：使用 LocalFileSystemStorage
    try:
        output_root_env = os.environ.get("BACKEND_OUTPUT_ROOT", "")
        if output_root_env:
            root = Path(output_root_env).expanduser().resolve()
        else:
            root = Path.home() / ".geooutput"
        root.mkdir(parents=True, exist_ok=True)
        from storage.local_fs import LocalFileSystemStorage

        return LocalFileSystemStorage(root)
    except Exception:
        return None


def build_runtime_context(request: JobRequest, workspace: Path) -> RuntimeContext:
    job_id = str(request.job_id)
    # Workflow Celery runs use job_id == workflow run id (run-*). Align tmp_dir
    # with backend lifecycle cancel flag: workspace/tmp/{run_id}/cancel.requested
    if job_id.startswith("run-"):
        run_id = job_id
        tmp_dir = workspace / "tmp" / run_id
    else:
        run_id = f"{job_id}-{uuid4().hex[:8]}"
        tmp_dir = workspace / "tmp" / run_id
    tmp_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = workspace / "cache"
    cancel_flag_path = tmp_dir / "cancel.requested"

    return RuntimeContext(
        job_id=request.job_id,
        run_id=run_id,
        workspace=workspace,
        tmp_dir=tmp_dir,
        cache_dir=cache_dir,
        resource_hint=request.resource_hint,
        env={
            "created_at": datetime.now(UTC).isoformat(),
            "cancel_flag_path": str(cancel_flag_path),
        },
        call_chain=[],
        storage_backend=_build_storage_backend(),
    )
