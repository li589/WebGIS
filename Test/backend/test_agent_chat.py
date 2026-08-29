"""Tests for Agent chat + global/personal profiles + tools/memory."""

from __future__ import annotations

import json
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
def agent_client(tmp_path, monkeypatch):
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
        # Create a standard user for personal-profile tests
        repo.create_user(
            username="stduser",
            password="std-pass-123",
            role="standard",
        )
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


AUTH = {"X-API-Key": "test-api-key"}


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    res = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert res.status_code == 200, res.text
    # Cookie session set by TestClient
    return {}


def test_agent_chat_requires_auth(agent_client: TestClient):
    res = agent_client.post("/agent/chat", json={"message": "打开降水"})
    assert res.status_code == 401


def test_agent_chat_open_layer_with_api_key(agent_client: TestClient):
    res = agent_client.post(
        "/agent/chat",
        json={"message": "打开 CMFD 降水"},
        headers=AUTH,
    )
    assert res.status_code == 200
    body = res.json()
    assert "降水" in body["reply"] or "cmfd" in body["reply"].lower()
    assert body["ui_intents"]
    assert body.get("usage")
    assert body.get("steps") is not None
    assert body["provider"] == "demo"


def test_agent_chat_list_layers_from_context(agent_client: TestClient):
    res = agent_client.post(
        "/agent/chat",
        json={
            "message": "有哪些活动图层",
            "client_context": {
                "active_layers": [
                    {
                        "catalog_id": "dem-etopo",
                        "instance_id": "abc-123",
                        "name": "ETOPO 高程",
                    }
                ]
            },
        },
        headers=AUTH,
    )
    assert res.status_code == 200
    body = res.json()
    assert "dem-etopo" in body["reply"]


def test_agent_chat_opacity_intent(agent_client: TestClient):
    res = agent_client.post(
        "/agent/chat",
        json={
            "message": "cmfd 透明度 50%",
            "client_context": {"active_catalog_ids": ["cmfd-precip-cn"]},
        },
        headers=AUTH,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ui_intents"][0]["name"] == "set_layer_opacity"
    assert body["ui_intents"][0]["args"]["opacity"] == pytest.approx(0.5)


def test_agent_chat_session_memory(agent_client: TestClient):
    r1 = agent_client.post(
        "/agent/chat",
        json={"message": "打开 CMFD 降水", "session_id": "mem-test-1"},
        headers=AUTH,
    )
    assert r1.status_code == 200
    r2 = agent_client.post(
        "/agent/chat",
        json={"message": "有哪些活动图层", "session_id": "mem-test-1"},
        headers=AUTH,
    )
    assert r2.status_code == 200
    assert "此前" in r2.json()["reply"] or r2.json()["session_id"] == "mem-test-1"


def test_provider_catalog_json_loads():
    from app.services.agent.presets import _reload_presets_for_tests, list_presets

    _reload_presets_for_tests()
    presets = list_presets()
    ids = {p["id"] for p in presets}
    assert "demo" in ids
    assert "deepseek" in ids
    assert "ollama" in ids


def test_normalize_drops_legacy_migration_and_repairs_demo():
    from app.services.agent.config_service import (
        _default_demo_profile,
        _normalize_global_store,
    )

    dirty = {
        "active_profile_id": "deadbeef",
        "profiles": [
            {
                "id": "demo",
                "name": "迁移自旧配置 (mock)",
                "provider_kind": "demo",
                "protocol": "demo",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen2.5",
                "context_window_input": 8192,
                "context_window_output": 4096,
                "preset_id": "demo",
                "api_key_ciphertext": "sk-test",
                "api_key_iv": "",
            },
            {
                "id": "aaaa",
                "name": "DeepSeek",
                "provider_kind": "deepseek",
                "protocol": "openai",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "context_window_input": 64000,
                "context_window_output": 8192,
                "preset_id": "deepseek",
            },
            {
                "id": "aaaa",
                "name": "DeepSeek dup",
                "provider_kind": "deepseek",
                "protocol": "openai",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "context_window_input": 64000,
                "context_window_output": 4096,
                "preset_id": "deepseek",
            },
        ],
    }
    store, changed = _normalize_global_store(dirty)
    assert changed is True
    assert store["active_profile_id"] == "demo"
    ids = [p["id"] for p in store["profiles"]]
    assert ids.count("demo") == 1
    assert ids.count("aaaa") == 1
    demo = next(p for p in store["profiles"] if p["id"] == "demo")
    assert demo == _default_demo_profile()
    assert not any(str(p.get("name") or "").startswith("迁移自旧配置") for p in store["profiles"])


def test_mock_legacy_migrates_to_demo_only(tmp_path, monkeypatch):
    from dataclasses import replace

    import app.core.config as cfg_mod
    from app.core.config import Settings

    data = tmp_path / "data"
    data.mkdir()
    runtime = data / "_runtime"
    runtime.mkdir()
    (runtime / "agent_config.json").write_text(
        json.dumps(
            {
                "provider": "mock",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen2.5",
                "api_key_ciphertext": "sk-test",
                "api_key_iv": "",
            }
        ),
        encoding="utf-8",
    )
    cfg_mod.settings = replace(Settings(), data_root=str(data), environment="test")
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)

    from app.services.agent import config_service as cs

    monkeypatch.setattr(cs, "settings", cfg_mod.settings)
    dest = data / "_runtime" / "agent" / "global_profiles.json"
    assert not dest.exists()
    cs._ensure_global_migrated()
    assert dest.exists()
    store = json.loads(dest.read_text(encoding="utf-8"))
    assert store["active_profile_id"] == "demo"
    assert len(store["profiles"]) == 1
    assert store["profiles"][0]["id"] == "demo"
    assert store["profiles"][0]["name"] == "演示（无网）"
    assert not (runtime / "agent_config.json").exists()
    assert (runtime / "agent_config.json.migrated.bak").exists()


