"""Config endpoint contract + auth tests (CGDA review F3, breaking-change lock).

- GET /config/general now REQUIRES read auth (F3) and redis_url password is redacted.
- open-data-presets / remote-layer-uris now REQUIRE the wrapped request body; a bare
  dict is rejected with 422. This locks the intentional breaking change so it cannot
  be silently reverted to the old lenient "accept either" behavior.
- DELETE /api-keys/{key} returns the typed ApiKeyDeletedResponse envelope.
- GET /runtime/config snapshot shape (service layer + model validation).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dataclasses import replace

from app.api import deps
from app.core.config import settings as core_settings
from app.main import create_app
from app.services.config_service import _redact_redis_url
from app.services.workflow.service_container import runtime_status_service
from shared.contracts.api_contracts import RuntimeConfigSnapshotResponse
from shared.contracts.config_contracts import (
    ApiKeyDeletedResponse,
    GeeAccountDeletedResponse,
    GeeAccountToggleResponse,
    PortalCredentialUpsertRequest,
    PortalCredentialsMapResponse,
    RemoteStorageDeletedResponse,
    RemoteStorageToggleResponse,
    WeatherProviderDeletedResponse,
    WeatherProviderPriorityResponse,
    WeatherProviderToggleResponse,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # conftest sets BACKEND_ENV=test; require_write_access/read only bypasses in
    # development, so we must supply a key + header in the test environment.
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "test-key",
    )
    return TestClient(create_app(), headers={"X-API-Key": "test-key"})


@pytest.fixture
def anon_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "test-key",
    )
    # No X-API-Key header -> must be rejected.
    return TestClient(create_app())


# ── F3: /config/general auth + redis_url redaction ────────────────────────


def test_redact_redis_url_masks_password():
    assert (
        _redact_redis_url("redis://:secretpw@127.0.0.1:6379/0")
        == "redis://:***@127.0.0.1:6379/0"
    )
    assert (
        _redact_redis_url("redis://user:secretpw@host:6379")
        == "redis://user:***@host:6379"
    )
    # no credential -> unchanged
    assert _redact_redis_url("redis://127.0.0.1:6379/0") == "redis://127.0.0.1:6379/0"
    assert _redact_redis_url("") == ""


def test_general_config_requires_auth(anon_client: TestClient):
    resp = anon_client.get("/config/general")
    # Unauthenticated callers must be rejected (401 invalid key, or 503 if none configured).
    assert resp.status_code in (401, 403, 503)


def test_general_config_ok_with_auth_and_no_leak(client: TestClient):
    resp = client.get("/config/general")
    assert resp.status_code == 200
    data = resp.json()
    assert "redis_url" in data
    # Even authenticated callers must never receive a Redis password.
    redis_url = data["redis_url"]
    if "@" in redis_url:
        assert "***" in redis_url


# ── Breaking-change lock: wrapped body required ──────────────────────────


def test_open_data_presets_accepts_wrapped(client: TestClient):
    resp = client.put(
        "/config/data-source/open-data-presets",
        json={"open_data_presets": {"noaa_nomads": "https://nomads.ncep.noaa.gov/"}},
    )
    assert resp.status_code == 200


def test_open_data_presets_rejects_bare_dict(client: TestClient):
    # Old "accept either bare dict or wrapped" behavior is gone; bare dict -> 422.
    resp = client.put(
        "/config/data-source/open-data-presets",
        json={"noaa_nomads": "https://nomads.ncep.noaa.gov/"},
    )
    assert resp.status_code == 422


def test_remote_layer_uris_accepts_wrapped(client: TestClient):
    resp = client.put(
        "/config/data-source/remote-layer-uris",
        json={"remote_layer_data_uris": {"foo": ["https://example.com/x/"]}},
    )
    assert resp.status_code == 200


def test_remote_layer_uris_rejects_bare_dict(client: TestClient):
    resp = client.put(
        "/config/data-source/remote-layer-uris",
        json={"foo": ["https://example.com/x/"]},
    )
    assert resp.status_code == 422


# ── Response envelope ─────────────────────────────────────────────────────


def test_api_key_deleted_envelope_shape():
    assert ApiKeyDeletedResponse(deleted=True, key_name="x").model_dump() == {
        "deleted": True,
        "key_name": "x",
    }


# ── /runtime/config snapshot shape ────────────────────────────────────────


def test_runtime_config_snapshot_shape():
    snapshot = runtime_status_service.get_runtime_config()
    assert isinstance(snapshot, dict)
    # backend scope is always present with the documented runtime keys
    assert "backend" in snapshot
    assert isinstance(snapshot["backend"], dict)
    # The endpoint simply model_validates this; validate the same contract here.
    validated = RuntimeConfigSnapshotResponse.model_validate(snapshot)
    assert validated is not None


# ════════════════════════════════════════════════════════════════════════════
# Phase 2 缺口补齐测试（审查发现 F6 / F7 / F8 / F12 / F6-async）
# ════════════════════════════════════════════════════════════════════════════


# ── F6: portal-credentials 声明字段（含 clear_secrets）→200；data-cache/evict
#        包裹体→200；验证 extra="ignore" 仅透传声明字段 ───────────────────────


def test_portal_credential_upsert_declared_fields_incl_clear_secrets(client: TestClient):
    resp = client.put(
        "/config/data-source/portal-credentials/earthdata",
        json={
            "enabled": True,
            "auth_type": "earthdata",
            "username": "tessa",
            "clear_secrets": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "portal_credentials" in data


def test_portal_credential_request_extra_ignored_at_model():
    # extra="ignore": 声明字段之外的字段被静默丢弃，不会 422
    req = PortalCredentialUpsertRequest(
        enabled=True,
        auth_type="earthdata",
        username="tessa",
        clear_secrets=False,
        not_a_declared_field="should-be-dropped",
    )
    dumped = req.model_dump()
    # 未声明字段不透传
    assert "not_a_declared_field" not in dumped
    # 声明字段原样保留
    assert dumped["enabled"] is True
    assert dumped["clear_secrets"] is False
    assert dumped["auth_type"] == "earthdata"


def test_portal_credential_upsert_accepts_undeclared_extra_over_http(client: TestClient):
    # 通过 HTTP 发送未声明字段，依靠 extra="ignore" 解析而非 422
    resp = client.put(
        "/config/data-source/portal-credentials/earthdata",
        json={"enabled": True, "rogue_field": "ignored"},
    )
    assert resp.status_code == 200


def test_data_cache_evict_wrapped_body(client: TestClient):
    resp = client.post(
        "/config/data-cache/evict",
        json={"uri_or_name": "tessa-nonexistent-cache-key", "older_than_seconds": 3600},
    )
    assert resp.status_code == 200
    data = resp.json()
    # 包裹体反序列化成功；响应含 cache_root 且 removed 为列表
    assert "cache_root" in data
    assert isinstance(data.get("removed", []), list)


# ── F7: 扩展 delete/toggle *Response 信封结构断言 ──────────────────────────
# 既有 test_api_key_deleted_envelope_shape 已覆盖 ApiKeyDeletedResponse；
# 此处补齐其余 delete/toggle 端点的信封（均为纯模型断言，稳定、无 DB 依赖）。


def test_gee_account_deleted_envelope_shape():
    assert GeeAccountDeletedResponse(deleted=True, account_id="a1").model_dump() == {
        "deleted": True,
        "account_id": "a1",
    }


def test_gee_account_toggle_envelope_shape():
    assert GeeAccountToggleResponse(account_id="a1", enabled=True).model_dump() == {
        "account_id": "a1",
        "enabled": True,
    }


def test_weather_provider_deleted_envelope_shape():
    assert WeatherProviderDeletedResponse(deleted=True, provider_id="p1").model_dump() == {
        "deleted": True,
        "provider_id": "p1",
    }


def test_weather_provider_toggle_envelope_shape():
    assert WeatherProviderToggleResponse(provider_id="p1", enabled=False).model_dump() == {
        "provider_id": "p1",
        "enabled": False,
    }


def test_weather_provider_priority_envelope_shape():
    assert WeatherProviderPriorityResponse(provider_id="p1", priority=7).model_dump() == {
        "provider_id": "p1",
        "priority": 7,
    }


def test_remote_storage_deleted_envelope_shape():
    assert RemoteStorageDeletedResponse(deleted=True, profile_id="pf1").model_dump() == {
        "deleted": True,
        "profile_id": "pf1",
    }


def test_remote_storage_toggle_envelope_shape():
    assert RemoteStorageToggleResponse(profile_id="pf1", enabled=True).model_dump() == {
        "profile_id": "pf1",
        "enabled": True,
    }


def test_portal_credentials_map_envelope_shape():
    # upsert / delete 门户凭证均返回该整图信封（非单条 toggle 信封）
    assert PortalCredentialsMapResponse(portal_credentials={}).model_dump() == {
        "portal_credentials": {}
    }


# ── F8: GET /runtime/config 合并快照 scope→key→value 结构 ─────────────────


def test_runtime_config_http_snapshot_scope_structure(client: TestClient):
    resp = client.get("/runtime/config")
    assert resp.status_code == 200
    snap = resp.json()
    assert isinstance(snap, dict)
    # 顶层按 scope 划分（backend / frontend / workflow ...）
    assert "backend" in snap
    assert isinstance(snap["backend"], dict)
    # 合并快照呈现 scope→key→value 结构（backend 下至少存在一组 key）
    assert len(snap["backend"]) > 0


# ── F12: dev 局域网旁路正向路径 ───────────────────────────────────────────
# development + api_keys_enabled=False + BACKEND_DEV_AUTH_BYPASS=true +
# 非 loopback 客户端主机 → 写端点应返回 200（无需 X-API-Key）。
# save/restore settings 由 monkeypatch 自动保证。


def test_dev_lan_bypass_allows_write_without_key(
    anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        deps,
        "settings",
        replace(core_settings, environment="development", api_keys_enabled=False),
    )
    monkeypatch.setenv("BACKEND_DEV_AUTH_BYPASS", "true")
    # TestClient 默认 client.host="testclient"，不在 _LOOPBACK_IPS，属非 loopback
    resp = anon_client.put(
        "/config/data-source/open-data-presets",
        json={"open_data_presets": {"noaa_nomads": "https://nomads.ncep.noaa.gov/"}},
    )
    assert resp.status_code == 200


# ── F6-async: 3 个 anyio.to_thread.run_sync 的 api-key 写路由 HTTP 级一致性 ─
# update / delete / toggle 跨线程写入后，GET /config/api-keys 读回应一致
# （间接验证 hydrate_effective_config 已在线程边界生效）。


def test_api_key_update_persists_via_thread(client: TestClient):
    name = "tessa_ak_update"
    resp = client.put(
        f"/config/api-keys/{name}",
        json={"key_value": "tessa-secret-value-123", "enabled": True, "display_name": "Tessa AK"},
    )
    assert resp.status_code == 200
    assert resp.json()["key_name"] == name
    listed = client.get("/config/api-keys").json()
    assert any(k["key_name"] == name for k in listed)


def test_api_key_toggle_flips_status(client: TestClient):
    name = "tessa_ak_toggle"
    client.put(
        f"/config/api-keys/{name}",
        json={"key_value": "tessa-toggle-value-123", "enabled": False},
    )
    resp = client.put(f"/config/api-keys/{name}/toggle", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    listed = client.get("/config/api-keys").json()
    item = next(k for k in listed if k["key_name"] == name)
    assert item["enabled"] is True


def test_api_key_delete_via_thread(client: TestClient):
    name = "tessa_ak_delete"
    client.put(
        f"/config/api-keys/{name}",
        json={"key_value": "tessa-delete-value-123", "enabled": True},
    )
    resp = client.delete(f"/config/api-keys/{name}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "key_name": name}
    listed = client.get("/config/api-keys").json()
    assert not any(k["key_name"] == name for k in listed)
