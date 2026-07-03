from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class LogEvent:
    job_id: str
    run_id: str
    stage: str
    event_type: str
    timestamp: datetime
    message: str
    progress: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)
