from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .runtime import CachePolicy, RegionSpec, TimeRange


@dataclass(slots=True)
class DataRequest:
    dataset_name: str
    variables: list[str]
    time_range: TimeRange
    spatial_filter: RegionSpec | None = None
    depth_filter: dict[str, Any] | None = None
    acquire_mode: str = "lazy"
    cache_policy: CachePolicy | None = None
    target_grid: dict[str, Any] | None = None


@dataclass(slots=True)
class DataBundle:
    bundle_id: str
    dataset_name: str
    variables: list[str]
    time_range: TimeRange
    storage_mode: str
    local_paths: list[str] = field(default_factory=list)
    remote_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    is_materialized: bool = False
