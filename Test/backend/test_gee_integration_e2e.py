"""GEE (Google Earth Engine) 端到端集成与安全验证测试。

覆盖维度：
1. GEE 账号管理 API 路由鉴权与安全门禁 (require_gee_account_management_enabled + require_config_management_access)
2. 账号完整生命周期 CRUD 操作与脱敏保障 (client_email 保留，private_key 绝不回显)
3. 凭据测试与重载端点安全性
4. GEE 运行态配置与并发限制接口 (/gee/config, /gee/config/limits, /gee/config/status)
5. GEE 在线数据源统一凭据状态报告 (/config/online-sources)
6. GeeBridgeService 桥接执行引擎工作流生命周期
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from app.core.config import settings
from app.main import create_app
from fastapi.testclient import TestClient
from shared.contracts.api_contracts import (
    GeeWorkflowRequest,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowSubmitRequest,
)


@pytest.fixture
def base_sa_payload() -> dict[str, Any]:
    return {
        "account_id": "test_e2e_gee_account",
        "service_account_json": {
            "client_email": "gee-sa@my-e2e-project.iam.gserviceaccount.com",
            "private_key": "mock_sa_private_key_content_for_test",
            "private_key_id": "e2e_key_id_98765",
            "project_id": "my-e2e-project",
        },
        "display_name": "E2E GEE Test SA",
    }


@pytest.fixture
def admin_client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> TestClient:
    """具备 admin 角色且启用 GEE 账号管理的测试客户端。"""
    # 隔离 GEE 数据库路径到 tmp_path
    db_path = tmp_path / "gee_test_db.sqlite3"
    monkeypatch.setattr(
        "app.core.config.settings",
        replace(
            settings,
            api_key_role="admin",
            gee_api_account_management_enabled=True,
            gee_credentials_db_path=db_path,
        ),
    )
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "test-admin-key",
    )
    # 重置 GEE repository 缓存
    from app.services.config_gee_accounts import _get_gee_credentials_repository

    _get_gee_credentials_repository.cache_clear()

    return TestClient(create_app(), headers={"X-API-Key": "test-admin-key"})


@pytest.fixture
def standard_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """非 admin（standard 角色）客户端。"""
    monkeypatch.setattr(
        "app.core.config.settings",
        replace(settings, api_key_role="standard", gee_api_account_management_enabled=True),
    )
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "test-std-key",
    )
    return TestClient(create_app(), headers={"X-API-Key": "test-std-key"})


@pytest.fixture
def disabled_mgm_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """账号管理被禁用的客户端 (模拟生产环境默认行为)。"""
    monkeypatch.setattr(
        "app.core.config.settings",
        replace(settings, api_key_role="admin", gee_api_account_management_enabled=False),
    )
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "test-admin-key",
    )
    return TestClient(create_app(), headers={"X-API-Key": "test-admin-key"})


# ── 1. 安全门禁与鉴权拦截 ──────────────────────────────────────────────────


def test_gee_account_management_disabled_guard(disabled_mgm_client: TestClient, base_sa_payload):
    """验证当 gee_api_account_management_enabled=False 时，写操作被 403 严格拒绝。"""
    resp = disabled_mgm_client.post("/config/gee/accounts", json=base_sa_payload)
    assert resp.status_code == 403
    assert "GEE API account management is disabled" in resp.json()["detail"]

    # toggle 与 reload 同样受阻
    resp_toggle = disabled_mgm_client.put(
        "/config/gee/accounts/some_id/toggle", json={"enabled": False}
    )
    assert resp_toggle.status_code == 403

    resp_reload = disabled_mgm_client.post("/config/gee/accounts/reload")
    assert resp_reload.status_code == 403


def test_gee_accounts_requires_admin_for_mutations(
    standard_client: TestClient, base_sa_payload
):
    """验证标准用户（非 admin）尝试写入 GEE 账号时被拒绝 (403)。"""
    resp = standard_client.post("/config/gee/accounts", json=base_sa_payload)
    assert resp.status_code == 403


def test_gee_accounts_unauthenticated_rejected(base_sa_payload):
    """验证未提供鉴权信息的匿名请求被拒绝 (401)。"""
    anon = TestClient(create_app())
    resp = anon.get("/config/gee/accounts")
    assert resp.status_code == 401


# ── 2. 账号 CRUD 完整生命周期与脱敏验证 ─────────────────────────────────────


def test_gee_accounts_crud_lifecycle(admin_client: TestClient, base_sa_payload):
    """验证 GEE 账号的创建、列表查询、启用/禁用、脱敏以及删除。"""
    # 1. 校验输入验证：缺少必填字段 client_email 应当 400
    invalid_payload = {
        "account_id": "bad_sa",
        "service_account_json": {"private_key": "some-key", "private_key_id": "k1"},
    }
    resp = admin_client.post("/config/gee/accounts", json=invalid_payload)
    assert resp.status_code == 400
    assert "client_email" in resp.json()["detail"]

    # 2. 成功创建账号
    resp_create = admin_client.post("/config/gee/accounts", json=base_sa_payload)
    assert resp_create.status_code == 200
    item = resp_create.json()
    assert item["account_id"] == "test_e2e_gee_account"
    assert item["display_name"] == "E2E GEE Test SA"
    assert item["project_id"] == "my-e2e-project"
    assert item["enabled"] is True
    # 核心安全约束：脱敏保障，绝不泄露 private_key
    assert "private_key" not in item
    assert "credentials_encrypted" not in item

    # 3. GET 列表查询
    resp_list = admin_client.get("/config/gee/accounts")
    assert resp_list.status_code == 200
    accounts = resp_list.json()
    assert any(a["account_id"] == "test_e2e_gee_account" for a in accounts)

    # 4. 禁用账号
    resp_toggle = admin_client.put(
        "/config/gee/accounts/test_e2e_gee_account/toggle",
        json={"enabled": False},
    )
    assert resp_toggle.status_code == 200
    assert resp_toggle.json()["enabled"] is False

    # 5. 凭证测试（离线环境测试凭据优雅返回 failed，不崩溃）
    resp_test = admin_client.post(
        "/config/gee/accounts/test_e2e_gee_account/test"
    )
    assert resp_test.status_code == 200
    test_result = resp_test.json()
    assert "success" in test_result
    assert "message" in test_result

    # 6. 重载账户池
    resp_reload = admin_client.post("/config/gee/accounts/reload")
    assert resp_reload.status_code == 200
    reload_result = resp_reload.json()
    assert "account_count" in reload_result

    # 7. 删除账号
    resp_delete = admin_client.delete("/config/gee/accounts/test_e2e_gee_account")
    assert resp_delete.status_code == 200
    assert resp_delete.json()["deleted"] is True
    assert resp_delete.json()["account_id"] == "test_e2e_gee_account"

    # 8. 再次删除已不存在的账号应返回 404
    resp_delete_again = admin_client.delete("/config/gee/accounts/test_e2e_gee_account")
    assert resp_delete_again.status_code == 404


# ── 3. GEE 配置、状态与在线源接口 ──────────────────────────────────────────


def test_gee_config_and_status_endpoints(admin_client: TestClient):
    """验证 /gee/config, /gee/config/limits, /gee/config/status 正常返回结构化数据。"""
    # GET /gee/config
    resp_conf = admin_client.get("/gee/config")
    assert resp_conf.status_code == 200
    conf_data = resp_conf.json()
    assert "parallel_config" in conf_data
    assert "storage_backend" in conf_data
    assert "local_storage_root" in conf_data

    # GET /gee/config/limits
    resp_limits = admin_client.get("/gee/config/limits")
    assert resp_limits.status_code == 200
    limits_data = resp_limits.json()
    assert "export" in limits_data
    assert "upload" in limits_data
    assert "download" in limits_data

    # GET /gee/config/status
    resp_status = admin_client.get("/gee/config/status")
    assert resp_status.status_code == 200
    status_data = resp_status.json()
    assert "gee_available" in status_data
    assert "concurrency_stats" in status_data
    assert "task_limits" in status_data


def test_online_sources_reports_gee_status(admin_client: TestClient):
    """验证 /config/online-sources 正确包含 GEE 账号池凭据状态。"""
    resp = admin_client.get("/config/online-sources")
    assert resp.status_code == 200
    data = resp.json()
    gee_source = next((s for s in data["sources"] if s["source_id"] == "gee"), None)
    assert gee_source is not None
    assert gee_source["kind"] == "account_pool"
    assert "account_count" in gee_source
    assert "enabled_count" in gee_source


# ── 4. GeeBridgeService 桥接引擎执行验证 ────────────────────────────────────


def test_gee_bridge_service_workflow_lifecycle():
    """验证 GeeBridgeService 从请求支持检测到核心引擎调度的工作流全过程。"""
    from app.services.gee_bridge_service import GeeBridgeService

    bridge = GeeBridgeService()

    # 1. supports() 检查
    gee_req = GeeWorkflowRequest(
        workflow={
            "workflow_id": "test_e2e_wf",
            "nodes": [
                {"node_id": "node_lit", "node_type": "literal", "params": {"value": 100}},
                {"node_id": "node_id", "node_type": "identity"},
            ],
            "edges": [
                {
                    "source_node_id": "node_lit",
                    "source_port": "value",
                    "target_node_id": "node_id",
                    "target_port": "value",
                }
            ],
        }
    )
    submit_req = WorkflowSubmitRequest(
        workflow_id="test_e2e_wf",
        command_type=WorkflowCommandType.custom,
        priority=WorkflowPriority.normal,
        gee_request=gee_req,
    )

    assert bridge.supports(submit_req) is True

    # 2. execute() 执行 (真实调用 webgis_gee 执行 literal 节点)
    from datetime import UTC, datetime

    from shared.contracts.api_contracts import EventChannel, LogLevel, WorkflowEvent

    def _event_factory(channel="log", message="", progress=0, payload=None):
        return WorkflowEvent(
            event_id=f"evt-{channel}",
            run_id="run_e2e_001",
            channel=EventChannel(channel),
            level=LogLevel.info,
            message=message,
            created_at=datetime.now(UTC),
            progress=progress,
            payload=payload or {},
        )

    result = bridge.execute(
        run_id="run_e2e_001",
        payload=submit_req,
        requested_at=datetime.now(UTC),
        event_factory=_event_factory,
    )

    assert "GEE 工作流" in result.message
    assert result.result_dto["job_status"] == "completed"
    assert result.result_dto["workflow_entry_name"] == "test_e2e_wf"
