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
    # 模板路径直接调用 workflow_router.submit_workflow（模块级 import），
    # 需同时拦截（run_workflow_template 内部 from-import 会绑定到 patch 后的对象）
    wf_router_mod = importlib.import_module("app.api.routers.workflow_router")
    monkeypatch.setattr(wf_router_mod, "submit_workflow", _fake_submit)
    return submitted


def _clear_active_online_sync_runs(layer_id: str) -> None:
    """物理清理测试仓储中残留的 online_sync run（仓储跨测试轮次持久，
    reuses 预置的 queued run 会让后续轮次的 parsing 测试误入复用分支；
    不可用 save_run 覆写成 cancelled——终态守卫会拦截后续同 run_id 预置）。"""
    from app.services.workflow_repository import SQLiteWorkflowRepository

    repo = SQLiteWorkflowRepository()
    with repo._connect() as connection:  # noqa: SLF001 - 测试专用物理清理
        connection.execute(
            "DELETE FROM workflow_runs WHERE layer_id = ? AND workflow_kind = ?",
            (layer_id, "online_sync"),
        )
    repo.close()



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
    _clear_active_online_sync_runs("ndvi")
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
    # P1 遗留修复：analysis 类型（submission normalize 才会填充 engine request）
    assert mock_submit[0].command_type.value == "analysis"


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

    # 预置活跃 online_sync run（唯一 run_id：防跨轮残留 + 终态守卫拦截覆盖）
    import uuid as _uuid

    preset_run_id = f"run-existing-online-sync-{_uuid.uuid4().hex[:8]}"
    repo = SQLiteWorkflowRepository()
    now = datetime.now(UTC)
    repo.save_run(
        WorkflowRunStatusResponse(
            run_id=preset_run_id,
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
    assert second.run_id == preset_run_id
    assert len(mock_submit) == 0


def test_online_sync_response_contract(no_auth, mock_submit) -> None:
    """响应契约字段完整性。"""
    from app.api.routers.layer_router import sync_layer_asset_online
    from shared.contracts.api_contracts import LayerOnlineSyncRequest

    _clear_active_online_sync_runs("ndvi")
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


# ── 图层平台子系统 P1：课题组工作流模板一键显示 ───────────────────────────────


def test_list_workflow_templates_filters_templates(no_auth) -> None:
    """模板列表只返回 is_template=true 或 tags 含 template/lab 的定义。"""
    from app.api.routers.layer_router import list_workflow_templates

    resp = list_workflow_templates(cred=None)
    assert isinstance(resp.count, int)
    # 系统种子中默认无 is_template 标记，列表可能为空——契约完整性即可
    for item in resp.items:
        assert item.is_template is True or any(
            t in {"template", "lab", "课题组"} for t in item.tags
        )


def test_run_workflow_template_not_found(no_auth) -> None:
    """未知模板 id 返回 404。"""
    import pytest
    from fastapi import HTTPException

    from app.api.routers.layer_router import run_workflow_template

    with pytest.raises(HTTPException) as ctx:
        run_workflow_template("no-such-template-xyz", body=None, cred=None)
    assert ctx.value.status_code == 404


def test_run_workflow_template_builds_payload(no_auth, mock_submit, monkeypatch) -> None:
    """模板运行构建 WorkflowSubmitRequest（workflow_kind=lab_template）。"""
    from app.api.routers.layer_router import run_workflow_template
    from shared.contracts.api_contracts import WorkflowTemplateRunRequest

    # 造一个临时模板定义（patch get_definition）
    fake_def = {
        "workflow_id": "lab.test",
        "_meta": {
            "name": "测试模板",
            "linked_layer_id": "aridity-cn",
            "auto_display": True,
            "resource_profile": "heavy",
            "is_template": True,
        },
    }
    import app.services.workflow_definition_service as wds

    monkeypatch.setattr(wds, "get_definition", lambda _id: fake_def)

    resp = run_workflow_template(
        "lab.test",
        body=WorkflowTemplateRunRequest(parameters={"region": "cn"}),
        cred=None,
    )
    assert resp.status == "submitted"
    assert resp.workflow_id == "lab.test"
    assert resp.linked_layer_id == "aridity-cn"
    assert resp.auto_display is True

    assert len(mock_submit) == 1
    payload = mock_submit[0]
    # P1 遗留修复：analysis 类型 + workflow_name 入口（custom 会 no bridge）
    assert payload.command_type.value == "analysis"
    ar = payload.algorithm_request
    ar_dict = ar if isinstance(ar, dict) else ar.model_dump()
    assert ar_dict["workflow_name"] == "lab.test"
    assert ar_dict["algorithm_params"]["region"] == "cn"
    assert payload.parameters["workflow_kind"] == "lab_template"
    assert payload.parameters["workflow_template_id"] == "lab.test"
    assert payload.parameters["region"] == "cn"
    assert payload.layer_id == "aridity-cn"
    assert payload.resource_profile.value == "heavy"


def test_run_workflow_template_overrides(no_auth, mock_submit, monkeypatch) -> None:
    """请求可覆盖模板默认 resource_profile 与 auto_display。"""
    from app.api.routers.layer_router import run_workflow_template
    from shared.contracts.api_contracts import WorkflowTemplateRunRequest

    fake_def = {
        "workflow_id": "lab.override",
        "_meta": {
            "name": "覆盖测试",
            "linked_layer_id": "ndvi",
            "auto_display": True,
            "resource_profile": "batch",
            "is_template": True,
        },
    }
    import app.services.workflow_definition_service as wds

    monkeypatch.setattr(wds, "get_definition", lambda _id: fake_def)

    resp = run_workflow_template(
        "lab.override",
        body=WorkflowTemplateRunRequest(
            resource_profile="realtime", auto_display=False
        ),
        cred=None,
    )
    assert resp.auto_display is False
    assert mock_submit[0].resource_profile.value == "light"
    assert mock_submit[0].parameters["auto_display"] is False


# ── 2026-08-25 反馈修复：无烘焙任务图层的资产工作流语义 ───────────────────────


def _make_asset_service_run(repo, layer_id: str) -> str:
    """在仓储中预置一条 accepted 状态的资产 run，返回 run_id。"""
    from datetime import UTC, datetime

    from shared.contracts.api_contracts import (
        ExecutionStatus,
        WorkflowCommandType,
        WorkflowRunStatusResponse,
    )

    run_id = f"asset-bake-test-{layer_id}"
    now = datetime.now(UTC)
    repo.save_run(
        WorkflowRunStatusResponse(
            run_id=run_id,
            command_type=WorkflowCommandType.custom,
            command_label="图层资产检查",
            layer_id=layer_id,
            status=ExecutionStatus.accepted,
            progress=0,
            message="已受理",
            created_at=now,
            updated_at=now,
        ),
        request_json="{}",
        run_class="asset",
        workflow_kind="asset_bake",
    )
    return run_id


def test_asset_workflow_no_task_with_files_succeeds(monkeypatch) -> None:
    """无烘焙任务但 PNG/bounds 存在 → succeeded（按现状显示，不报失败）。"""
    from app.services import overlay_asset_workflow_service as svc
    from app.services.overlay_asset_workflow_service import (
        OverlayAssetWorkflowService,
    )
    from app.services.workflow_repository import SQLiteWorkflowRepository

    # smap-aux-koppen（柯本）不在 _LAYER_TO_TASK 中
    monkeypatch.setattr(
        svc,
        "_read_asset_state",
        lambda layer_id: {
            "layer_id": layer_id,
            "png_exists": True,
            "bounds_exists": True,
            "bake_version": None,
            "asset_state": "stale",
        },
    )
    repo = SQLiteWorkflowRepository()
    run_id = _make_asset_service_run(repo, "smap-aux-koppen")
    try:
        service = OverlayAssetWorkflowService(repository=repo)
        result = service.run_asset_workflow(run_id)
        assert result["status"] == "succeeded"
        run = repo.get_run(run_id)
        assert run is not None
        assert run.status.value == "succeeded"
        assert "按现状显示" in (run.message or "")
    finally:
        repo.close()


def test_asset_workflow_no_task_missing_files_fails(monkeypatch) -> None:
    """无烘焙任务且资产文件缺失 → failed（真缺资产才报失败）。"""
    from app.services import overlay_asset_workflow_service as svc
    from app.services.overlay_asset_workflow_service import (
        OverlayAssetWorkflowService,
    )
    from app.services.workflow_repository import SQLiteWorkflowRepository

    monkeypatch.setattr(
        svc,
        "_read_asset_state",
        lambda layer_id: {
            "layer_id": layer_id,
            "png_exists": False,
            "bounds_exists": False,
            "bake_version": None,
            "asset_state": "missing",
        },
    )
    repo = SQLiteWorkflowRepository()
    run_id = _make_asset_service_run(repo, "smap-aux-koppen")
    try:
        service = OverlayAssetWorkflowService(repository=repo)
        result = service.run_asset_workflow(run_id)
        assert result["status"] == "failed"
        run = repo.get_run(run_id)
        assert run is not None
        assert run.status.value == "failed"
        assert "资产文件缺失" in (run.message or "")
    finally:
        repo.close()
