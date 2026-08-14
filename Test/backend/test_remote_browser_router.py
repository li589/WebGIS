"""remote_browser_router：profile 模式（远程与存储）分支。

/api/remote/{list,test,servers} 在 server 非 hpc/win11/nas 时
按「远程与存储」profile id 分发：
- list → remote_access.browser.browse_profile（双路径回退）
- test → config_service.test_remote_storage_profile
- servers → list_remote_storage_profiles 并入目录
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (
    _REPO_ROOT / "Code" / "backend",
    _REPO_ROOT / "Code",
    _REPO_ROOT / "algorithms" / "providers" / "Python",
):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)

from app.api.deps import require_write_access  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture()
def client():
    app = create_app()
    app.dependency_overrides[require_write_access] = lambda: None
    with TestClient(app) as c:
        yield c


def test_list_profile_delegates_to_browse_profile(client, monkeypatch):
    from app.services.remote_access import browser

    calls: list[tuple[str, str]] = []

    def fake_browse(profile_id: str, path: str = "/"):
        calls.append((profile_id, path))
        return {
            "profile_id": profile_id,
            "protocol": "sftp",
            "path": path,
            "via": "primary",
            "items": [
                {"name": "data", "is_dir": True, "size": 0},
                {"name": "a.h5", "is_dir": False, "size": 128},
            ],
        }

    monkeypatch.setattr(browser, "browse_profile", fake_browse)

    resp = client.get("/api/remote/list", params={"server": "lab-hpc", "path": "/pub"})

    assert resp.status_code == 200
    assert calls == [("lab-hpc", "/pub")]
    body = resp.json()
    assert body["server"] == "lab-hpc"
    assert body["path"] == "/pub"
    assert {"name": "data", "isDir": True, "size": 0} in body["items"]
    assert {"name": "a.h5", "isDir": False, "size": 128} in body["items"]


def test_list_profile_maps_sanitized_errors(client, monkeypatch):
    from app.services.remote_access import browser

    def raise_auth(_profile_id: str, _path: str = "/"):
        raise browser.RemoteAccessAuthError("SSH/SFTP 认证失败")

    monkeypatch.setattr(browser, "browse_profile", raise_auth)

    resp = client.get("/api/remote/list", params={"server": "lab-hpc", "path": "/"})

    assert resp.status_code == 403
    assert resp.json()["detail"] == "SSH/SFTP 认证失败"

    def raise_missing(_profile_id: str, _path: str = "/"):
        raise browser.RemoteAccessError("数据源不存在: lab-hpc")

    monkeypatch.setattr(browser, "browse_profile", raise_missing)
    resp = client.get("/api/remote/list", params={"server": "lab-hpc", "path": "/"})
    assert resp.status_code == 400


def test_list_profile_rejects_traversal(client, monkeypatch):
    from app.services.remote_access import browser

    seen: dict[str, str] = {}

    def fake_browse(profile_id: str, path: str = "/"):
        seen["path"] = path
        return {"profile_id": profile_id, "protocol": "sftp", "path": path, "items": []}

    monkeypatch.setattr(browser, "browse_profile", fake_browse)

    # 相对 ../ 在 normpath 后仍保留 .. 前缀 → 400（与遗留分支共用同一校验器）
    resp = client.get("/api/remote/list", params={"server": "lab-hpc", "path": "../etc"})

    assert resp.status_code == 400
    assert "path" not in seen


def test_test_profile_delegates_to_config_service(client, monkeypatch):
    from app.services import config_service

    monkeypatch.setattr(
        config_service,
        "test_remote_storage_profile",
        lambda pid, uri=None: {
            "profile_id": pid,
            "success": True,
            "message": "ok via primary",
            "tested_at": "2026-08-15T00:00:00+00:00",
        },
    )

    resp = client.get("/api/remote/test", params={"server": "lab-nas"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["server"] == "lab-nas"
    assert body["error"] is None

    monkeypatch.setattr(
        config_service,
        "test_remote_storage_profile",
        lambda pid, uri=None: {
            "profile_id": pid,
            "success": False,
            "message": "Profile not found: lab-nas",
            "tested_at": "2026-08-15T00:00:00+00:00",
        },
    )
    resp = client.get("/api/remote/test", params={"server": "lab-nas"})
    body = resp.json()
    assert body["ok"] is False
    assert "not found" in str(body["error"])


def test_servers_includes_enabled_profiles(client, monkeypatch):
    from app.services import config_remote_storage

    monkeypatch.setattr(
        config_remote_storage,
        "list_remote_storage_profiles",
        lambda include_disabled=True: [
            {
                "profile_id": "lab-nas",
                "protocol": "filebrowser",
                "host": "",
                "port": None,
                "enabled": True,
                "display_name": "实验室 NAS",
                "extra": {"base_url": "https://nas.local"},
            },
            {
                "profile_id": "off-smb",
                "protocol": "smb",
                "host": "files",
                "port": None,
                "enabled": False,
                "display_name": "停用共享",
                "extra": {},
            },
        ],
    )

    resp = client.get("/api/remote/servers")

    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()["servers"]]
    assert "lab-nas" in names
    assert "off-smb" not in names
    profile = next(s for s in resp.json()["servers"] if s["name"] == "lab-nas")
    assert profile["server_type"] == "profile"
    assert profile["protocol"] == "filebrowser"
    assert profile["url"] == "https://nas.local"
    assert profile["display_name"] == "实验室 NAS"
