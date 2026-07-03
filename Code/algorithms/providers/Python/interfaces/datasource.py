from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from contracts.data import DataBundle, DataRequest


@dataclass(slots=True)
class DataAsset:
    uri: str
    dataset_name: str
    variables: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class DataSourceAdapter(Protocol):
    def discover(self, request: DataRequest) -> list[DataAsset]:
        ...

    def resolve(self, request: DataRequest) -> DataBundle:
        ...

    def acquire(self, bundle: DataBundle) -> DataBundle:
        ...

    def materialize(self, bundle: DataBundle) -> DataBundle:
        ...
