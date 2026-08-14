"""Phase B: Resource permission management tests.

Covers PermissionRepository CRUD, access-check logic (open/whitelist),
API endpoints, and integration with layer listing / workflow definitions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_CODE_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PROVIDER = _CODE_ROOT / "algorithms" / "providers" / "Python"
for _p in (_PYTHON_PROVIDER, _CODE_ROOT):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    )
    from app.services import user_repository as ur_mod
    from app.services.user_repository import UserRepository

    _db_path = tmp_path / "state" / "users.sqlite3"
    ur_mod._repo = UserRepository(_db_path)

    # Explicitly set permission repository singleton to use the same temp DB.
    # Setting _repo=None would cause get_permission_repository() to create a
    # new instance via _users_db_path(), which may not resolve to the same
    # path if Settings didn't pick up the BACKEND_WORKFLOW_STATE_DIR env var.
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

    with TestClient(create_app()) as client:
        yield client

    # Cleanup
    pr_mod._repo = None
    pr_mod.invalidate_access_cache()


def _login(client: TestClient, username: str, password: str) -> None:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text


def _create_user(client: TestClient, username: str, role: str = "standard") -> dict:
    """Create a user via admin API and return the user dict."""
    resp = client.post(
        "/auth/users",
        json={"username": username, "password": "user-pass-123", "role": role},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _login_as(client: TestClient, username: str) -> None:
    """Logout current session and login as a different user."""
    client.post("/auth/logout")
    _login(client, username, "user-pass-123")


# ---------------------------------------------------------------------------
# PermissionRepository unit tests
# ---------------------------------------------------------------------------


def test_permission_repository_crud(tmp_path, monkeypatch):
    """Test CRUD operations on PermissionRepository."""
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    from app.services.user_repository import UserRepository
    from app.services.permission_repository import (
        PermissionRepository,
        PermissionInput,
        invalidate_access_cache,
    )

    # Setup
    ur = UserRepository(tmp_path / "state" / "users.sqlite3")
    user = ur.create_user(username="testuser", password="pass-12345", role="standard")
    user_id = int(user["id"])

    repo = PermissionRepository(tmp_path / "state" / "users.sqlite3")
    invalidate_access_cache()

    # Initially no permissions
    assert repo.get_user_permissions(user_id) == []

    # Set permissions
    perms = repo.set_user_permissions(
        user_id,
        [
            PermissionInput(resource_type="layer", resource_id="layer_1", permission="deny"),
            PermissionInput(resource_type="workflow", resource_id="wf_1", permission="allow"),
        ],
    )
    assert len(perms) == 2
    assert perms[0].resource_type == "layer"
    assert perms[0].resource_id == "layer_1"
    assert perms[0].permission == "deny"

    # Read back
    all_perms = repo.get_user_permissions(user_id)
    assert len(all_perms) == 2

    # Delete one
    first_id = all_perms[0].id
    assert repo.delete_permission(first_id) is True
    assert len(repo.get_user_permissions(user_id)) == 1
    # Delete non-existent
    assert repo.delete_permission(99999) is False

    # Replace all (set_user_permissions replaces)
    repo.set_user_permissions(
        user_id,
        [PermissionInput(resource_type="data_source", resource_id="/data/test", permission="deny")],
    )
    all_perms = repo.get_user_permissions(user_id)
    assert len(all_perms) == 1
    assert all_perms[0].resource_type == "data_source"

    invalidate_access_cache()
    repo.close()
    ur.close()


def test_permission_repository_access_check_open_mode(tmp_path, monkeypatch):
    """Test access check in open (black-list) mode."""
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    from app.services.user_repository import UserRepository
    from app.services.permission_repository import (
        PermissionRepository,
        PermissionInput,
        invalidate_access_cache,
    )

    ur = UserRepository(tmp_path / "state" / "users.sqlite3")
    user = ur.create_user(username="testuser", password="pass-12345", role="standard")
    user_id = int(user["id"])

    repo = PermissionRepository(tmp_path / "state" / "users.sqlite3")
    invalidate_access_cache()

    # Open mode (default): no deny record means allowed
    assert repo.get_permission_mode(user_id) == "open"
    assert repo.check_resource_access(user_id, "layer", "layer_1") is True

    # Add deny record
    repo.set_user_permissions(
        user_id,
        [PermissionInput(resource_type="layer", resource_id="layer_1", permission="deny")],
    )
    assert repo.check_resource_access(user_id, "layer", "layer_1") is False
    # Other layers still accessible
    assert repo.check_resource_access(user_id, "layer", "layer_2") is True

    invalidate_access_cache()
    repo.close()
    ur.close()


def test_permission_repository_access_check_whitelist_mode(tmp_path, monkeypatch):
    """Test access check in whitelist mode."""
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    from app.services.user_repository import UserRepository
    from app.services.permission_repository import (
        PermissionRepository,
        PermissionInput,
        invalidate_access_cache,
    )

    ur = UserRepository(tmp_path / "state" / "users.sqlite3")
    user = ur.create_user(username="testuser", password="pass-12345", role="standard")
    user_id = int(user["id"])

    repo = PermissionRepository(tmp_path / "state" / "users.sqlite3")
    invalidate_access_cache()

    # Switch to whitelist mode
    repo.set_permission_mode(user_id, "whitelist")
    assert repo.get_permission_mode(user_id) == "whitelist"

    # In whitelist mode: nothing is accessible without an allow record
    assert repo.check_resource_access(user_id, "layer", "layer_1") is False

    # Add allow record
    repo.set_user_permissions(
        user_id,
        [PermissionInput(resource_type="layer", resource_id="layer_1", permission="allow")],
    )
    assert repo.check_resource_access(user_id, "layer", "layer_1") is True
    # Other layers still not accessible
    assert repo.check_resource_access(user_id, "layer", "layer_2") is False

    invalidate_access_cache()
    repo.close()
    ur.close()


def test_permission_repository_batch_filter(tmp_path, monkeypatch):
    """Test batch_filter_accessible for efficient list filtering."""
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    from app.services.user_repository import UserRepository
    from app.services.permission_repository import (
        PermissionRepository,
        PermissionInput,
        invalidate_access_cache,
    )

    ur = UserRepository(tmp_path / "state" / "users.sqlite3")
    user = ur.create_user(username="testuser", password="pass-12345", role="standard")
    user_id = int(user["id"])

    repo = PermissionRepository(tmp_path / "state" / "users.sqlite3")
    invalidate_access_cache()

    # Deny layer_2 and layer_4 out of [layer_1..layer_5]
    repo.set_user_permissions(
        user_id,
        [
            PermissionInput(resource_type="layer", resource_id="layer_2", permission="deny"),
            PermissionInput(resource_type="layer", resource_id="layer_4", permission="deny"),
        ],
    )
    all_ids = [f"layer_{i}" for i in range(1, 6)]
    accessible = repo.batch_filter_accessible(user_id, "layer", all_ids)
    assert set(accessible) == {"layer_1", "layer_3", "layer_5"}

    # Empty list
    assert repo.batch_filter_accessible(user_id, "layer", []) == []

    invalidate_access_cache()
    repo.close()
    ur.close()


def test_permission_repository_cache_invalidation(tmp_path, monkeypatch):
    """Test that cache invalidation works after permission changes."""
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    from app.services.user_repository import UserRepository
    from app.services.permission_repository import (
        PermissionRepository,
        PermissionInput,
        invalidate_access_cache,
        _cache_get,
        _cache_set,
    )

    ur = UserRepository(tmp_path / "state" / "users.sqlite3")
    user = ur.create_user(username="testuser", password="pass-12345", role="standard")
    user_id = int(user["id"])

    repo = PermissionRepository(tmp_path / "state" / "users.sqlite3")
    invalidate_access_cache()

    # Check access (caches result)
    assert repo.check_resource_access(user_id, "layer", "layer_1") is True
    # Cache should have the result
    assert _cache_get((user_id, "layer", "layer_1")) is True

    # Add deny record — set_user_permissions should invalidate cache
    repo.set_user_permissions(
        user_id,
        [PermissionInput(resource_type="layer", resource_id="layer_1", permission="deny")],
    )
    # Cache should be cleared
    assert _cache_get((user_id, "layer", "layer_1")) is None
    # Re-check should return False
    assert repo.check_resource_access(user_id, "layer", "layer_1") is False

    invalidate_access_cache()
    repo.close()
    ur.close()


def test_permission_repository_invalid_inputs(tmp_path, monkeypatch):
    """Test that invalid inputs raise ValueError."""
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    from app.services.user_repository import UserRepository
    from app.services.permission_repository import (
        PermissionRepository,
        PermissionInput,
        invalidate_access_cache,
    )

    ur = UserRepository(tmp_path / "state" / "users.sqlite3")
    user = ur.create_user(username="testuser", password="pass-12345", role="standard")
    user_id = int(user["id"])

    repo = PermissionRepository(tmp_path / "state" / "users.sqlite3")
    invalidate_access_cache()

    # Invalid resource_type
    with pytest.raises(ValueError, match="invalid resource_type"):
        repo.set_user_permissions(
            user_id,
            [PermissionInput(resource_type="invalid", resource_id="x", permission="allow")],
        )

    # Invalid permission value
    with pytest.raises(ValueError, match="invalid permission"):
        repo.set_user_permissions(
            user_id,
            [PermissionInput(resource_type="layer", resource_id="x", permission="maybe")],
        )

    # Empty resource_id
    with pytest.raises(ValueError, match="resource_id is required"):
        repo.set_user_permissions(
            user_id,
            [PermissionInput(resource_type="layer", resource_id="  ", permission="allow")],
        )

    # Invalid permission mode
    with pytest.raises(ValueError, match="invalid permission_mode"):
        repo.set_permission_mode(user_id, "invalid_mode")

    invalidate_access_cache()
    repo.close()
    ur.close()


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


def test_api_list_permissions_empty(auth_client: TestClient):
    """GET /auth/users/{id}/permissions returns empty list for new user."""
    _login(auth_client, "testadmin", "test-pass-123")
    user = _create_user(auth_client, "standarduser", "standard")
    resp = auth_client.get(f"/auth/users/{user['id']}/permissions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_api_set_and_list_permissions(auth_client: TestClient):
    """PUT /auth/users/{id}/permissions sets and returns permissions."""
    _login(auth_client, "testadmin", "test-pass-123")
    user = _create_user(auth_client, "standarduser", "standard")

    resp = auth_client.put(
        f"/auth/users/{user['id']}/permissions",
        json={
            "permissions": [
                {"resource_type": "layer", "resource_id": "layer_1", "permission": "deny"},
                {"resource_type": "workflow", "resource_id": "wf_1", "permission": "allow"},
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    # Verify via GET
    resp = auth_client.get(f"/auth/users/{user['id']}/permissions")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_api_replace_permissions(auth_client: TestClient):
    """PUT replaces all permissions (not append)."""
    _login(auth_client, "testadmin", "test-pass-123")
    user = _create_user(auth_client, "standarduser", "standard")

    # Set initial permissions
    auth_client.put(
        f"/auth/users/{user['id']}/permissions",
        json={
            "permissions": [
                {"resource_type": "layer", "resource_id": "layer_1", "permission": "deny"},
                {"resource_type": "layer", "resource_id": "layer_2", "permission": "deny"},
            ]
        },
    )

    # Replace with different set
    resp = auth_client.put(
        f"/auth/users/{user['id']}/permissions",
        json={
            "permissions": [
                {"resource_type": "layer", "resource_id": "layer_3", "permission": "deny"},
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["resource_id"] == "layer_3"


def test_api_delete_permission(auth_client: TestClient):
    """DELETE /auth/users/{id}/permissions/{perm_id} removes a permission."""
    _login(auth_client, "testadmin", "test-pass-123")
    user = _create_user(auth_client, "standarduser", "standard")

    resp = auth_client.put(
        f"/auth/users/{user['id']}/permissions",
        json={
            "permissions": [
                {"resource_type": "layer", "resource_id": "layer_1", "permission": "deny"},
            ]
        },
    )
    perm_id = resp.json()[0]["id"]

    resp = auth_client.delete(f"/auth/users/{user['id']}/permissions/{perm_id}")
    assert resp.status_code == 204

    # Verify deleted
    resp = auth_client.get(f"/auth/users/{user['id']}/permissions")
    assert resp.json() == []


def test_api_delete_permission_not_found(auth_client: TestClient):
    """DELETE with non-existent permission_id returns 404."""
    _login(auth_client, "testadmin", "test-pass-123")
    user = _create_user(auth_client, "standarduser", "standard")
    resp = auth_client.delete(f"/auth/users/{user['id']}/permissions/99999")
    assert resp.status_code == 404


def test_api_update_permission_mode(auth_client: TestClient):
    """PATCH /auth/users/{id}/permission-mode switches mode."""
    _login(auth_client, "testadmin", "test-pass-123")
    user = _create_user(auth_client, "standarduser", "standard")

    resp = auth_client.patch(
        f"/auth/users/{user['id']}/permission-mode",
        json={"mode": "whitelist"},
    )
    assert resp.status_code == 200
    assert resp.json()["permission_mode"] == "whitelist"

    # Switch back
    resp = auth_client.patch(
        f"/auth/users/{user['id']}/permission-mode",
        json={"mode": "open"},
    )
    assert resp.status_code == 200
    assert resp.json()["permission_mode"] == "open"


def test_api_permissions_require_admin(auth_client: TestClient):
    """Non-admin users cannot manage permissions."""
    _login(auth_client, "testadmin", "test-pass-123")
    user = _create_user(auth_client, "standarduser", "standard")

    # Login as standard user
    _login_as(auth_client, "standarduser")

    # All permission endpoints should return 403
    resp = auth_client.get(f"/auth/users/{user['id']}/permissions")
    assert resp.status_code == 403

    resp = auth_client.put(
        f"/auth/users/{user['id']}/permissions",
        json={"permissions": []},
    )
    assert resp.status_code == 403


def test_api_permissions_user_not_found(auth_client: TestClient):
    """Permissions endpoints return 404 for non-existent user."""
    _login(auth_client, "testadmin", "test-pass-123")
    resp = auth_client.get("/auth/users/99999/permissions")
    assert resp.status_code == 404


def test_api_set_permissions_validation_error(auth_client: TestClient):
    """Invalid permission data returns 400."""
    _login(auth_client, "testadmin", "test-pass-123")
    user = _create_user(auth_client, "standarduser", "standard")

    # Invalid resource_type (Pydantic validation → 422)
    resp = auth_client.put(
        f"/auth/users/{user['id']}/permissions",
        json={
            "permissions": [
                {"resource_type": "invalid_type", "resource_id": "x", "permission": "allow"},
            ]
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_layer_listing_filtered_by_permissions(auth_client: TestClient):
    """GET /layers filters out denied layers for non-admin users."""
    _login(auth_client, "testadmin", "test-pass-123")
    user = _create_user(auth_client, "standarduser", "standard")

    # Get all layers as admin first
    admin_resp = auth_client.get("/layers")
    assert admin_resp.status_code == 200
    all_layers = admin_resp.json().get("items", [])
    if not all_layers:
        pytest.skip("No layers in catalog for this test environment")

    # Deny the first layer for the standard user
    first_layer_id = all_layers[0]["layer_id"]
    auth_client.put(
        f"/auth/users/{user['id']}/permissions",
        json={
            "permissions": [
                {"resource_type": "layer", "resource_id": first_layer_id, "permission": "deny"},
            ]
        },
    )

    # Login as standard user and fetch layers
    _login_as(auth_client, "standarduser")
    resp = auth_client.get("/layers")
    assert resp.status_code == 200
    visible_layers = resp.json().get("items", [])
    visible_ids = [l["layer_id"] for l in visible_layers]
    assert first_layer_id not in visible_ids


def test_layer_listing_not_filtered_for_admin(auth_client: TestClient):
    """Admin sees all layers regardless of permission records."""
    _login(auth_client, "testadmin", "test-pass-123")

    # Add a deny record for admin (should be ignored)
    me = auth_client.get("/auth/me").json()
    auth_client.put(
        f"/auth/users/{me['id']}/permissions",
        json={
            "permissions": [
                {"resource_type": "layer", "resource_id": "any_layer", "permission": "deny"},
            ]
        },
    )

    # Admin should still see all layers
    resp = auth_client.get("/layers")
    assert resp.status_code == 200
    # Should not be filtered
    assert len(resp.json().get("items", [])) > 0


def test_whitelist_mode_restricts_all_layers(auth_client: TestClient):
    """Whitelist mode without allow records hides all layers."""
    _login(auth_client, "testadmin", "test-pass-123")
    user = _create_user(auth_client, "standarduser", "standard")

    # Switch to whitelist mode without any allow records
    auth_client.patch(
        f"/auth/users/{user['id']}/permission-mode",
        json={"mode": "whitelist"},
    )

    _login_as(auth_client, "standarduser")
    resp = auth_client.get("/layers")
    assert resp.status_code == 200
    # In whitelist mode with no allow records, no layers should be visible
    assert resp.json().get("items", []) == []


def test_whitelist_mode_with_allow_record(auth_client: TestClient):
    """Whitelist mode with an allow record shows only that layer."""
    _login(auth_client, "testadmin", "test-pass-123")
    user = _create_user(auth_client, "standarduser", "standard")

    # Get a layer ID from admin view
    admin_resp = auth_client.get("/layers")
    all_layers = admin_resp.json().get("items", [])
    if not all_layers:
        pytest.skip("No layers in catalog")
    allowed_layer_id = all_layers[0]["layer_id"]

    # Set whitelist mode and allow one layer
    auth_client.patch(
        f"/auth/users/{user['id']}/permission-mode",
        json={"mode": "whitelist"},
    )
    auth_client.put(
        f"/auth/users/{user['id']}/permissions",
        json={
            "permissions": [
                {"resource_type": "layer", "resource_id": allowed_layer_id, "permission": "allow"},
            ]
        },
    )

    _login_as(auth_client, "standarduser")
    resp = auth_client.get("/layers")
    assert resp.status_code == 200
    visible = resp.json().get("items", [])
    visible_ids = [l["layer_id"] for l in visible]
    assert allowed_layer_id in visible_ids
    # Should not see other layers
    for layer in all_layers[1:]:
        assert layer["layer_id"] not in visible_ids
