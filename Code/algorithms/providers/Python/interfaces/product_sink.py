from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from contracts.product import ProductManifest, ProductRef


@dataclass(slots=True)
class RasterProduct:
    name: str
    uri: str
    variable: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TableProduct:
    name: str
    uri: str
    table_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ProductSink(Protocol):
    def write_raster(self, product: RasterProduct) -> ProductRef:
        ...

    def write_table(self, product: TableProduct) -> ProductRef:
        ...

    def write_manifest(self, manifest: ProductManifest) -> str:
        ...
