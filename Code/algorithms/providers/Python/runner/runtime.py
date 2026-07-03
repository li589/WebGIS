from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from contracts.job import JobRequest
from contracts.runtime import RuntimeContext

def build_runtime_context(request: JobRequest, workspace: Path) -> RuntimeContext:
    run_id = f"{request.job_id}-{uuid4().hex[:8]}"
    tmp_dir = workspace / "tmp" / run_id
    cache_dir = workspace / "cache"

    return RuntimeContext(
        job_id=request.job_id,
        run_id=run_id,
        workspace=workspace,
        tmp_dir=tmp_dir,
        cache_dir=cache_dir,
        resource_hint=request.resource_hint,
        env={
            "created_at": datetime.now(UTC).isoformat(),
        },
        call_chain=[],
    )
