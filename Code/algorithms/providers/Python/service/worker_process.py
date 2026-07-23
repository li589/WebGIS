from __future__ import annotations

import argparse
from pathlib import Path

from service.job_api import (
    build_local_job_service,
    build_local_persistent_job_service,
    build_worker,
)
from service.job_queue import FileJobQueue
from service.platform_service_factory import build_platform_http_job_service
from service.worker import PlatformWorkerLoop


def serve_worker(
    *,
    workspace: str,
    queue_backend: str = "file",
    persistent_state: bool = True,
    poll_timeout: float = 0.5,
) -> None:
    service = build_worker_service(
        workspace=workspace,
        queue_backend=queue_backend,
        persistent_state=persistent_state,
    )
    worker = build_worker(service)
    print(
        "mat2py worker listening for queued jobs at "
        f"workspace={Path(workspace)} queue_backend={queue_backend}"
    )
    PlatformWorkerLoop(worker).run_forever(poll_timeout=poll_timeout)


def build_worker_service(
    *,
    workspace: str,
    queue_backend: str = "file",
    persistent_state: bool = True,
):
    resolved_workspace = Path(workspace)
    if queue_backend not in {"memory", "file", "platform"}:
        raise ValueError(f"Unsupported queue backend: {queue_backend}")
    if queue_backend == "memory":
        return build_local_job_service(
            workspace=resolved_workspace,
            start_worker=False,
        )
    if queue_backend == "platform":
        if not persistent_state:
            raise ValueError("queue_backend='platform' requires persistent_state=True.")
        service, _worker, _platform_client = build_platform_http_job_service(
            workspace=resolved_workspace,
            start_worker=False,
        )
        return service
    if not persistent_state:
        raise ValueError("queue_backend='file' requires persistent_state=True.")
    return build_local_persistent_job_service(
        workspace=resolved_workspace,
        job_queue=FileJobQueue(resolved_workspace / "service_state" / "queue"),
        start_worker=False,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a standalone mat2py queue worker."
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument(
        "--queue-backend", choices=("memory", "file", "platform"), default="file"
    )
    parser.add_argument("--persistent-state", action="store_true")
    parser.add_argument("--poll-timeout", type=float, default=0.5)
    return parser


if __name__ == "__main__":
    options = _build_parser().parse_args()
    serve_worker(
        workspace=options.workspace,
        queue_backend=options.queue_backend,
        persistent_state=options.persistent_state or options.queue_backend == "file",
        poll_timeout=options.poll_timeout,
    )
