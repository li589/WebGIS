"""Auth boundary hardening regressions (timers admin, workflow owner, weather ACL, upload owner)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

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

    from dataclasses import replace

    import app.core.config as cfg_mod
    from app.core.config import Settings

    cfg_mod.settings = replace(
        Settings(),
        admin_username="testadmin",
        admin_password="test-pass-123",
        environment="test",
        api_key="test-api-key",
        api_keys_enabled=True,
        user_auth_enabled=True,
        data_root=str(tmp_path / "data"),
        workflow_state_dir=str(tmp_path / "state"),
        output_root=str(tmp_path / "out"),
    )
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)

    from app.services import user_repository as ur_mod
    from app.services.user_repository import UserRepository

    _db_path = tmp_path / "state" / "users.sqlite3"
    ur_mod._repo = UserRepository(_db_path)

    from app.services import permission_repository as pr_mod
    from app.services.permission_repository import PermissionRepository

    pr_mod._repo = PermissionRepository(_db_path)
    pr_mod.invalidate_access_cache()

    from app.main import create_app
    from app.services.auth_bootstrap import bootstrap_auth
    from app.services.config_service import (
        _get_api_keys_repository,
        _get_effective_api_key_cached,
    )
    from app.services.effective_config import hydrate_effective_config

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
    _get_effective_api_key_cached.cache_clear()
    hydrate_effective_config()

    app = create_app()
    with TestClient(app) as client:
        yield client

    pr_mod._repo = None
    pr_mod.invalidate_access_cache()


def _login(client: TestClient, username: str, password: str) -> None:
    client.post("/auth/logout")
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text


def _admin_login(client: TestClient) -> None:
    _login(client, "testadmin", "test-pass-123")


def _create_standard(client: TestClient, username: str) -> None:
    _admin_login(client)
    resp = client.post(
        "/auth/users",
        json={"username": username, "password": "user-pass-123", "role": "standard"},
    )
    assert resp.status_code in (201, 409), resp.text
    _login(client, username, "user-pass-123")


def test_workflow_definition_owner_blocks_peer_mutation(auth_client: TestClient) -> None:
    _create_standard(auth_client, "alice")
    create = auth_client.post(
        "/workflow-definitions",
        json={
            "workflow_id": "wf-alice-owned",
            "name": "Alice WF",
            "engine": "common",
            "nodes": [],
            "links": [],
        },
    )
    assert create.status_code == 201, create.text
    meta = create.json().get("_meta") or {}
    assert meta.get("owner_user_id") is not None

    _create_standard(auth_client, "bob")
    put = auth_client.put(
        "/workflow-definitions/wf-alice-owned",
        json={"name": "Hijacked"},
    )
    assert put.status_code == 403, put.text
    delete = auth_client.delete("/workflow-definitions/wf-alice-owned")
    assert delete.status_code == 403, delete.text

    _admin_login(auth_client)
    put_admin = auth_client.put(
        "/workflow-definitions/wf-alice-owned",
        json={"name": "Admin rename"},
    )
    assert put_admin.status_code == 200, put_admin.text


def test_weather_tile_requires_auth_and_layer_acl(auth_client: TestClient) -> None:
    # Anonymous fail-closed
    anon = auth_client.get("/weather/tiles/wind-field/0/0/0")
    assert anon.status_code in (401, 403), anon.text

    _create_standard(auth_client, "alice")
    from app.services.permission_repository import (
        PermissionInput,
        get_permission_repository,
    )

    me = auth_client.get("/auth/me")
    assert me.status_code == 200, me.text
    alice_id = int(me.json()["id"])
    repo = get_permission_repository()
    repo.set_permission_mode(alice_id, "whitelist")
    repo.set_user_permissions(alice_id, [])  # empty whitelist → deny all
    denied = auth_client.get("/weather/tiles/wind-field/0/0/0")
    assert denied.status_code == 403, denied.text

    repo.set_user_permissions(
        alice_id,
        [
            PermissionInput(
                resource_type="layer", resource_id="wind-field", permission="allow"
            )
        ],
    )
    with patch("app.api.weather_tile_routes.get_weather_tile_service") as mock_svc:
        svc = mock_svc.return_value
        svc.get_tile = AsyncMock(
            return_value=({"type": "FeatureCollection", "features": []}, "MISS")
        )
        allowed = auth_client.get("/weather/tiles/wind-field/0/0/0")
    assert allowed.status_code == 200, allowed.text


def test_upload_owner_isolation(auth_client: TestClient) -> None:
    _create_standard(auth_client, "alice")
    init = auth_client.post(
        "/import/upload/init",
        json={
            "filename": "a.tif",
            "size": 4,
            "content_type": "image/tiff",
        },
    )
    assert init.status_code == 200, init.text
    upload_id = init.json()["upload_id"]

    _create_standard(auth_client, "bob")
    status = auth_client.get(f"/import/upload/{upload_id}/status")
    assert status.status_code == 404, status.text
    discard = auth_client.delete(f"/import/upload/{upload_id}")
    assert discard.status_code == 404, discard.text

    _login(auth_client, "alice", "user-pass-123")
    ok = auth_client.get(f"/import/upload/{upload_id}/status")
    assert ok.status_code == 200, ok.text


def test_acl_cache_generation_cross_process_signal(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    from dataclasses import replace

    import app.core.config as cfg_mod
    from app.core.config import Settings
    from app.services import permission_repository as pr_mod
    from app.services.permission_repository import (
        PermissionRepository,
        _access_cache,
        _cache_get,
        _cache_set,
        invalidate_access_cache,
    )

    cfg_mod.settings = replace(
        Settings(),
        environment="test",
        workflow_state_dir=str(tmp_path / "state"),
    )
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)
    db = tmp_path / "state" / "users.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    repo = PermissionRepository(db)
    pr_mod._repo = repo

    try:
        _cache_set((1, "layer", "wind-field"), True)
        assert _cache_get((1, "layer", "wind-field")) is True
        # Simulate another worker bumping generation
        pr_mod._local_cache_generation = -1
        invalidate_access_cache(None)
        assert _cache_get((1, "layer", "wind-field")) is None
        assert (1, "layer", "wind-field") not in _access_cache
    finally:
        repo.close()
        pr_mod._repo = None
        invalidate_access_cache(None)


def test_can_mutate_user_definition_unit() -> None:
    from app.services.workflow_definition_service import can_mutate_user_definition

    assert can_mutate_user_definition(
        {"kind": "user", "owner_user_id": 2}, role="admin", user_id=9
    )
    assert can_mutate_user_definition(
        {"kind": "user", "owner_user_id": 2}, role="standard", user_id=2
    )
    assert not can_mutate_user_definition(
        {"kind": "user", "owner_user_id": 2}, role="standard", user_id=3
    )
    assert not can_mutate_user_definition(
        {"kind": "user"}, role="standard", user_id=2
    )
    assert not can_mutate_user_definition(
        {"kind": "system", "readonly": True}, role="standard", user_id=2
    )
