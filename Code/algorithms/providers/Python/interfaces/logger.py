from __future__ import annotations

from typing import Any, Protocol


class LoggerAdapter(Protocol):
    def bind_context(self, job_id: str, run_id: str) -> None: ...

    def emit_stage_start(self, stage: str, message: str) -> None: ...

    def emit_progress(self, stage: str, progress: float, message: str) -> None: ...

    def emit_warning(
        self,
        stage: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None: ...

    def emit_error(
        self,
        stage: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None: ...

    def emit_artifact(
        self, stage: str, artifact_uri: str, artifact_type: str
    ) -> None: ...

    def emit_stage_end(self, stage: str, message: str) -> None: ...
