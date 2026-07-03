from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from contracts.job import JobRequest
from contracts.runtime import RuntimeContext


@dataclass(slots=True)
class InputSourceSpec:
    source_type: str
    format: str
    path: str | None = None
    pattern: str | None = None
    field_map: dict[str, list[str]] = field(default_factory=dict)
    selector: dict[str, object] = field(default_factory=dict)
    options: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class PortSpec:
    name: str
    kind: str
    data_class: str
    required: bool = True
    multi_input: bool = False
    description: str | None = None
    shape_hint: str | None = None
    format_hint: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ArtifactRef:
    artifact_id: str
    artifact_type: str
    format: str
    uri: str | None
    producer_node_id: str
    schema_name: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class NodeExecutionContext:
    workflow_id: str
    node_id: str
    request: JobRequest
    runtime_context: RuntimeContext
    workspace: Path
    artifact_store: "ArtifactStoreLike"
    datasource_adapter: Any = None
    logger_adapter: Any = None
    product_sink: Any = None


class ArtifactStoreLike(Protocol):
    def put(self, artifact: ArtifactRef, payload: object | None = None) -> ArtifactRef:
        raise NotImplementedError

    def get(self, artifact_id: str) -> ArtifactRef:
        raise NotImplementedError

    def load(self, artifact_id: str) -> object:
        raise NotImplementedError

    def exists(self, artifact_id: str) -> bool:
        raise NotImplementedError


class NodeExecutor(Protocol):
    def get_input_ports(self) -> list[PortSpec]:
        raise NotImplementedError

    def get_output_ports(self) -> list[PortSpec]:
        raise NotImplementedError

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        raise NotImplementedError
