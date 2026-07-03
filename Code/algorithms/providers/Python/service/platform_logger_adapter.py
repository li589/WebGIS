from __future__ import annotations

from typing import Any, Callable

from contracts.event import LogEvent
from service.platform_scheduler_adapter import _resolve_required_callable
from service.platform_templates import PlatformLoggerAdapterTemplate


EmitEventFn = Callable[[LogEvent], None]


class PlatformLoggerAdapter(PlatformLoggerAdapterTemplate):
    def __init__(
        self,
        *,
        platform_client: Any = None,
        emit_event_fn: EmitEventFn | None = None,
    ) -> None:
        super().__init__(platform_client=platform_client)
        self._emit_event_fn = emit_event_fn or _resolve_required_callable(
            platform_client,
            "emit_log_event",
            "emit_event_fn",
        )

    def emit_platform_event(self, event: LogEvent) -> None:
        self._emit_event_fn(event)
