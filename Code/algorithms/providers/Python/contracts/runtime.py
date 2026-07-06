from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class TimeRange:
    start: datetime
    end: datetime
    step: str | None = None


@dataclass(slots=True)
class RegionSpec:
    kind: str
    value: dict[str, Any]


@dataclass(slots=True)
class ResourceHint:
    cpu_cores: int | None = None
    memory_gb: float | None = None
    gpu_count: int | None = None
    tmp_disk_gb: float | None = None
    preferred_chunk_size: int | None = None


@dataclass(slots=True)
class CachePolicy:
    mode: str = "metadata_only"
    enabled: bool = True


@dataclass(slots=True)
class RuntimeContext:
    job_id: str
    run_id: str
    workspace: Path
    tmp_dir: Path
    cache_dir: Path
    resource_hint: ResourceHint | None = None
    env: dict[str, str] = field(default_factory=dict)
    call_chain: list[str] = field(default_factory=list)
    storage_backend: Any = None
