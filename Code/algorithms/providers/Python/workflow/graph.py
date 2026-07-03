from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import InputSourceSpec


@dataclass(slots=True)
class WorkflowNodeSpec:
    node_id: str
    node_type: str
    version: str = "1.0"
    label: str | None = None
    input_bindings: dict[str, str] = field(default_factory=dict)
    params: dict[str, object] = field(default_factory=dict)
    cache_policy: dict[str, object] | None = None
    retry_policy: dict[str, object] | None = None
    enabled: bool = True


@dataclass(slots=True)
class WorkflowEdge:
    from_node: str
    from_port: str
    to_node: str
    to_port: str


@dataclass(slots=True)
class WorkflowOutputSpec:
    name: str
    source: str


@dataclass(slots=True)
class WorkflowDefinition:
    workflow_id: str
    version: str = "1.0"
    name: str | None = None
    description: str | None = None
    inputs: dict[str, InputSourceSpec] = field(default_factory=dict)
    nodes: list[WorkflowNodeSpec] = field(default_factory=list)
    edges: list[WorkflowEdge] = field(default_factory=list)
    outputs: list[WorkflowOutputSpec] = field(default_factory=list)
    defaults: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
