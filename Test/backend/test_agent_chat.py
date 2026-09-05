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


def test_normalize_collapses_identical_preset_clones():
    from app.services.agent.config_service import _normalize_global_store

    dirty = {
        "active_profile_id": "o3",
        "profiles": [
            {
                "id": "demo",
                "name": "演示（无网）",
                "provider_kind": "demo",
                "protocol": "demo",
                "preset_id": "demo",
            },
            {
                "id": "o1",
                "name": "OpenAI",
                "provider_kind": "openai",
                "protocol": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "preset_id": "openai",
                "api_key_ciphertext": None,
            },
            {
                "id": "o2",
                "name": "OpenAI",
                "provider_kind": "openai",
                "protocol": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "preset_id": "openai",
                "api_key_ciphertext": "sk-keep-me",
            },
            {
                "id": "o3",
                "name": "OpenAI",
                "provider_kind": "openai",
                "protocol": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "preset_id": "openai",
                "api_key_ciphertext": None,
            },
            {
                "id": "o-custom",
                "name": "OpenAI",
                "provider_kind": "openai",
                "protocol": "openai",
                "base_url": "http://127.0.0.1:9/v1",
                "model": "gpt-4o-mini",
                "preset_id": "openai",
            },
        ],
    }
    store, changed = _normalize_global_store(dirty)
    assert changed is True
    openai_rows = [p for p in store["profiles"] if p.get("preset_id") == "openai"]
    assert len(openai_rows) == 2
    kept_default = next(
        p for p in openai_rows if "api.openai.com" in str(p.get("base_url") or "")
    )
    assert kept_default.get("api_key_ciphertext") == "sk-keep-me"
    assert store["active_profile_id"] == "demo" or store["active_profile_id"] in {
        str(p["id"]) for p in store["profiles"]
    }


