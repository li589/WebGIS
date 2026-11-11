# -*- coding: utf-8 -*-
"""游客会话历史越权隔离（2026-11-10 老师实测 P0）。

「以游客身份进入」= 所有人共用同一个 demo 账号，服务端拿不到「人」维度。
旧实现 ``/agent/sessions`` 用 ``cred.user_id`` 列会话，于是所有游客共用同一个
demo user_id，列表/读取/删除都会互相越权（能看到别人的查询全文）。

修复：游客（demo/guest 角色，或无有效会话）对历史会话三接口一律返回空 / 404；
已登录（admin/standard）不受影响。
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_USER_AUTH_ENABLED", "true")
    monkeypatch.setenv("BACKEND_ADMIN_USERNAME", "testadmin")
    monkeypatch.setenv("BACKEND_ADMIN_PASSWORD", "test-pass-123")
    monkeypatch.setenv("BACKEND_API_KEY", "test-api-key")
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "true")
    monkeypatch.setenv("BACKEND_API_KEY_ROLE", "standard")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BACKEND_DEV_AUTH_PREFILL", "false")

    import app.core.config as cfg_mod
    from dataclasses import replace
    from app.core.config import Settings

    cfg_mod.settings = replace(
        Settings(),
        admin_username="testadmin",
        admin_password="test-pass-123",
        environment="test",
        api_key="test-api-key",
        api_keys_enabled=True,
        api_key_role="standard",
        user_auth_enabled=True,
        data_root=str(tmp_path / "data"),
        workflow_state_dir=str(tmp_path / "state"),
        output_root=str(tmp_path / "out"),
    )
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)

    from app.services import user_repository as ur_mod
    from app.services.user_repository import UserRepository

    repo = UserRepository(tmp_path / "state" / "users.sqlite3")

    from app.main import create_app
    from app.services.auth_bootstrap import bootstrap_auth
    from app.services.config_service import (
        _get_api_keys_repository,
        _get_effective_api_key_cached,
    )
    from app.services.effective_config import hydrate_effective_config

    with patch.object(ur_mod, "_repo", repo):
        hydrate_effective_config()
        bootstrap_auth()
        # standard 实名账号 + demo 共享游客账号
        repo.create_user(username="stduser", password="std-pass-123", role="standard")
        repo.create_user(username="demouser", password="demo-pass-123", role="demo")
        _get_api_keys_repository().upsert_key(
            key_name="backend_auth",
            key_value="test-api-key",
            display_name="Test backend auth",
            description="pytest fixture",
            history_source="test",
            archive_previous=False,
        )
        _get_effective_api_key_cached.cache_clear()
        hydrate_effective_config()

        with TestClient(create_app()) as c:
            yield c


def _login(c: TestClient, username: str, password: str) -> None:
    res = c.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text


def test_guest_cannot_list_sessions(client: TestClient):
    """游客列表接口必须返回空，不能看到共享 demo 桶里其他人的会话。"""
    _login(client, "demouser", "demo-pass-123")
    # 先以实名账号造一条会话，确认 demo 桶里其实有数据
    _login(client, "stduser", "std-pass-123")
    r = client.post(
        "/agent/chat",
        json={"message": "有哪些活动图层", "session_id": "sess-std-1"},
    )
    assert r.status_code == 200, r.text

    # 切回游客
    _login(client, "demouser", "demo-pass-123")
    listed = client.get("/agent/sessions")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["count"] == 0
    assert body["sessions"] == []


def test_guest_cannot_get_session(client: TestClient):
    _login(client, "demouser", "demo-pass-123")
    got = client.get("/agent/sessions/whatever-id")
    assert got.status_code == 404


def test_guest_cannot_delete_session(client: TestClient):
    _login(client, "demouser", "demo-pass-123")
    deleted = client.delete("/agent/sessions/whatever-id")
    assert deleted.status_code == 404


def test_standard_can_still_use_sessions(client: TestClient):
    """实名账号的历史会话功能不受影响。"""
    _login(client, "stduser", "std-pass-123")
    r = client.post(
        "/agent/chat",
        json={"message": "有哪些活动图层", "session_id": "sess-std-2"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    listed = client.get("/agent/sessions")
    assert listed.status_code == 200
    assert any(s["session_id"] == sid for s in listed.json()["sessions"])

    got = client.get(f"/agent/sessions/{sid}")
    assert got.status_code == 200
    assert got.json()["session_id"] == sid
