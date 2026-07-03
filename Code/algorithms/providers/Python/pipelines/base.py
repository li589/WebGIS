from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from contracts.job import JobRequest
from contracts.product import ProductManifest
from contracts.runtime import RuntimeContext


@dataclass(slots=True)
class PipelinePlan:
    required_datasets: list[str] = field(default_factory=list)
    required_variables: list[str] = field(default_factory=list)
    estimated_outputs: list[str] = field(default_factory=list)
    parallelizable: bool = False
    chunk_strategy: str | None = None
    cache_requirement: str | None = None


class BasePipeline(ABC):
    name: str

    def __init__(
        self,
        datasource_adapter: Any = None,
        logger_adapter: Any = None,
        product_sink: Any = None,
    ) -> None:
        self.datasource_adapter = datasource_adapter
        self.logger_adapter = logger_adapter
        self.product_sink = product_sink

    @abstractmethod
    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        raise NotImplementedError

    @abstractmethod
    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        raise NotImplementedError