def test_create_profile_from_preset_is_idempotent(agent_client, tmp_path):
    """Repeated「从预设新建」with same defaults must not pile identical rows."""
    _login(agent_client, "testadmin", "test-pass-123")
    r1 = agent_client.post(
        "/agent/config/profiles",
        json={"preset_id": "openai", "scope": "global"},
    )
    assert r1.status_code == 200, r1.text
    id1 = r1.json()["id"]
    r2 = agent_client.post(
        "/agent/config/profiles",
        json={"preset_id": "openai", "scope": "global"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == id1
    store = json.loads(
        (tmp_path / "data" / "_runtime" / "agent" / "global_profiles.json").read_text(
            encoding="utf-8"
        )
    )
    openai_rows = [p for p in store["profiles"] if p.get("preset_id") == "openai"]
    assert len(openai_rows) == 1


def test_personal_store_collapses_identical_clones_on_load(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    from dataclasses import replace
    import app.core.config as cfg_mod
    from app.core.config import Settings
    from app.services.agent import config_service as cs

    cfg_mod.settings = replace(Settings(), data_root=str(tmp_path / "data"), environment="test")
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)

    path = tmp_path / "data" / "_runtime" / "agent" / "users" / "9" / "profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    twin = {
        "id": "a1",
        "name": "我的 Ollama",
        "provider_kind": "ollama",
        "protocol": "openai",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5",
        "preset_id": "ollama",
    }
    twin2 = dict(twin)
    twin2["id"] = "a2"
    path.write_text(
        json.dumps({"active_profile_id": "", "profiles": [twin, twin2]}, ensure_ascii=False),
        encoding="utf-8",
    )
    store = cs._load_store_unlocked(path, personal=True)
    assert len(store["profiles"]) == 1
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert len(disk["profiles"]) == 1


def test_agent_client_does_not_write_outside_tmp(agent_client: TestClient, tmp_path):
    """Regression: global profile creates must land under the test data_root."""
    from app.core import config as cfg_mod
    from app.services.agent import config_service as cs

    assert Path(cfg_mod.settings.data_root) == tmp_path / "data"
    assert cs._runtime_root() == tmp_path / "data" / "_runtime" / "agent"

    _login(agent_client, "testadmin", "test-pass-123")
    res = agent_client.post(
        "/agent/config/profiles",
        json={"preset_id": "openai", "scope": "global"},
    )
    assert res.status_code == 200, res.text
    store_path = tmp_path / "data" / "_runtime" / "agent" / "global_profiles.json"
    assert store_path.is_file()
    store = json.loads(store_path.read_text(encoding="utf-8"))
    assert any(p.get("preset_id") == "openai" for p in store["profiles"])


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


def test_list_workflows_and_get_layer_meta():
    from app.services.agent.server_tools_runtime import (
        ALLOWED_SERVER_TOOLS,
        execute_server_tool,
    )

    assert "list_workflows" in ALLOWED_SERVER_TOOLS
    assert "get_layer_meta" in ALLOWED_SERVER_TOOLS

    class _Cred:
        role = "admin"
        user_id = 1
        source = "session"

    wf = execute_server_tool("list_workflows", {"limit": 10}, cred=_Cred())
    assert wf["ok"] is True
    assert isinstance(wf.get("workflows"), list)

    meta = execute_server_tool(
        "get_layer_meta", {"catalog_id": "ndvi"}, cred=_Cred()
    )
    assert meta["ok"] is True
    assert meta["layer"]["layer_id"] == "ndvi"
    assert "workflow_id" in meta["layer"]

    missing = execute_server_tool(
        "get_layer_meta", {"catalog_id": ""}, cred=_Cred()
    )
    assert missing["ok"] is False


def test_agent_openai_multihop_tools_mocked(agent_client: TestClient, monkeypatch):
    monkeypatch.setenv("BACKEND_AGENT_MAX_TOOL_HOPS", "4")
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

    hop1 = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "t1",
                            "function": {
                                "name": "list_workflows",
                                "arguments": json.dumps({"limit": 5}),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
    }
    hop2 = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "t2",
                            "function": {
                                "name": "get_layer_meta",
                                "arguments": json.dumps({"catalog_id": "ndvi"}),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
    }
    final = {
        "choices": [
            {
                "message": {
                    "content": "已查到工作流与 NDVI 图层元数据。",
                    "tool_calls": [],
                }
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
    }

    with patch(
        "app.services.agent.clients.openai_compat.chat_completions",
        side_effect=[hop1, hop2, final],
    ) as mock_llm:
        res = agent_client.post(
            "/agent/chat",
            json={"message": "查一下工作流再看 ndvi 元数据"},
        )
    assert res.status_code == 200
    body = res.json()
    assert "NDVI" in body["reply"] or "元数据" in body["reply"]
    assert mock_llm.call_count == 3
    tool_steps = [s for s in body["steps"] if s.get("type") == "tool"]
    assert len(tool_steps) >= 2
    hop_thoughts = [
        s
        for s in body["steps"]
        if s.get("type") == "thought" and "工具跳" in str(s.get("summary") or "")
    ]
    assert len(hop_thoughts) >= 2


def test_agent_openai_multihop_cap(agent_client: TestClient, monkeypatch):
    monkeypatch.setenv("BACKEND_AGENT_MAX_TOOL_HOPS", "1")
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

    always_tool = {
        "choices": [
            {
                "message": {
                    "content": "继续",
                    "tool_calls": [
                        {
                            "id": "tx",
                            "function": {
                                "name": "list_workflows",
                                "arguments": "{}",
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    with patch(
        "app.services.agent.clients.openai_compat.chat_completions",
        side_effect=[always_tool, always_tool, always_tool],
    ) as mock_llm:
        res = agent_client.post("/agent/chat", json={"message": "无限工具"})
    assert res.status_code == 200
    body = res.json()
    # initial + 1 follow-up after hop 1; no further hops
    assert mock_llm.call_count == 2
    assert any(
        "上限" in str(s.get("summary") or "")
        for s in body["steps"]
        if s.get("type") == "thought"
    )


def test_run_workflow_creates_confirmation_ticket(tmp_path, monkeypatch):
    from dataclasses import replace

    import app.core.config as cfg_mod
    from app.core.config import Settings
    from app.services.agent import agent_confirm as ac
    from app.services.agent.server_tools_runtime import execute_server_tool

    data = tmp_path / "data"
    data.mkdir()
    cfg_mod.settings = replace(Settings(), data_root=str(data), environment="test")
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)


    class _Cred:
        role = "admin"
        user_id = 1
        source = "session"

    class _Demo:
        role = "demo"
        user_id = 9
        source = "session"

    denied = execute_server_tool(
        "run_workflow",
        {"catalog_id": "ndvi", "workflow_id": "ndvi_local_read"},
        cred=_Demo(),
    )
    assert denied["ok"] is False

    out = execute_server_tool(
        "run_workflow",
        {"catalog_id": "ndvi", "workflow_id": "ndvi_local_read", "params": {"a": 1}},
        cred=_Cred(),
    )
    assert out["ok"] is True
    assert out.get("needs_confirmation") is True
    cid = out["confirmation_id"]
    assert cid
    ticket = ac.get_confirmation(cid)
    assert ticket is not None
    assert ticket["status"] == "pending"
    assert ticket["submit_payload"]["layer_id"] == "ndvi"


def test_agent_confirm_approve_reject_and_expire(tmp_path, monkeypatch):
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta
    from unittest.mock import MagicMock

    import app.core.config as cfg_mod
    from app.core.config import Settings
    from app.services.agent import agent_confirm as ac

    data = tmp_path / "data"
    data.mkdir()
    cfg_mod.settings = replace(Settings(), data_root=str(data), environment="test")
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)


    ticket = ac.create_confirmation(
        action="run_workflow",
        summary={"catalog_id": "ndvi", "workflow_id": "ndvi_local_read"},
        submit_payload={"layer_id": "ndvi", "command_type": "analysis"},
        user_id=1,
        role="standard",
    )
    cid = ticket["confirmation_id"]

    # Wrong user cannot consume
    with pytest.raises(ValueError, match="无权"):
        ac.consume_confirmation(cid, user_id=2, role="standard", decision="approve")

    rejected = ac.consume_confirmation(
        cid, user_id=1, role="standard", decision="reject"
    )
    assert rejected["status"] == "rejected"

    ticket2 = ac.create_confirmation(
        action="run_workflow",
        summary={"catalog_id": "ndvi"},
        submit_payload={"layer_id": "ndvi", "command_type": "analysis"},
        user_id=1,
        role="standard",
    )
    path = ac._path_for(ticket2["confirmation_id"])
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["expires_at"] = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="过期"):
        ac.consume_confirmation(
            ticket2["confirmation_id"],
            user_id=1,
            role="standard",
            decision="approve",
        )


def test_agent_chat_run_workflow_confirmation_and_confirm_api(
    agent_client: TestClient, tmp_path, monkeypatch
):
    """E2E: demo chat emits confirmation; reject/approve via /agent/confirm."""
    from dataclasses import replace
    from unittest.mock import MagicMock

    import app.core.config as cfg_mod
    from app.services.agent import agent_confirm as ac
    from app.services.agent import config_service as cs
    from app.services.agent import session_store as ss

    # create_app may re-bind DATA_ROOT via deployment.config.json — isolate Agent stores.
    data = tmp_path / "agent-iso"
    data.mkdir(exist_ok=True)
    new_settings = replace(cfg_mod.settings, data_root=str(data))
    cfg_mod.settings = new_settings
    monkeypatch.setattr("app.core.config.settings", new_settings)

    cs._save_store_unlocked(cs._global_profiles_path(), cs._empty_store())

    _login(agent_client, "testadmin", "test-pass-123")
    chat = agent_client.post(
        "/agent/chat",
        json={
            "message": "运行工作流",
            "client_context": {"active_catalog_ids": ["ndvi"]},
        },
    )
    assert chat.status_code == 200, chat.text
    body = chat.json()
    assert body.get("provider") == "demo", body
    assert body.get("confirmations"), body
    conf = body["confirmations"][0]
    cid = conf["confirmation_id"]
    assert conf.get("summary", {}).get("catalog_id") == "ndvi"

    reject = agent_client.post(
        "/agent/confirm",
        json={"confirmation_id": cid, "decision": "reject"},
    )
    assert reject.status_code == 200, reject.text
    assert reject.json()["status"] == "rejected"

    chat2 = agent_client.post(
        "/agent/chat",
        json={
            "message": "提交工作流",
            "client_context": {"active_catalog_ids": ["ndvi"]},
        },
    )
    assert chat2.status_code == 200, chat2.text
    cid2 = chat2.json()["confirmations"][0]["confirmation_id"]

    fake = MagicMock()
    fake.run_id = "run-testapprove01"
    fake.status_url = "/workflow-runs/run-testapprove01"

    with patch(
        "app.services.workflow.service_container.submission_service.submit_workflow",
        return_value=fake,
    ):
        ok = agent_client.post(
            "/agent/confirm",
            json={"confirmation_id": cid2, "decision": "approve"},
        )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"
    assert ok.json()["run_id"] == "run-testapprove01"


def test_agent_sessions_list_get_delete(agent_client: TestClient, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    from app.services.agent import session_store as ss

    _login(agent_client, "stduser", "std-pass-123")
    # Seed via chat so user_id matches session cookie
    r = agent_client.post(
        "/agent/chat",
        json={"message": "有哪些活动图层", "session_id": "sess-api-1"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    assert sid

    listed = agent_client.get("/agent/sessions")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["count"] >= 1
    assert any(s["session_id"] == sid for s in body["sessions"])

    got = agent_client.get(f"/agent/sessions/{sid}")
    assert got.status_code == 200, got.text
    assert got.json()["session_id"] == sid
    assert isinstance(got.json()["messages"], list)
    assert len(got.json()["messages"]) >= 1

    deleted = agent_client.delete(f"/agent/sessions/{sid}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["ok"] is True
    assert agent_client.get(f"/agent/sessions/{sid}").status_code == 404


def test_mock_orchestrator_unit():
    from app.services.agent.mock_orchestrator import mock_chat

    out = mock_chat(
        "定位到降水", client_context={"active_catalog_ids": ["cmfd-precip-cn"]}
    )
    assert out["ui_intents"][0]["name"] == "fit_layer"


def test_mock_orchestrator_fit_china_and_basemap_and_locate():
    from app.services.agent.mock_orchestrator import mock_chat

    china = mock_chat("缩放到中国全境")
    assert china["ui_intents"][0]["name"] == "fit_china"

    basemap = mock_chat("切换为天地图影像")
    assert basemap["ui_intents"][0]["name"] == "switch_basemap"
    assert basemap["ui_intents"][0]["args"]["basemap_id"] == "tianditu-img"

    city = mock_chat("定位到北京")
    assert city["ui_intents"][0]["name"] == "locate_coordinate"
    assert city["ui_intents"][0]["args"]["lng"] == pytest.approx(116.4074)
    assert city["ui_intents"][0]["args"]["lat"] == pytest.approx(39.9042)

    coord = mock_chat("定位到 116.4, 39.9")
    assert coord["ui_intents"][0]["name"] == "locate_coordinate"
    assert coord["ui_intents"][0]["args"]["lng"] == pytest.approx(116.4)


def test_mock_orchestrator_p1_timeline_remove_reorder():
    from app.services.agent.mock_orchestrator import mock_chat

    tl = mock_chat("时间设为 8 点")
    assert tl["ui_intents"][0]["name"] == "set_timeline"
    assert tl["ui_intents"][0]["args"]["hour"] == 8

    pause = mock_chat("暂停时间轴播放")
    assert pause["ui_intents"][0]["name"] == "set_timeline_playing"
    assert pause["ui_intents"][0]["args"]["playing"] is False

    rem = mock_chat(
        "移除图层降水",
        client_context={"active_catalog_ids": ["cmfd-precip-cn"]},
    )
    assert rem["ui_intents"][0]["name"] == "remove_layer"

    front = mock_chat(
        "将降水置顶",
        client_context={"active_catalog_ids": ["cmfd-precip-cn"]},
    )
    assert front["ui_intents"][0]["name"] == "reorder_layer"
    assert front["ui_intents"][0]["args"]["action"] == "front"


def test_normalize_intents_allows_map_viewport_aliases():
    from app.services.agent.orchestrator import _normalize_intents

    raw = [
        {"name": "fit_china", "args": {}},
        {"name": "zoom_to_china", "args": {}},
        {"name": "locate_coordinate", "args": {"lng": 1, "lat": 2}},
        {"name": "fly_to", "args": {"lng": 3, "lat": 4}},
        {"name": "switch_basemap", "args": {"basemap_id": "tianditu-img"}},
        {"name": "set_basemap", "args": {"source_id": "gaode-street"}},
        {"name": "set_timeline", "args": {"hour": 1}},
        {"name": "remove_layer", "args": {"catalog_id": "x"}},
        {"name": "not_a_real_intent", "args": {}},
    ]
    out = _normalize_intents(raw)
    names = [i["name"] for i in out]
    assert names == [
        "fit_china",
        "zoom_to_china",
        "locate_coordinate",
        "fly_to",
        "switch_basemap",
        "set_basemap",
        "set_timeline",
        "remove_layer",
    ]


def test_load_ui_intent_tools_includes_map_viewport():
    from app.services.agent.orchestrator import load_ui_intent_tools_openai

    tools = load_ui_intent_tools_openai()
    names = {t["function"]["name"] for t in tools}
    assert "fit_china" in names
    assert "locate_coordinate" in names
    assert "switch_basemap" in names
    assert "fit_layer" in names
    assert "set_timeline" in names
    assert "remove_layer" in names
    assert "set_layer_symbology" in names


def test_server_tools_p2_read_wrappers():
    from app.services.agent.server_tools_runtime import (
        ALLOWED_SERVER_TOOLS,
        execute_server_tool,
    )

    assert "list_workflow_runs" in ALLOWED_SERVER_TOOLS
    assert "get_workflow_run" in ALLOWED_SERVER_TOOLS
    assert "get_layer_coverage" in ALLOWED_SERVER_TOOLS
    assert "list_workflow_timers" in ALLOWED_SERVER_TOOLS

    # Non-admin without user → empty runs list (fail-closed)
    runs = execute_server_tool("list_workflow_runs", {"limit": 5}, cred=None)
    assert runs.get("ok") is True
    assert runs.get("runs") == []

    timers = execute_server_tool("list_workflow_timers", {}, cred=None)
    assert timers.get("ok") is False


def test_prepare_run_workflow_maps_time_range(monkeypatch):
    from types import SimpleNamespace

    from app.services.agent import server_tools_runtime as runtime

    class Cred:
        user_id = 1
        role = "admin"

    monkeypatch.setattr(
        runtime,
        "_filter_ids",
        lambda ids, cred: list(ids),
    )

    def fake_desc(cid: str):
        return SimpleNamespace(
            display_name="Demo",
            workflow_id="wf-demo",
            workflow_variants={
                "online": SimpleNamespace(workflow_id="wf-demo-online"),
            },
        )

    monkeypatch.setattr(
        "app.services.layer_catalog.get_layer_descriptor",
        fake_desc,
    )

    captured: dict = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return {
            "confirmation_id": "cid-test-12345678",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }

    monkeypatch.setattr(
        "app.services.agent.agent_confirm.create_confirmation",
        fake_create,
    )

    out = runtime.execute_server_tool(
        "run_workflow",
        {
            "catalog_id": "cmfd-precip-cn",
            "time_range": {
                "start": "2024-01-01T00:00:00+00:00",
                "end": "2024-01-02T00:00:00+00:00",
            },
            "workflow_variant": "online",
        },
        cred=Cred(),
    )
    assert out.get("needs_confirmation") is True
    assert "time_range" in (out.get("summary") or {})
    assert (out.get("summary") or {}).get("workflow_id") == "wf-demo-online"
    payload = captured.get("submit_payload") or {}
    assert payload.get("time_range") is not None


def test_prepare_run_workflow_rejects_bad_time_range_and_online(monkeypatch):
    from types import SimpleNamespace

    from app.services.agent import server_tools_runtime as runtime

    class Cred:
        user_id = 1
        role = "admin"

    monkeypatch.setattr(runtime, "_filter_ids", lambda ids, cred: list(ids))

    def fake_desc(_cid: str):
        return SimpleNamespace(
            display_name="Demo",
            workflow_id="wf-demo",
            workflow_variants={},
        )

    monkeypatch.setattr(
        "app.services.layer_catalog.get_layer_descriptor",
        fake_desc,
    )

    created = {"n": 0}

    def fake_create(**_kwargs):
        created["n"] += 1
        return {
            "confirmation_id": "cid-should-not",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }

    monkeypatch.setattr(
        "app.services.agent.agent_confirm.create_confirmation",
        fake_create,
    )

    incomplete = runtime.execute_server_tool(
        "run_workflow",
        {
            "catalog_id": "cmfd-precip-cn",
            "time_range": {"start": "2024-01-01T00:00:00+00:00"},
        },
        cred=Cred(),
    )
    assert incomplete.get("ok") is False
    assert "time_range" in str(incomplete.get("error") or "")
    assert created["n"] == 0

    bad_iso = runtime.execute_server_tool(
        "run_workflow",
        {
            "catalog_id": "cmfd-precip-cn",
            "time_range": {"start": "not-a-date", "end": "also-bad"},
        },
        cred=Cred(),
    )
    assert bad_iso.get("ok") is False
    assert created["n"] == 0

    online_missing = runtime.execute_server_tool(
        "run_workflow",
        {
            "catalog_id": "cmfd-precip-cn",
            "workflow_variant": "online",
        },
        cred=Cred(),
    )
    assert online_missing.get("ok") is False
    assert "online" in str(online_missing.get("error") or "").lower()
    assert created["n"] == 0


def test_get_workflow_run_fail_closed_without_uid(monkeypatch):
    from types import SimpleNamespace

    from app.services.agent import server_tools_runtime as runtime
    from app.services.workflow import service_container as sc

    class CredNoUid:
        user_id = None
        role = "standard"

    monkeypatch.setattr(
        sc.submission_service,
        "get_workflow_run",
        lambda _rid: SimpleNamespace(
            run_id="run-1",
            status=SimpleNamespace(value="succeeded"),
            layer_id="cmfd-precip-cn",
            command_label="x",
            progress=1.0,
            message=None,
            created_at=None,
            updated_at=None,
        ),
    )

    out = runtime.execute_server_tool(
        "get_workflow_run", {"run_id": "run-1"}, cred=CredNoUid()
    )
    assert out.get("ok") is False
    assert "未找到" in str(out.get("error") or "")


def test_agent_session_invalid_id_returns_404(agent_client: TestClient, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    _login(agent_client, "stduser", "std-pass-123")
    # Illegal chars must 404 (not 500)
    bad = agent_client.get("/agent/sessions/bad!id")
    assert bad.status_code == 404, bad.text
    bad_del = agent_client.delete("/agent/sessions/bad!id")
    assert bad_del.status_code == 422, bad_del.text


def test_session_store_anon_and_invalid_id(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    from app.services.agent import session_store as ss

    assert ss.list_sessions(user_id=None) == []
    assert ss.get_session_messages(user_id=None, session_id="sess-1") is None
    assert ss.delete_session(user_id=None, session_id="sess-1") is False
    assert ss.get_session_messages(user_id=1, session_id="bad!id") is None
    assert ss.delete_session(user_id=1, session_id="bad!id") is False


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


def test_admin_refresh_demo_models_ok(agent_client: TestClient):
    _login(agent_client, "testadmin", "test-pass-123")
    r = agent_client.post(
        "/agent/models/refresh",
        json={"profile_id": "demo", "scope": "global"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "demo-rules" in body["models"]
    assert body.get("error") in (None, "")


def test_admin_refresh_openai_upstream_error_is_200(agent_client: TestClient):
    """Upstream / SSRF failures must not become HTTP 500."""
    _login(agent_client, "testadmin", "test-pass-123")
    create = agent_client.post(
        "/agent/config/profiles",
        json={"preset_id": "openai", "scope": "global"},
    )
    assert create.status_code == 200, create.text
    pid = create.json()["id"]
    agent_client.put(
        f"/agent/config/profiles/{pid}",
        json={
            "scope": "global",
            "base_url": "http://127.0.0.1:9/v1",
            "api_key": "sk-test",
        },
    )
    with patch(
        "app.services.agent.clients.openai_compat.list_models",
        side_effect=Exception("boom"),
    ):
        r = agent_client.post(
            "/agent/models/refresh",
            json={"profile_id": pid, "scope": "global"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["models"] == []
    assert body["manual"] is True
    assert body.get("error")


def test_admin_refresh_passes_draft_api_key(agent_client: TestClient):
    """Unsaved API key in the settings form must be usable for refresh."""
    _login(agent_client, "testadmin", "test-pass-123")
    create = agent_client.post(
        "/agent/config/profiles",
        json={"preset_id": "openai", "scope": "global"},
    )
    assert create.status_code == 200, create.text
    pid = create.json()["id"]
    agent_client.put(
        f"/agent/config/profiles/{pid}",
        json={"scope": "global", "base_url": "http://127.0.0.1:9/v1"},
    )
    captured: dict[str, object] = {}

    def _fake_list_models(*, base_url: str, api_key: str | None, timeout: float = 30.0):
        captured["base_url"] = base_url
        captured["api_key"] = api_key
        return ["draft-model-a", "draft-model-b"]

    with patch(
        "app.services.agent.clients.openai_compat.list_models",
        side_effect=_fake_list_models,
    ):
        r = agent_client.post(
            "/agent/models/refresh",
            json={
                "profile_id": pid,
                "scope": "global",
                "base_url": "http://127.0.0.1:9/v1",
                "api_key": "sk-draft-unsaved",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["models"] == ["draft-model-a", "draft-model-b"]
    assert captured.get("api_key") == "sk-draft-unsaved"


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


def test_agent_chat_stream_sse_demo(agent_client: TestClient):
    _login(agent_client, "testadmin", "test-pass-123")
    # Earlier tests may leave a non-demo global profile active (shared data root).
    act = agent_client.post(
        "/agent/config/active",
        json={"profile_id": "demo", "scope": "global"},
    )
    assert act.status_code == 200, act.text
    events: list[tuple[str, dict]] = []
    with agent_client.stream(
        "POST",
        "/agent/chat/stream",
        json={"message": "打开 CMFD 降水"},
    ) as res:
        assert res.status_code == 200
        assert "text/event-stream" in (res.headers.get("content-type") or "")
        buf = ""
        for chunk in res.iter_text():
            buf += chunk
        blocks = [b for b in buf.split("\n\n") if b.strip()]
        for block in blocks:
            ev = "message"
            data_lines: list[str] = []
            for line in block.split("\n"):
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
            if not data_lines:
                continue
            events.append((ev, json.loads("\n".join(data_lines))))

    kinds = [e[0] for e in events]
    assert "done" in kinds, events
    assert "token" in kinds
    assert "intent" in kinds
    done = next(d for k, d in events if k == "done")
    assert done["reply"]
    assert done["ui_intents"]
    assert done["ui_intents"][0]["name"] == "set_layer_visibility"
    tokens = "".join(d.get("text", "") for k, d in events if k == "token")
    assert tokens == done["reply"]


def test_agent_chat_stream_error_event(agent_client: TestClient, monkeypatch):
    _login(agent_client, "testadmin", "test-pass-123")

    def boom(*_a, **_k):
        raise ValueError("故意失败")

    # Use the submodule object — package __init__ aliases `agent_router` to APIRouter,
    # so string path "app.api.routers.agent_router.run_chat" resolves incorrectly.
    import importlib

    ar_mod = importlib.import_module("app.api.routers.agent_router")
    monkeypatch.setattr(ar_mod, "run_chat", boom)
    with agent_client.stream(
        "POST",
        "/agent/chat/stream",
        json={"message": "hi"},
    ) as res:
        assert res.status_code == 200
        text = "".join(res.iter_text())
    assert "event: error" in text
    assert "故意失败" in text


def test_get_workflow_meta_and_sample_and_web_search(monkeypatch):
    from app.services.agent.server_tools_runtime import (
        ALLOWED_SERVER_TOOLS,
        execute_server_tool,
    )
    from app.services.agent import web_search as web_search_mod

    assert "get_workflow_meta" in ALLOWED_SERVER_TOOLS
    assert "sample_layer_point" in ALLOWED_SERVER_TOOLS
    assert "web_search" in ALLOWED_SERVER_TOOLS

    class _Cred:
        role = "admin"
        user_id = 1
        source = "session"

    lw = execute_server_tool("list_workflows", {"limit": 5}, cred=_Cred())
    assert lw["ok"] is True
    workflows = lw.get("workflows") or []
    if workflows:
        wid = workflows[0]["workflow_id"]
        meta = execute_server_tool(
            "get_workflow_meta", {"workflow_id": wid}, cred=_Cred()
        )
        assert meta["ok"] is True
        assert meta["workflow"]["workflow_id"] == wid
        assert "nodes" in meta["workflow"]

    missing_wf = execute_server_tool(
        "get_workflow_meta", {"workflow_id": ""}, cred=_Cred()
    )
    assert missing_wf["ok"] is False

    no_point = execute_server_tool(
        "sample_layer_point",
        {"catalog_id": "ndvi"},
        cred=_Cred(),
        client_context={},
    )
    assert no_point["ok"] is False

    sampled = execute_server_tool(
        "sample_layer_point",
        {"catalog_id": "ndvi"},
        cred=_Cred(),
        client_context={"map_point": {"lng": 113.3, "lat": 23.1}},
    )
    assert sampled["ok"] is True
    assert sampled["lng"] == 113.3
    assert sampled["lat"] == 23.1
    assert sampled["count"] >= 1
    assert isinstance(sampled.get("samples"), list)

    from_ctx_layers = execute_server_tool(
        "sample_layer_point",
        {},
        cred=_Cred(),
        client_context={
            "map_point": {"lng": 113.3, "lat": 23.1},
            "active_catalog_ids": ["ndvi"],
        },
    )
    assert from_ctx_layers["ok"] is True
    assert from_ctx_layers["count"] >= 1

    monkeypatch.setenv("BACKEND_AGENT_WEB_SEARCH_ENABLED", "false")
    disabled = execute_server_tool("web_search", {"query": "降水"}, cred=_Cred())
    assert disabled["ok"] is False
    assert "关闭" in str(disabled.get("error") or "")

    monkeypatch.setenv("BACKEND_AGENT_WEB_SEARCH_ENABLED", "true")

    def _fake_run(query: str, *, limit: int = 5):
        return {
            "ok": True,
            "query": query,
            "count": 1,
            "results": [
                {"title": "t", "snippet": "s", "url": "https://example.com/x"}
            ],
            "sources": ["test"],
        }

    monkeypatch.setattr(web_search_mod, "run_web_search", _fake_run)
    ws = execute_server_tool("web_search", {"query": "CMFD"}, cred=_Cred())
    assert ws["ok"] is True
    assert ws["count"] == 1


def test_sanitize_client_context_keeps_map_point():
    from app.services.agent.orchestrator import sanitize_client_context

    cleaned = sanitize_client_context(
        {
            "active_catalog_ids": ["ndvi"],
            "map_point": {"lng": 113.264385, "lat": 23.12911},
            "noise": {"x": 1},
        }
    )
    assert cleaned is not None
    assert cleaned["map_point"]["lng"] == 113.264385
    assert cleaned["map_point"]["lat"] == 23.12911
    assert "noise" not in cleaned

    bad = sanitize_client_context({"map_point": {"lng": 999, "lat": 0}})
    assert bad is None or "map_point" not in (bad or {})


def test_catalog_search_vs_list_active_heuristics():
    from app.services.agent.orchestrator import (
        _is_catalog_search_query,
        _is_list_active_layers_query,
        _synthesize_reply_from_tool_steps,
    )

    assert _is_list_active_layers_query("有哪些活动图层")
    assert _is_list_active_layers_query("当前图层有哪些")
    assert not _is_catalog_search_query("有哪些活动图层")
    assert _is_catalog_search_query("搜索图层 cmfd")
    assert _is_catalog_search_query("查找图层 降水")

    empty = _synthesize_reply_from_tool_steps(
        [
            {
                "type": "tool_result",
                "summary": "命中 0 条",
                "detail": json.dumps(
                    {"ok": True, "query": "有哪些活动图层", "count": 0, "layers": []},
                    ensure_ascii=False,
                ),
            }
        ]
    )
    assert empty is not None
    assert "未在图层库中找到" in empty
    assert "活动图层" in empty

    hits = _synthesize_reply_from_tool_steps(
        [
            {
                "type": "tool_result",
                "summary": "命中 1 条",
                "detail": json.dumps(
                    {
                        "ok": True,
                        "query": "cmfd",
                        "count": 1,
                        "layers": [
                            {
                                "layer_id": "cmfd-precip-cn",
                                "display_name": "CMFD 降水",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            }
        ]
    )
    assert hits is not None
    assert "cmfd-precip-cn" in hits
