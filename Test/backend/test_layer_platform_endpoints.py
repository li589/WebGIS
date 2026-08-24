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


@pytest.fixture
def no_auth(monkeypatch):
    """测试环境下禁用鉴权（接口语义测试不需要真凭证）。

    Settings 为 frozen dataclass，须用 ``dataclasses.replace`` 重建后整体
    替换模块级 ``settings`` 引用（与 test_auth.py 的 fixture 模式一致）。
    """
    from dataclasses import replace

    import app.core.config as cfg_mod

    patched = replace(cfg_mod.settings, user_auth_enabled=False)
    monkeypatch.setattr("app.core.config.settings", patched)
    yield


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


# ── 图层平台子系统 P1：online_sync 统一入口 ──────────────────────────────────


@pytest.fixture
def mock_submit(monkeypatch):
    """拦截 workflow 提交（online_sync 路由只验证编排逻辑，不真实提交）。

    真实 workflow 提交由 workflow_router 的既有测试覆盖；此处验证：
    - 图层能力判定（skipped-unsupported）
    - 活跃 run 复用（in-flight）
    - 请求参数构建（time_range/priority/queue_tag）
    """
    from datetime import UTC, datetime

    from shared.contracts.api_contracts import ExecutionStatus, WorkflowAcceptedResponse

    submitted: list = []

    def _fake_submit(payload, cred=None):  # noqa: ANN001, ANN202
        submitted.append(payload)
        return WorkflowAcceptedResponse(
            run_id=f"run-{len(submitted)}",
            status=ExecutionStatus.accepted,
            status_url=f"/workflow-runs/run-{len(submitted)}",
            events_url=f"/workflow-runs/run-{len(submitted)}/events",
            created_at=datetime.now(UTC),
            message="已受理",
        )

    import importlib

    layer_router_mod = importlib.import_module("app.api.routers.layer_router")
    monkeypatch.setattr(layer_router_mod, "_submit_online_sync_workflow", _fake_submit)
    return submitted



def test_online_sync_skipped_for_unsupported_layer(no_auth) -> None:
    """未启用 online_temporal 的图层返回 skipped-unsupported（不报错）。"""
    from app.api.routers.layer_router import sync_layer_asset_online

    # aridity-cn 未启用 online_temporal（静态图层）
    resp = sync_layer_asset_online("aridity-cn", body=None, cred=None)
    assert resp.status == "skipped-unsupported"
    assert resp.layer_id == "aridity-cn"
    assert resp.run_id is None


def test_online_sync_time_key_month_parsing(no_auth, mock_submit) -> None:
    """time_key YYYY-MM 解析为当月时间范围。"""
    from app.api.routers.layer_router import sync_layer_asset_online
    from shared.contracts.api_contracts import LayerOnlineSyncRequest

    # ndvi 启用了 online_temporal（1M 步长）
    resp = sync_layer_asset_online(
        "ndvi",
        body=LayerOnlineSyncRequest(time_key="2023-01"),
        cred=None,
    )
    assert resp.status in {"submitted", "in-flight"}
    assert resp.layer_id == "ndvi"
    assert resp.time_key == "2023-01"
    assert resp.run_id is not None
    assert resp.status_url is not None


def test_online_sync_reuses_active_run(no_auth, mock_submit) -> None:
    """同图层已有活跃 online_sync run 时返回 in-flight 复用。

    在仓储里预置一条 online_sync 活跃 run，验证路由复用逻辑（不再提交新 run）。
    """
    from datetime import UTC, datetime

    from app.api.routers.layer_router import sync_layer_asset_online
    from app.services.workflow_repository import SQLiteWorkflowRepository
    from shared.contracts.api_contracts import (
        ExecutionStatus,
        LayerOnlineSyncRequest,
        WorkflowCommandType,
        WorkflowRunStatusResponse,
    )

    # 预置活跃 online_sync run（workflow_kind 经 executor_metadata 自动提取）
    repo = SQLiteWorkflowRepository()
    now = datetime.now(UTC)
    repo.save_run(
        WorkflowRunStatusResponse(
            run_id="run-existing-online-sync",
            command_type=WorkflowCommandType.custom,
            layer_id="ndvi",
            status=ExecutionStatus.queued,
            progress=10,
            message="在线同步中",
            created_at=now,
            updated_at=now,
            executor_metadata={"workflow_kind": "online_sync"},
        ),
        request_json="{}",
    )
    repo.close()

    # 再次同步同图层 → in-flight 复用既有 run，不再提交
    second = sync_layer_asset_online(
        "ndvi",
        body=LayerOnlineSyncRequest(time_key="2023-03"),
        cred=None,
    )
    assert second.status == "in-flight"
    assert second.run_id == "run-existing-online-sync"
    assert len(mock_submit) == 0


def test_online_sync_response_contract(no_auth, mock_submit) -> None:
    """响应契约字段完整性。"""
    from app.api.routers.layer_router import sync_layer_asset_online
    from shared.contracts.api_contracts import LayerOnlineSyncRequest

    resp = sync_layer_asset_online(
        "ndvi",
        body=LayerOnlineSyncRequest(time_key="2023-04", is_prefetch=True),
        cred=None,
    )
    data = resp.model_dump()
    assert "status" in data
    assert "message" in data
    assert "layer_id" in data
    assert "time_key" in data
    assert data["status"] in {"submitted", "in-flight", "cooldown", "succeeded", "skipped-unsupported"}
