from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class OutputSpec:
    raster_format: str = "COG"
    table_format: str = "parquet"
    include_qc: bool = True
    include_manifest: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProductRef:
    name: str
    type: str
    uri: str
    variable: str | None = None
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ProductManifest:
    job_id: str
    run_id: str
    products: list[ProductRef] = field(default_factory=list)
    main_layers: list[str] = field(default_factory=list)
    qc_layers: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    metadata_uri: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = field(default_factory=dict)