def test_global_admin_vs_standard_personal(agent_client: TestClient):
    # Service key cannot create personal (no user_id) → 403
    bad = agent_client.post(
        "/agent/config/profiles",
        json={"preset_id": "ollama", "scope": "personal"},
        headers=AUTH,
    )
    assert bad.status_code == 403

    # Standard login: personal OK, global forbidden
    _login(agent_client, "stduser", "std-pass-123")
    pers = agent_client.post(
        "/agent/config/profiles",
        json={"preset_id": "ollama", "scope": "personal", "name": "我的 Ollama"},
    )
    assert pers.status_code == 200
    assert pers.json()["scope"] == "personal"
    assert "api_key" not in pers.json()

    forbid = agent_client.post(
        "/agent/config/profiles",
        json={"preset_id": "openai", "scope": "global"},
    )
    assert forbid.status_code == 403

    # Admin login: global OK
    agent_client.post("/auth/logout")
    _login(agent_client, "testadmin", "test-pass-123")
    glob = agent_client.post(
        "/agent/config/profiles",
        json={"preset_id": "deepseek", "scope": "global"},
    )
    assert glob.status_code == 200
    assert glob.json()["scope"] == "global"
    assert "sk-" not in json.dumps(glob.json())

    put = agent_client.put(
        f"/agent/config/profiles/{glob.json()['id']}",
        json={"scope": "global", "api_key": "sk-secret-never"},
    )
    assert put.status_code == 200
    assert put.json()["has_api_key"] is True
    assert "sk-secret" not in json.dumps(put.json())


def test_agent_config_bundle_shape(agent_client: TestClient):
    get_res = agent_client.get("/agent/config", headers=AUTH)
    assert get_res.status_code == 200
    bundle = get_res.json()
    assert "active_profile_id" in bundle
    assert "active_scope" in bundle
    assert "can_manage_global" in bundle
    assert isinstance(bundle["profiles"], list)
    assert isinstance(bundle["presets"], list)


