from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from shared.contracts.api_contracts import ResultKind


@dataclass
class ProviderExecutionPayload:
    layer_id: str
    requested_at: datetime
    requested_hour: float
    parameters: dict[str, Any] = field(default_factory=dict)
    requested_outputs: list[ResultKind | str] = field(default_factory=list)
    spatial_filter: dict[str, Any] = field(default_factory=dict)
    time_range: dict[str, Any] = field(default_factory=dict)
    client: dict[str, Any] = field(default_factory=dict)
    map_context: dict[str, Any] = field(default_factory=dict)
    config_overrides: dict[str, Any] = field(default_factory=dict)
    execution_limits: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None


@dataclass
class ProviderExecutionResult:
    provider_key: str
    layer_id: str
    title: str
    summary: str
    metric_label: str
    metric_unit: str
    metric_value: float | int | str | None
    status_label: str
    confidence_label: str
    hotspots: list[dict[str, Any]] = field(default_factory=list)
    series: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class AlgorithmProvider(Protocol):
    provider_key: str
    supported_layers: tuple[str, ...]

    def execute(self, payload: ProviderExecutionPayload) -> ProviderExecutionResult:
        ...
