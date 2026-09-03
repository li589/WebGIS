"""Product themes: branding seed, user binding, ACL merge (theme ? user override)."""

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
def theme_client(tmp_path, monkeypatch):
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
        workflow_state_dir=str(tmp_path / "state"),
    )
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)

    from app.services import theme_repository as tr_mod
    from app.services import user_repository as ur_mod
    from app.services import permission_repository as pr_mod
    from app.services.theme_repository import ThemeRepository, reset_theme_repository_for_tests
    from app.services.user_repository import UserRepository
    from app.services.permission_repository import (
        PermissionRepository,
        reset_permission_repository_for_tests,
    )

    db = tmp_path / "state" / "users.sqlite3"
    repo = UserRepository(db)
    themes = ThemeRepository(db)
    perms = PermissionRepository(db)

    from app.main import create_app
    from app.services.auth_bootstrap import bootstrap_auth
    from app.services.config_service import (
        _get_api_keys_repository,
        _get_effective_api_key_cached,
    )
    from app.services.effective_config import hydrate_effective_config

    reset_theme_repository_for_tests()
    reset_permission_repository_for_tests()

    with (
        patch.object(ur_mod, "_repo", repo),
        patch.object(tr_mod, "_repo", themes),
        patch.object(pr_mod, "_repo", perms),
    ):
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

    reset_theme_repository_for_tests()
    reset_permission_repository_for_tests()


def _admin_login(client: TestClient) -> None:
    r = client.post(
        "/auth/login", json={"username": "testadmin", "password": "test-pass-123"}
    )
    assert r.status_code == 200, r.text


def test_primary_theme_public_branding(theme_client: TestClient) -> None:
    from app.services.theme_repository import (
        SGFS_ABBR,
        SGFS_FULL_NAME_ZH,
        SGFS_NAME_EN,
        SGFS_NAME_ZH,
        SGFS_SLUG,
    )

    r = theme_client.get("/auth/themes/primary/public")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == SGFS_SLUG
    assert body["abbr"] == SGFS_ABBR
    assert body["name_en"] == SGFS_NAME_EN
    assert body["name_zh"] == SGFS_NAME_ZH
    assert body["full_name_zh"] == SGFS_FULL_NAME_ZH


def test_list_themes_public_branding(theme_client: TestClient) -> None:
    r = theme_client.get("/auth/themes/public")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    assert body[0]["slug"] == "sgfs"
    slugs = {t["slug"] for t in body}
    assert "sgfs" in slugs


def test_login_includes_theme(theme_client: TestClient) -> None:
    _admin_login(theme_client)
    me = theme_client.get("/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["theme_id"] is not None
    assert body["theme"]["slug"] == "sgfs"
    assert body["theme"]["name_en"].startswith("Satellite-Ground")


def test_theme_acl_user_override_wins(theme_client: TestClient) -> None:
    from app.services.permission_repository import (
        PermissionInput,
        get_permission_repository,
    )
    from app.services.theme_repository import get_theme_repository
    from app.services.user_repository import get_user_repository

    _admin_login(theme_client)
    themes = get_theme_repository()
    primary = themes.get_primary()
    themes.set_theme_permissions(
        primary.id,
        [
            PermissionInput(
                resource_type="layer", resource_id="wind-field", permission="deny"
            ),
            PermissionInput(
                resource_type="layer", resource_id="precipitation", permission="allow"
            ),
        ],
    )

    users = get_user_repository()
    created = users.create_user(
        username="std1", password="password123", role="standard", theme_id=primary.id
    )
    uid = int(created["id"])
    perms = get_permission_repository()
    perms.set_permission_mode(uid, "open")

    assert perms.check_resource_access(uid, "layer", "wind-field") is False
    assert perms.check_resource_access(uid, "layer", "precipitation") is True

    # User override allow on theme-denied resource
    perms.set_user_permissions(
        uid,
        [
            PermissionInput(
                resource_type="layer", resource_id="wind-field", permission="allow"
            )
        ],
    )
    assert perms.check_resource_access(uid, "layer", "wind-field") is True


def test_theme_whitelist_default(theme_client: TestClient) -> None:
    from app.services.permission_repository import PermissionInput, get_permission_repository
    from app.services.theme_repository import get_theme_repository
    from app.services.user_repository import get_user_repository

    _admin_login(theme_client)
    themes = get_theme_repository()
    demo = themes.create_theme(
        slug="demo-theme",
        name_zh="????",
        full_name_zh="??????",
        name_en="Demo Theme",
        abbr="DEMO",
        default_permission_mode="whitelist",
    )
    themes.set_theme_permissions(
        demo.id,
        [
            PermissionInput(
                resource_type="layer", resource_id="temperature", permission="allow"
            )
        ],
    )
    users = get_user_repository()
    created = users.create_user(
        username="std2", password="password123", role="standard", theme_id=demo.id
    )
    uid = int(created["id"])
    perms = get_permission_repository()
    # create_user copies theme default_permission_mode; assert inherit + whitelist
    assert perms.get_permission_mode(uid) == "whitelist"
    assert perms.check_resource_access(uid, "layer", "temperature") is True
    assert perms.check_resource_access(uid, "layer", "wind-field") is False


def test_create_theme_via_api(theme_client: TestClient) -> None:
    _admin_login(theme_client)
    r = theme_client.post(
        "/auth/themes",
        json={
            "slug": "soil-lab",
            "name_zh": "?????",
            "full_name_zh": "???????",
            "name_en": "Soil Lab Theme",
            "abbr": "SLAB",
            "default_permission_mode": "whitelist",
        },
    )
    assert r.status_code == 201, r.text
    theme_id = r.json()["id"]
    listed = theme_client.get("/auth/themes")
    assert listed.status_code == 200
    assert any(t["id"] == theme_id for t in listed.json())


def test_login_palette_infer_and_update(theme_client: TestClient) -> None:
    """???????????? green??? PATCH ????????????"""
    _admin_login(theme_client)
    created = theme_client.post(
        "/auth/themes",
        json={
            "slug": "vemp-ecology",
            "name_zh": "?????????",
            "full_name_zh": "?????????????",
            "name_en": "Vegetation and Ecology Monitoring Platform",
            "abbr": "VEMP",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["login_palette"] == "green"
    theme_id = body["id"]

    patched = theme_client.patch(
        f"/auth/themes/{theme_id}",
        json={"login_palette": "violet"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["login_palette"] == "violet"

    public = theme_client.get("/auth/themes/public")
    assert public.status_code == 200
    match = next(t for t in public.json() if t["id"] == theme_id)
    assert match["login_palette"] == "violet"

    bad = theme_client.patch(
        f"/auth/themes/{theme_id}",
        json={"login_palette": "neon"},
    )
    assert bad.status_code == 422

def test_user_theme_id_cannot_be_cleared(theme_client: TestClient) -> None:
    """Mandatory bind: PATCH theme_id=null is rejected; new users default to primary."""
    _admin_login(theme_client)
    created = theme_client.post(
        "/auth/users",
        json={"username": "bound-user", "password": "password123", "role": "standard"},
    )
    assert created.status_code == 201, created.text
    user = created.json()
    assert user["theme_id"] is not None
    assert user["theme"]["slug"] == "sgfs"

    cleared = theme_client.patch(
        f"/auth/users/{user['id']}",
        json={"theme_id": None},
    )
    assert cleared.status_code == 422, cleared.text
