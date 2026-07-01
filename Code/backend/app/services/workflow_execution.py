from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.contracts.api_contracts import WorkflowEvent, WorkflowResultReference


@dataclass
class WorkflowExecutionResult:
    message: str
    result_refs: list[WorkflowResultReference] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    events: list[WorkflowEvent] = field(default_factory=list)
    follow_up_tasks: list[dict[str, Any]] = field(default_factory=list)
