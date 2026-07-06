from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .product import OutputSpec
from .runtime import CachePolicy, RegionSpec, ResourceHint, TimeRange


@dataclass(slots=True)
class JobRequest:
    job_id: str
    pipeline_name: str
    task_type: str
    time_range: TimeRange
    region: RegionSpec
    datasource_selection: dict[str, Any]
    algorithm_params: dict[str, Any]
    output_spec: OutputSpec
    resource_hint: ResourceHint | None = None
    cache_policy: CachePolicy | None = None
    resume_policy: dict[str, Any] | None = None
    priority: int | None = None
    tags: dict[str, str] = field(default_factory=dict)
    module_name: str | None = None
    workflow_name: str | None = None
    workflow_definition: Any | None = None
    # 透明透传字段：由调用方设置的工作流入口名，结果侧原样回写
    # 修复前：该字段在 AlgorithmWorkflowRequest 中存在但经 bridge 转换时被丢弃，导致信息损失
    workflow_entry_name: str | None = None


@dataclass(slots=True)
class JobResult:
    job_id: str
    run_id: str
    status: str
    started_at: datetime
    finished_at: datetime
    manifest_uri: str | None = None
    log_uri: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error_summary: str | None = None
