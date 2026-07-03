from __future__ import annotations

from typing import Any, Callable

from contracts.job import JobRequest, JobResult
from service.platform_templates import PlatformSchedulerAdapterTemplate


RunContextProvider = Callable[[JobRequest], dict[str, Any]]
StatusPublisher = Callable[[str, str, str, dict[str, Any] | None], None]
CompletionPublisher = Callable[[JobResult], None]


class PlatformSchedulerAdapter(PlatformSchedulerAdapterTemplate):
    def __init__(
        self,
        *,
        platform_client: Any = None,
        run_context_provider: RunContextProvider | None = None,
        status_publisher: StatusPublisher | None = None,
        completion_publisher: CompletionPublisher | None = None,
    ) -> None:
        super().__init__(platform_client=platform_client)
        self._run_context_provider = run_context_provider or _resolve_optional_callable(
            platform_client,
            "build_run_context",
        )
        self._status_publisher = status_publisher or _resolve_required_callable(
            platform_client,
            "update_job_status",
            "status_publisher",
        )
        self._completion_publisher = completion_publisher or _resolve_required_callable(
            platform_client,
            "complete_job",
            "completion_publisher",
        )

    def build_run_context(self, request: JobRequest) -> dict[str, Any]:
        if self._run_context_provider is None:
            return {"job_id": request.job_id}
        return dict(self._run_context_provider(request))

    def push_status(
        self,
        *,
        job_id: str,
        run_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._status_publisher(job_id, run_id, status, detail)

    def push_completion(self, result: JobResult) -> None:
        self._completion_publisher(result)


def _resolve_optional_callable(platform_client: Any, name: str):
    if platform_client is None:
        return None
    candidate = getattr(platform_client, name, None)
    if candidate is None:
        return None
    if not callable(candidate):
        raise TypeError(f"platform_client.{name} must be callable")
    return candidate


def _resolve_required_callable(platform_client: Any, name: str, parameter_name: str):
    candidate = _resolve_optional_callable(platform_client, name)
    if candidate is None:
        raise ValueError(f"{parameter_name} is required, or platform_client.{name} must be provided")
    return candidate
