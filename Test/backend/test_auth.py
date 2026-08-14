"""User login, session cookies, and account management tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_CODE_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PROVIDER = _CODE_ROOT / "algorithms" / "providers" / "Python"
for _p in (_PYTHON_PROVIDER, _CODE_ROOT):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
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
    )
    # 确保直接赋值在 fixture 结束后恢复（monkeypatch 不追踪直接赋值）。
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)
    from app.services import user_repository as ur_mod
    from app.services.user_repository import UserRepository

    # P2-12: 使用 patch.object 替代直接赋值，确保测试结束后自动恢复原始 _repo
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
        _get_api_keys_repository().upsert_key(
            key_name="backend_auth",
            key_value="test-api-key",
            display_name="Test backend auth",
            description="pytest fixture",
            history_source="test",
            archive_previous=False,
        )
        # upsert 不自动失效 _get_effective_api_key_cached 的 lru_cache；
        # 跨测试污染（如 test_api_keys_basemap 的 cache_clear）会使 hydrate 读到旧 backend_auth。
        _get_effective_api_key_cached.cache_clear()
        hydrate_effective_config()

        with TestClient(create_app()) as client:
            yield client


def _login(client: TestClient, username: str, password: str) -> None:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text


def test_login_and_session_write_access(auth_client: TestClient):
    _login(auth_client, "testadmin", "test-pass-123")
    assert auth_client.cookies.get("cgda_session")

    me = auth_client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "testadmin"

    resp = auth_client.get("/config/api-keys")
    assert resp.status_code == 200

    logout = auth_client.post("/auth/logout")
    assert logout.status_code == 204
    assert auth_client.get("/auth/me").status_code == 401


def test_invalid_login(auth_client: TestClient):
    resp = auth_client.post(
        "/auth/login",
        json={"username": "testadmin", "password": "wrong"},
    )
    assert resp.status_code == 401


def test_admin_user_crud(auth_client: TestClient):
    _login(auth_client, "testadmin", "test-pass-123")
    created = auth_client.post(
        "/auth/users",
        json={
            "username": "operator1",
            "password": "operator-pass",
            "role": "standard",
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    listed = auth_client.get("/auth/users")
    assert listed.status_code == 200
    assert any(u["username"] == "operator1" for u in listed.json())

    updated = auth_client.patch(
        f"/auth/users/{user_id}",
        json={"role": "demo", "enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["role"] == "demo"
    assert updated.json()["enabled"] is False

    deleted = auth_client.delete(f"/auth/users/{user_id}")
    assert deleted.status_code == 204


def test_viewer_cannot_write(auth_client: TestClient):
    _login(auth_client, "testadmin", "test-pass-123")
    created = auth_client.post(
        "/auth/users",
        json={"username": "viewer1", "password": "viewer-pass", "role": "demo"},
    )
    assert created.status_code == 201

    auth_client.post("/auth/logout")
    _login(auth_client, "viewer1", "viewer-pass")

    resp = auth_client.post("/weather/sync/trigger", json={})
    assert resp.status_code == 403


def test_role_change_revokes_session(auth_client: TestClient):
    _login(auth_client, "testadmin", "test-pass-123")
    created = auth_client.post(
        "/auth/users",
        json={"username": "op2", "password": "operator-pass", "role": "standard"},
    )
    user_id = created.json()["id"]

    operator_client = TestClient(auth_client.app)
    _login(operator_client, "op2", "operator-pass")

    auth_client.patch(f"/auth/users/{user_id}", json={"role": "demo"})

    resp = operator_client.post("/weather/sync/trigger", json={})
    assert resp.status_code == 401


def test_user_api_token_inherits_role(auth_client: TestClient):
    _login(auth_client, "testadmin", "test-pass-123")
    created = auth_client.post(
        "/auth/users",
        json={"username": "viewer2", "password": "viewer-pass", "role": "demo"},
    )
    viewer_id = created.json()["id"]
    token_resp = auth_client.post(
        "/auth/tokens",
        json={"user_id": viewer_id, "label": "viewer-token"},
    )
    assert token_resp.status_code == 201
    plain = token_resp.json()["token"]

    auth_client.post("/auth/logout")
    resp = auth_client.post(
        "/weather/sync/trigger",
        json={},
        headers={"X-API-Key": plain},
    )
    assert resp.status_code == 403


def test_service_key_role_operator(auth_client: TestClient):
    auth_client.post("/auth/logout")
    resp = auth_client.post(
        "/weather/sync/trigger",
        json={},
        headers={"X-API-Key": "test-api-key"},
    )
    assert resp.status_code in {200, 409, 503}


def test_last_admin_protection(auth_client: TestClient):
    _login(auth_client, "testadmin", "test-pass-123")
    me = auth_client.get("/auth/me").json()
    resp = auth_client.patch(
        f"/auth/users/{me['id']}",
        json={"role": "standard"},
    )
    assert resp.status_code == 400


def test_auth_config_dev_prefill(monkeypatch, tmp_path):
    from dataclasses import replace

    from app.api.routers import auth_router
    from app.core.config import settings
    from app.services import user_repository as ur_mod
    from app.services.user_repository import UserRepository

    # 确保使用干净的 _repo，避免前序 auth_client fixture 的 testadmin 用户残留。
    clean_repo = UserRepository(tmp_path / "dev_prefill_state" / "users.sqlite3")
    monkeypatch.setattr(ur_mod, "_repo", clean_repo)

    patched = replace(
        settings,
        environment="development",
        dev_auth_prefill=True,
        admin_username="admin",
        admin_password="cgda-dev-admin",
        dev_default_api_key="cgda-dev-write-key",
    )
    monkeypatch.setattr("app.core.config.settings", patched)
    monkeypatch.setattr(auth_router, "settings", patched)
    monkeypatch.setattr(
        auth_router,
        "_direct_client_host",
        lambda _request: "127.0.0.1",
    )

    from app.main import create_app

    with TestClient(create_app()) as client:
        resp = client.get("/auth/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_required"] is True
    assert body["dev_prefill"]["username"] == "admin"
    assert body["dev_write_api_key"] == "cgda-dev-write-key"
