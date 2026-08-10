"""统一业务错误码契约测试（架构交付包 BD-03：C403001 / C429001）。

- ``C403001``：鉴权/授权失败（未鉴权写 fail-closed、无权限、登录失败等）。
- ``C429001``：限流触发，响应携带 ``Retry-After``（仅 production 生效）。
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


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_USER_AUTH_ENABLED", "true")
    monkeypatch.setenv("BACKEND_ADMIN_USERNAME", "testadmin")
    monkeypatch.setenv("BACKEND_ADMIN_PASSWORD", "test-pass-123")
    monkeypatch.setenv("BACKEND_API_KEY", "test-api-key")
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "true")
    monkeypatch.setenv("BACKEND_API_KEY_ROLE", "operator")
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
    )
    from app.services import user_repository as ur_mod
    from app.services.user_repository import UserRepository

    ur_mod._repo = UserRepository(tmp_path / "state" / "users.sqlite3")

    # 注意：须在 import app.main 之前替换 cfg_mod.settings（main 模块级绑定生效）
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
    # 失效 _get_effective_api_key_cached 的 lru_cache，避免跨测试污染读到旧 backend_auth。
    _get_effective_api_key_cached.cache_clear()
    hydrate_effective_config()

    with TestClient(create_app()) as client:
        yield client


def _login(client: TestClient, username: str, password: str) -> None:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text


def _create_viewer(client: TestClient) -> None:
    _login(client, "testadmin", "test-pass-123")
    resp = client.post(
        "/auth/users",
        json={"username": "viewer1", "password": "viewer-pass-1", "role": "viewer"},
    )
    assert resp.status_code == 201, resp.text
    client.post("/auth/logout")


def test_unauthenticated_write_returns_c403001(auth_client: TestClient) -> None:
    """未鉴权写：fail-closed 401 + 业务码 C403001（对齐架构契约）。"""
    resp = auth_client.put(
        "/config/api-keys/backend_auth",
        json={"key_value": "x"},
    )
    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert body["error_code"] == "C403001"
    assert body["detail"]
    assert body.get("request_id")


def test_viewer_write_returns_c403001(auth_client: TestClient) -> None:
    """viewer 角色写操作：403 + C403001。"""
    _create_viewer(auth_client)
    _login(auth_client, "viewer1", "viewer-pass-1")
    resp = auth_client.put(
        "/config/api-keys/backend_auth",
        json={"key_value": "x"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "C403001"


def test_invalid_login_returns_c403001(auth_client: TestClient) -> None:
    resp = auth_client.post(
        "/auth/login", json={"username": "nobody", "password": "wrong-pass"}
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["error_code"] == "C403001"


def test_admin_required_returns_c403001(auth_client: TestClient) -> None:
    _create_viewer(auth_client)
    _login(auth_client, "viewer1", "viewer-pass-1")
    resp = auth_client.get("/auth/users")
    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "C403001"


def test_rate_limited_response_c429001_with_retry_after(
    auth_client: TestClient,
    monkeypatch,
) -> None:
    """production 下写限流触发：429 + C429001 + Retry-After header。

    中间件读取 ``app.main.settings``（模块级绑定），故 patch 该引用而非
    ``app.core.config.settings``。
    """
    from dataclasses import replace

    import app.core.config as cfg_mod
    from app.api.rate_limit import RateLimitResult

    monkeypatch.setattr(
        "app.main.settings",
        replace(cfg_mod.settings, environment="production"),
    )

    import app.api.rate_limit as rl_mod

    monkeypatch.setattr(
        rl_mod,
        "check_write_rate_limit",
        lambda ip: RateLimitResult(allowed=False, retry_after_seconds=3),
    )
    monkeypatch.setattr(
        rl_mod,
        "check_login_rate_limit",
        lambda ip: RateLimitResult(allowed=True, retry_after_seconds=0),
    )
    monkeypatch.setattr(
        rl_mod,
        "check_weather_tile_rate_limit",
        lambda ip: RateLimitResult(allowed=True, retry_after_seconds=0),
    )

    resp = auth_client.put(
        "/config/api-keys/backend_auth",
        json={"key_value": "x"},
        headers={"X-API-Key": "test-api-key"},
    )
    assert resp.status_code == 429, resp.text
    body = resp.json()
    assert body["error_code"] == "C429001"
    assert resp.headers.get("Retry-After") == "3"


def test_validation_error_has_no_error_code(auth_client: TestClient) -> None:
    """422 校验错误不属于 C403001/C429001 语义域，不应携带业务码。"""
    resp2 = auth_client.post("/auth/login", json={"username": ""})
    assert resp2.status_code == 422, resp2.text
    assert "error_code" not in resp2.json()
