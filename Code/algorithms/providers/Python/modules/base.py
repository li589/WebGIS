from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from workflow.schemas import NodeExecutionContext, PortSpec


@dataclass(slots=True)
class ModuleSpec:
    name: str
    description: str | None = None
    input_ports: list[PortSpec] = field(default_factory=list)
    output_ports: list[PortSpec] = field(default_factory=list)
    default_params: dict[str, object] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)


class BaseModule(ABC):
    name: str
    description: str | None = None
    input_ports: list[PortSpec] = []
    output_ports: list[PortSpec] = []
    default_params: dict[str, object] = {}

    def get_spec(self) -> ModuleSpec:
        return ModuleSpec(
            name=self.name,
            description=self.description,
            input_ports=list(self.input_ports),
            output_ports=list(self.output_ports),
            default_params=dict(self.default_params),
        )

    def resolve_params(self, params: dict[str, object]) -> dict[str, object]:
        resolved = dict(self.default_params)
        resolved.update(params)
        return resolved

    @abstractmethod
    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        raise NotImplementedError
