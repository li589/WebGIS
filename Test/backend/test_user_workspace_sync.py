"""Per-user workspace sync: store 单元测试 + /workspace 路由鉴权与并发语义。

跨设备同步契约：
- payload 对服务端不透明（version/snapshot/dismissed）；
- revision 乐观并发：base_revision 不符 → 409 + 服务端现状；
- demo 只读（GET 可，PUT/DELETE 403）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_CODE_ROOT = Path(__file__).resolve().parents[2]
for _p in (_CODE_ROOT / "algorithms" / "providers" / "Python", _CODE_ROOT):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


# ── store 单元测试 ──────────────────────────────────────────────────────────


def _payload(tag: str = "a") -> dict:
    return {
        "version": 1,
        "snapshot": {
            "version": 1,
            "savedAt": f"2026-08-17T00:00:0{len(tag) % 10}",
            "layers": [],
            "groups": [],
            "tag": tag,
        },
        "dismissed": {"overlayLayerIds": [], "catalogIds": [], "runIds": [], "vectorBackendLayerIds": []},
    }


def test_store_roundtrip_and_revision_increment(tmp_path):
    from app.services.user_workspace_store import UserWorkspaceStore

    store = UserWorkspaceStore(tmp_path / "ws.sqlite3")
    empty = store.get(7)
    assert empty.revision == 0
    assert empty.payload is None

    rec1 = store.put(7, _payload("a"))
    assert rec1.revision == 1
    rec2 = store.put(7, _payload("b"))
    assert rec2.revision == 2

    got = store.get(7)
    assert got.revision == 2
    assert got.payload is not None
    assert got.payload["snapshot"]["tag"] == "b"


def test_store_conflict_on_stale_base_revision(tmp_path):
    from app.services.user_workspace_store import UserWorkspaceStore, WorkspaceConflictError

    store = UserWorkspaceStore(tmp_path / "ws.sqlite3")
    store.put(7, _payload("a"))
    with pytest.raises(WorkspaceConflictError) as exc_info:
        store.put(7, _payload("b"), base_revision=0)  # 服务端已是 1
    assert exc_info.value.server_revision == 1

    fresh = store.put(7, _payload("c"), base_revision=1)
    assert fresh.revision == 2


def test_store_rejects_oversized_payload(tmp_path):
    from app.services.user_workspace_store import (
        MAX_PAYLOAD_BYTES,
        UserWorkspaceStore,
        WorkspacePayloadTooLargeError,
    )

    store = UserWorkspaceStore(tmp_path / "ws.sqlite3")
    huge = _payload()
    huge["blob"] = "x" * (MAX_PAYLOAD_BYTES + 1)
    with pytest.raises(WorkspacePayloadTooLargeError):
        store.put(7, huge)


def test_store_delete(tmp_path):
    from app.services.user_workspace_store import UserWorkspaceStore

    store = UserWorkspaceStore(tmp_path / "ws.sqlite3")
    store.put(7, _payload())
    store.delete(7)
    assert store.get(7).revision == 0
    assert store.get(7).payload is None


# ── /workspace 路由测试 ─────────────────────────────────────────────────────


@pytest.fixture()
def ws_client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_USER_AUTH_ENABLED", "true")
    monkeypatch.setenv("BACKEND_ADMIN_USERNAME", "wsadmin")
    monkeypatch.setenv("BACKEND_ADMIN_PASSWORD", "ws-pass-12345")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))

    import app.core.config as cfg_mod
    from app.core.config import Settings
    from dataclasses import replace

    cfg_mod.settings = replace(
        Settings(),
        admin_username="wsadmin",
        admin_password="ws-pass-12345",
        environment="test",
    )
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)

    from app.services import user_repository as ur_mod
    from app.services.user_repository import UserRepository
    from app.services.user_workspace_store import UserWorkspaceStore

    repo = UserRepository(tmp_path / "state" / "users.sqlite3")
    ws_store = UserWorkspaceStore(tmp_path / "state" / "users.sqlite3")

    from app.main import create_app
    from app.services import user_workspace_store as ws_mod
    from app.services.auth_bootstrap import bootstrap_auth
    from app.services.effective_config import hydrate_effective_config

    with patch.object(ur_mod, "_repo", repo), patch.object(ws_mod, "_store", ws_store):
        hydrate_effective_config()
        bootstrap_auth()
        with TestClient(create_app()) as client:
            yield client


def _login(client: TestClient, username: str, password: str) -> None:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text


def _get(client: TestClient):
    resp = client.get("/workspace")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _put(client: TestClient, payload: dict, base_revision: int | None = None):
    body: dict = {"payload": payload}
    if base_revision is not None:
        body["base_revision"] = base_revision
    return client.put("/workspace", json=body)


def test_workspace_requires_session(ws_client: TestClient):
    resp = ws_client.get("/workspace")
    assert resp.status_code == 401


def test_workspace_put_get_roundtrip_with_revision(ws_client: TestClient):
    _login(ws_client, "wsadmin", "ws-pass-12345")

    first = _get(ws_client)
    assert first["revision"] == 0
    assert first["payload"] is None

    resp = _put(ws_client, _payload("a"), base_revision=0)
    assert resp.status_code == 200, resp.text
    assert resp.json()["revision"] == 1

    got = _get(ws_client)
    assert got["revision"] == 1
    assert got["payload"]["snapshot"]["tag"] == "a"

    resp = _put(ws_client, _payload("b"), base_revision=1)
    assert resp.json()["revision"] == 2


def test_workspace_conflict_returns_409_with_server_state(ws_client: TestClient):
    _login(ws_client, "wsadmin", "ws-pass-12345")
    _put(ws_client, _payload("a"), base_revision=0)

    stale = _put(ws_client, _payload("b"), base_revision=0)
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["revision"] == 1


def test_workspace_demo_role_readonly(ws_client: TestClient):
    _login(ws_client, "wsadmin", "ws-pass-12345")
    ws_client.post(
        "/auth/users", json={"username": "demouser", "password": "demo-pass-12345", "role": "demo"}
    )
    ws_client.cookies.clear()
    _login(ws_client, "demouser", "demo-pass-12345")

    assert ws_client.get("/workspace").status_code == 200
    resp = _put(ws_client, _payload("demo"))
    assert resp.status_code == 403
    assert ws_client.delete("/workspace").status_code == 403


def test_workspace_delete_clears(ws_client: TestClient):
    _login(ws_client, "wsadmin", "ws-pass-12345")
    _put(ws_client, _payload("a"))
    resp = ws_client.delete("/workspace")
    assert resp.status_code == 204
    assert _get(ws_client)["revision"] == 0
