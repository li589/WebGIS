"""图层平台子系统 P0：layer-assets / lifecycle 接口回归。

覆盖：
- get_asset_state 公有查询（未知图层 ValueError→404 语义）
- /layer-assets/{layer_id} 响应契约（asset_state/bake_version/time_list）
- /layers/{layer_id}/lifecycle 聚合（资产 + 最近 run + lifecycle_state 推导）
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.overlay_asset_workflow_service import (
    OverlayAssetWorkflowService,
    overlay_asset_workflow_service,
)


def test_get_asset_state_unknown_layer_raises() -> None:
    with pytest.raises(ValueError, match="Unknown overlay layer"):
        overlay_asset_workflow_service.get_asset_state("no-such-layer-xyz")


def test_get_asset_state_known_layer_structure(monkeypatch) -> None:
    """已知图层返回结构化资产状态（用注册表里的静态层做样本）。"""

    class _FakeRepo:
        def list_runs_by_layer(self, layer_id, *, limit=10, workflow_kind=None):
            return []

    service = OverlayAssetWorkflowService(repository=_FakeRepo())
    state = service.get_asset_state("aridity-cn")
    assert state["layer_id"] == "aridity-cn"
    assert state["asset_state"] in {"fresh", "stale", "missing", "unversioned"}
    assert isinstance(state["current_bake_version"], int)
    assert isinstance(state["time_list"], list)


def test_compute_lifecycle_state_matrix() -> None:
    """lifecycle_state 推导矩阵：活跃 run 优先，其次资产状态，再看失败 run。"""
    from app.api.routers.layer_router import _compute_lifecycle_state

    class _Run:
        def __init__(self, status: str) -> None:
            self.status = status

    # 活跃 run 优先于一切
    assert _compute_lifecycle_state("fresh", [_Run("running")])[0] == "updating"
    assert _compute_lifecycle_state("missing", [_Run("queued")])[0] == "updating"
    # 无活跃 run：按资产状态
    assert _compute_lifecycle_state("fresh", [])[0] == "fresh"
    assert _compute_lifecycle_state("stale", [_Run("succeeded")])[0] == "stale"
    assert _compute_lifecycle_state("missing", [])[0] == "missing"
    # unversioned 且最近失败 → failed
    assert _compute_lifecycle_state("unversioned", [_Run("failed")])[0] == "failed"


def test_layer_asset_state_response_mapping() -> None:
    from app.api.routers.layer_router import _layer_asset_state_response

    resp = _layer_asset_state_response(
        "era5-dwaa-cn",
        {
            "layer_id": "era5-dwaa-cn",
            "asset_state": "fresh",
            "bake_version": 4,
            "current_bake_version": 4,
            "png_exists": True,
            "bounds_exists": True,
            "category": "static",
            "time_list": [],
            "default_time": None,
        },
    )
    assert resp.layer_id == "era5-dwaa-cn"
    assert resp.asset_state == "fresh"
    assert resp.bake_version == 4
    assert resp.current_bake_version == 4
    assert resp.png_exists is True
    assert resp.category == "static"