def test_agent_openai_orchestrator_mocked(agent_client: TestClient):
    _login(agent_client, "testadmin", "test-pass-123")
    create = agent_client.post(
        "/agent/config/profiles",
        json={"preset_id": "openai", "scope": "global"},
    )
    pid = create.json()["id"]
    agent_client.put(
        f"/agent/config/profiles/{pid}",
        json={"scope": "global", "api_key": "sk-test"},
    )
    agent_client.post(
        "/agent/config/active",
        json={"profile_id": pid, "scope": "global"},
    )

    fake = {
        "choices": [
            {
                "message": {
                    "content": "已为你打开降水图层。",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "function": {
                                "name": "set_layer_visibility",
                                "arguments": json.dumps(
                                    {"catalog_id": "cmfd-precip-cn", "visible": True}
                                ),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    with patch(
        "app.services.agent.clients.openai_compat.chat_completions",
        return_value=fake,
    ):
        res = agent_client.post(
            "/agent/chat",
            json={"message": "打开降水"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["ui_intents"][0]["name"] == "set_layer_visibility"
    assert body["usage"]["total_tokens"] >= 15
    assert body["usage"].get("estimated") is False
    assert body["steps"]


def test_search_layers_runtime():
    from app.services.agent.server_tools_runtime import execute_server_tool

    class _Cred:
        role = "admin"
        user_id = 1
        source = "session"

    out = execute_server_tool(
        "search_layers", {"query": "cmfd", "limit": 5}, cred=_Cred()
    )
    assert out["ok"] is True
    blocked = execute_server_tool("run_workflow", {"catalog_id": "x"}, cred=_Cred())
    assert blocked["ok"] is False


def test_mock_orchestrator_unit():
    from app.services.agent.mock_orchestrator import mock_chat

    out = mock_chat(
        "定位到降水", client_context={"active_catalog_ids": ["cmfd-precip-cn"]}
    )
    assert out["ui_intents"][0]["name"] == "fit_layer"


def test_should_rate_limit_agent_chat():
    from app.api.rate_limit import should_rate_limit_agent_chat

    assert should_rate_limit_agent_chat("/agent/chat", "POST") is True
    assert should_rate_limit_agent_chat("/agent/config", "POST") is False


def test_should_rate_limit_agent_models_refresh():
    from app.api.rate_limit import should_rate_limit_agent_models_refresh

    assert should_rate_limit_agent_models_refresh("/agent/models/refresh", "POST") is True
    assert should_rate_limit_agent_models_refresh("/agent/models/refresh/", "POST") is True
    assert should_rate_limit_agent_models_refresh("/agent/chat", "POST") is False


def test_standard_cannot_refresh_global_models(agent_client: TestClient):
    """M-1: non-admin must not drive global profile outbound refresh."""
    _login(agent_client, "stduser", "std-pass-123")
    r = agent_client.post(
        "/agent/models/refresh",
        json={"profile_id": "demo", "scope": "global"},
    )
    assert r.status_code == 403


def test_leaving_demo_revalidates_base_url(tmp_path, monkeypatch):
    """W-2: switching protocol demo → openai must validate existing base_url."""
    from dataclasses import replace

    import app.core.config as cfg_mod
    from app.core.config import Settings
    from app.services.agent import config_service as cs

    data = tmp_path / "data"
    data.mkdir()
    cfg_mod.settings = replace(Settings(), data_root=str(data), environment="test")
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)
    monkeypatch.setattr(cs, "settings", cfg_mod.settings)

    store = {
        "active_profile_id": "demo",
        "profiles": [
            {
                "id": "demo",
                "name": "演示（无网）",
                "provider_kind": "demo",
                "protocol": "demo",
                "base_url": "http://169.254.169.254/",
                "model": "demo-rules",
                "context_window_input": 4000,
                "context_window_output": 2000,
                "preset_id": "demo",
            }
        ],
    }
    path = data / "_runtime" / "agent" / "global_profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store), encoding="utf-8")

    with pytest.raises(ValueError):
        cs.update_profile(
            "demo",
            scope="global",
            user_id=1,
            role="admin",
            protocol="openai",
        )


def test_session_store_ttl_and_cap(tmp_path, monkeypatch):
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    import app.core.config as cfg_mod
    from app.core.config import Settings

    monkeypatch.setenv("BACKEND_AGENT_SESSION_TTL_HOURS", "1")
    monkeypatch.setenv("BACKEND_AGENT_MAX_SESSIONS_PER_USER", "2")

    import importlib

    import app.services.agent.session_store as ss

    importlib.reload(ss)

    data = tmp_path / "data"
    data.mkdir()
    cfg_mod.settings = replace(Settings(), data_root=str(data), environment="test")
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)
    monkeypatch.setattr(ss, "settings", cfg_mod.settings)

    uid = 42
    ss.append_turn(user_id=uid, session_id="s1", user_message="a", assistant_message="a1")
    ss.append_turn(user_id=uid, session_id="s2", user_message="b", assistant_message="b1")
    ss.append_turn(user_id=uid, session_id="s3", user_message="c", assistant_message="c1")
    root = Path(data) / "_runtime" / "agent" / "sessions" / str(uid)
    files = list(root.glob("*.json"))
    assert len(files) <= 2

    old = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
    for f in root.glob("*.json"):
        raw = json.loads(f.read_text(encoding="utf-8"))
        raw["updated_at"] = old
        f.write_text(json.dumps(raw), encoding="utf-8")
    assert ss.load_history(user_id=uid, session_id="s3") == []
