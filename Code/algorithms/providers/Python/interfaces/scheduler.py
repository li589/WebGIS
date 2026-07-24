from __future__ import annotations

from typing import Any, Protocol

from contracts.job import JobRequest, JobResult


class SchedulerAdapter(Protocol):
    def get_run_context(self, request: JobRequest) -> dict[str, Any]: ...

    def update_status(
        self,
        job_id: str,
        run_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None: ...

    def complete(self, result: JobResult) -> None: ...
