from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from shared.contracts.api_contracts import ResultKind

# P0-5：parameter dict DoS 上限。真源在此（payload 构造即校验），
# provider_adapter._MAX_PARAMETER_KEYS 与 backend provider_workflow_service
# 的同名常量须与此保持一致。
MAX_PARAMETER_KEYS = 64


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

    def __post_init__(self) -> None:
        # 安审 2026-08-22（E-2）：构造即封顶，独立于 backend bridge 的校验，
        # 保证直连算法包路径同样受 P0-5 保护。
        if len(self.parameters) > MAX_PARAMETER_KEYS:
            raise ValueError(
                f"Too many parameter keys: {len(self.parameters)} > "
                f"{MAX_PARAMETER_KEYS}. Rejecting to prevent parameter DoS."
            )


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

    def execute(self, payload: ProviderExecutionPayload) -> ProviderExecutionResult: ...
