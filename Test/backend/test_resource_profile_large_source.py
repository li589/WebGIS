"""资源画像 P1 回归：大文件 data/source 自动升舱 heavy。

用户反馈#5 根因锁：standard worker 仅 2 实例，GEBCO_2024.nc 6.95GB 整读
占满槽位，后续工作流排队、会话过期。提交前 resolver 必须根据定义中的
本地源大小自动升级 heavy（不依赖 UI 手工选择）。
"""

from __future__ import annotations

from pathlib import Path

from app.services.resource_profile_resolver import (
    HEAVY_SOURCE_BYTES,
    infer_resource_profile,
    local_source_max_bytes,
)
from shared.contracts.api_contracts import WorkflowResourceProfile


def _definition(path: str) -> dict:
    return {"nodes": [{"type": "data/source", "properties": {"path": path}}]}


def test_large_local_source_upgrades_heavy(tmp_path: Path) -> None:
    source = tmp_path / "gebco.nc"
    with source.open("wb") as f:
        f.truncate(HEAVY_SOURCE_BYTES + 1)
    definition = _definition(str(source))
    assert local_source_max_bytes(definition) == HEAVY_SOURCE_BYTES + 1
    assert infer_resource_profile(
        current=WorkflowResourceProfile.standard,
        definition=definition,
    ) == WorkflowResourceProfile.heavy


def test_small_local_source_keeps_seed_profile(tmp_path: Path) -> None:
    source = tmp_path / "small.mat"
    source.write_bytes(b"small")
    assert infer_resource_profile(
        current=WorkflowResourceProfile.standard,
        meta={"resource_profile": "standard"},
        definition=_definition(str(source)),
    ) == WorkflowResourceProfile.standard


def test_missing_source_does_not_block_submission() -> None:
    # stat 失败按 0 处理：尽力探测不能让工作流提交直接失败
    assert local_source_max_bytes(_definition("{DATA_ROOT}/missing/unknown.nc")) == 0
