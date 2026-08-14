"""remote_access 浏览/搜索分发 + 双路径回退 + 凭据仓库扩展协议。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

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


# ── FakeRepo：跳过 SQLite/加密，直供 browser 所需 bundle ─────────────────────


class FakeRepo:
    def __init__(self, bundle: dict, info: dict | None = None):
        self._bundle = bundle
        self._info = info or {
            "profile_id": bundle["profile_id"],
            "enabled": bool(bundle.get("enabled", True)),
            "extra": bundle.get("extra") or {},
        }
        self.failover_writes: list[dict] = []

    def get_profile_info(self, profile_id: str):
        return self._info if self._info.get("profile_id") == profile_id else None

    def get_secret_bundle(self, profile_id: str, **_):
        return self._bundle if self._bundle["profile_id"] == profile_id else None

    def set_failover_state(self, profile_id: str, state: dict) -> bool:
        self.failover_writes.append(dict(state))
        return True


def _install_repo(monkeypatch, repo: FakeRepo):
    from app.services.remote_access import browser

    monkeypatch.setattr(browser, "_get_repository", lambda: repo)
    return browser


def _lan_bundle(tmp_path: Path, **extra) -> dict:
    return {
        "profile_id": "nas-lan",
        "protocol": "lan",
        "host": str(tmp_path),
        "port": None,
        "username": None,
        "secret": "",
        "private_key_pem": None,
        "domain": None,
        "extra": extra,
        "enabled": True,
    }


# ── 路径规范化 ───────────────────────────────────────────────────────────────


def test_normalize_remote_path_rejects_traversal_and_controls():
    from app.services.remote_access.browser import (
        RemoteAccessError,
        normalize_remote_path,
    )

    assert normalize_remote_path("") == "/"
    assert normalize_remote_path("a\\b\\c") == "/a/b/c"
    assert normalize_remote_path("/../etc") == "/etc"  # 前导 /.. 被 normpath 安全折叠
    with pytest.raises(RemoteAccessError):
        normalize_remote_path("../../etc")
    with pytest.raises(RemoteAccessError):
        normalize_remote_path("/a/\x00b")
    with pytest.raises(RemoteAccessError):
        normalize_remote_path("/a\x1bb")


# ── lan 协议浏览 ─────────────────────────────────────────────────────────────


def test_browse_lan_profile_lists_dir(tmp_path, monkeypatch):
    (tmp_path / "sub").mkdir()
    (tmp_path / "file.tif").write_bytes(b"x" * 10)

    repo = FakeRepo(_lan_bundle(tmp_path))
    browser = _install_repo(monkeypatch, repo)
    result = browser.browse_profile("nas-lan", "/")

    assert result["protocol"] == "lan"
    assert result["via"] == "primary"
    names = {item["name"] for item in result["items"]}
    assert names == {"sub", "file.tif"}
    by_name = {item["name"]: item for item in result["items"]}
    assert by_name["sub"]["is_dir"] is True
    assert by_name["file.tif"]["size"] == 10


def test_browse_unknown_or_disabled_profile(tmp_path, monkeypatch):
    bundle = _lan_bundle(tmp_path)
    bundle["enabled"] = False
    repo = FakeRepo(bundle)
    browser = _install_repo(monkeypatch, repo)
    with pytest.raises(browser.RemoteAccessError, match="不存在"):
        browser.browse_profile("missing", "/")
    with pytest.raises(browser.RemoteAccessError, match="禁用"):
        browser.browse_profile("nas-lan", "/")


# ── 双路径回退 ───────────────────────────────────────────────────────────────


def test_browse_failover_auto_switches_to_alt(tmp_path, monkeypatch):
    alt_dir = tmp_path / "tunnel"
    alt_dir.mkdir()
    bundle = _lan_bundle(
        tmp_path / "intranet-missing",
        alt={"host": str(alt_dir)},
        fallback_mode="auto",
    )
    repo = FakeRepo(bundle)
    browser = _install_repo(monkeypatch, repo)

    # 主路径目录不存在——_entries_local 对不存在路径抛 RemoteAccessError，
    # 这里模拟网络级失败以驱动 auto 回退
    original = browser._entries_local
    state = {"primary_failed": False}

    def fake_entries(b, target, path):
        if target["host"] == str(tmp_path / "intranet-missing"):
            state["primary_failed"] = True
            raise browser.RemoteAccessNetworkError("primary unreachable")
        return original(b, target, path)

    monkeypatch.setattr(browser, "_entries_local", fake_entries)
    result = browser.browse_profile("nas-lan", "/")

    assert state["primary_failed"] is True
    assert result["via"] == "alt"
    assert repo.failover_writes and repo.failover_writes[-1].get("active") == "alt"


def test_browse_auth_error_does_not_failover(tmp_path, monkeypatch):
    bundle = _lan_bundle(tmp_path, alt={"host": str(tmp_path)}, fallback_mode="auto")
    repo = FakeRepo(bundle)
    browser = _install_repo(monkeypatch, repo)

    def fake_entries(b, target, path):
        raise browser.RemoteAccessAuthError("认证失败")

    monkeypatch.setattr(browser, "_entries_local", fake_entries)
    with pytest.raises(browser.RemoteAccessAuthError):
        browser.browse_profile("nas-lan", "/")
    assert repo.failover_writes == []


def test_browse_manual_mode_pins_alt(tmp_path, monkeypatch):
    alt_dir = tmp_path / "tunnel"
    alt_dir.mkdir()
    bundle = _lan_bundle(
        tmp_path,
        alt={"host": str(alt_dir)},
        fallback_mode="manual",
        failover_state={"active": "alt"},
    )
    repo = FakeRepo(bundle)
    browser = _install_repo(monkeypatch, repo)
    calls: list[str] = []

    original = browser._entries_local

    def fake_entries(b, target, path):
        calls.append(target["host"])
        return original(b, target, path)

    monkeypatch.setattr(browser, "_entries_local", fake_entries)
    result = browser.browse_profile("nas-lan", "/")

    assert calls == [str(alt_dir)]
    assert result["via"] == "alt"


def test_browse_off_mode_never_uses_alt(tmp_path, monkeypatch):
    alt_dir = tmp_path / "tunnel"
    alt_dir.mkdir()
    bundle = _lan_bundle(tmp_path, alt={"host": str(alt_dir)}, fallback_mode="off")
    repo = FakeRepo(bundle)
    browser = _install_repo(monkeypatch, repo)

    def fake_entries(b, target, path):
        if target["host"] == str(alt_dir):
            raise AssertionError("off 模式不应访问备用路径")
        raise browser.RemoteAccessNetworkError("primary unreachable")

    monkeypatch.setattr(browser, "_entries_local", fake_entries)
    with pytest.raises(browser.RemoteAccessNetworkError):
        browser.browse_profile("nas-lan", "/")


# ── 搜索 ─────────────────────────────────────────────────────────────────────


def test_search_lan_profile_matches_names(tmp_path, monkeypatch):
    (tmp_path / "FY3D_2025").mkdir()
    (tmp_path / "FY3D_2025" / "a.mat").write_bytes(b"x")
    (tmp_path / "SMAP").mkdir()
    (tmp_path / "readme.txt").write_text("x")

    repo = FakeRepo(_lan_bundle(tmp_path))
    browser = _install_repo(monkeypatch, repo)
    result = browser.search_profile("nas-lan", "fy3d")

    assert result["query"] == "fy3d"
    names = [item["name"] for item in result["items"]]
    assert "FY3D_2025" in names
    assert "SMAP" not in names


def test_search_rejects_empty_query(tmp_path, monkeypatch):
    repo = FakeRepo(_lan_bundle(tmp_path))
    browser = _install_repo(monkeypatch, repo)
    with pytest.raises(browser.RemoteAccessError, match="不能为空"):
        browser.search_profile("nas-lan", "  ")


def test_search_unsupported_protocol(tmp_path, monkeypatch):
    bundle = _lan_bundle(tmp_path)
    bundle["protocol"] = "http"
    repo = FakeRepo(bundle)
    browser = _install_repo(monkeypatch, repo)
    with pytest.raises(browser.RemoteAccessError, match="不支持名称搜索"):
        browser.search_profile("nas-lan", "q")


# ── filebrowser ──────────────────────────────────────────────────────────────


class _FakeFileBrowserClient:
    calls: list[tuple[str, str]] = []

    def __init__(self, base_url, username, password, **_):
        self.base = base_url

    def list_dir(self, path):
        _FakeFileBrowserClient.calls.append(("list", self.base))
        return [{"name": "data", "is_dir": True, "size": 0}]

    def search(self, query, *, max_results=200):
        _FakeFileBrowserClient.calls.append(("search", self.base))
        return [{"name": f"{query}.mat", "is_dir": False, "size": 5}]


def test_browse_filebrowser_uses_client(tmp_path, monkeypatch):
    bundle = _lan_bundle(tmp_path)
    bundle["protocol"] = "filebrowser"
    bundle["host"] = "http://nas.local:8080"
    bundle["username"] = "u"
    bundle["secret"] = "p"
    bundle["extra"] = {}
    repo = FakeRepo(bundle)
    browser = _install_repo(monkeypatch, repo)
    monkeypatch.setattr(browser, "FileBrowserClient", _FakeFileBrowserClient)

    result = browser.browse_profile("nas-lan", "/")
    assert result["protocol"] == "filebrowser"
    assert result["items"] == [{"name": "data", "is_dir": True, "size": 0}]
    assert ("list", "http://nas.local:8080") in _FakeFileBrowserClient.calls

    search = browser.search_profile("nas-lan", "fy")
    assert search["items"][0]["name"] == "fy.mat"


def test_browser_repository_import_wiring(monkeypatch, tmp_path):
    """回归：browser._get_repository 的导入路径必须真实可用（曾引用不存在的公开名）。"""
    from app.services import config_remote_storage
    from app.services.remote_access import browser

    repo = _make_repo(tmp_path)
    monkeypatch.setattr(
        config_remote_storage, "_get_remote_storage_repository", lambda: repo
    )
    # 不 monkeypatch browser._get_repository，走真实导入链
    assert browser._get_repository() is repo


# ── 凭据仓库：扩展协议 + 双路径持久化 ───────────────────────────────────────


def _make_repo(tmp_path):
    from app.services.remote_storage_credentials_repository import (
        RemoteStorageCredentialsRepository,
    )

    return RemoteStorageCredentialsRepository(
        tmp_path / "remote.sqlite3", encryption_key=""
    )


def test_repository_accepts_extended_protocols(tmp_path):
    repo = _make_repo(tmp_path)
    for protocol in ("ssh", "http", "https", "filebrowser", "lan", "nfs"):
        repo.upsert(profile_id=f"p-{protocol}", protocol=protocol, host="x")
    protocols = {p["protocol"] for p in repo.list_profiles()}
    assert {"ssh", "http", "filebrowser", "lan", "nfs"} <= protocols


def test_repository_validates_alt_and_fallback_mode(tmp_path):
    repo = _make_repo(tmp_path)
    with pytest.raises(ValueError, match="fallback_mode"):
        repo.upsert(
            profile_id="bad",
            protocol="sftp",
            host="h",
            extra={"fallback_mode": "sometimes"},
        )
    with pytest.raises(ValueError, match="alt"):
        repo.upsert(
            profile_id="bad2",
            protocol="sftp",
            host="h",
            extra={"alt": "not-a-dict"},
        )
    repo.upsert(
        profile_id="ok",
        protocol="sftp",
        host="h",
        extra={"alt": {"host": "tunnel", "port": 2222}, "fallback_mode": "manual"},
    )
    bundle = repo.get_secret_bundle("ok")
    assert bundle["extra"]["alt"] == {"host": "tunnel", "port": 2222}
    assert bundle["extra"]["fallback_mode"] == "manual"


def test_repository_set_failover_state_merges(tmp_path):
    repo = _make_repo(tmp_path)
    repo.upsert(profile_id="p", protocol="sftp", host="h", extra={"default_share": "d"})
    assert repo.set_failover_state("p", {"active": "alt", "last_error": "timeout"})
    assert repo.set_failover_state("p", {"last_failover_at": "2026-01-01T00:00:00"})
    extra = repo.get_profile_info("p")["extra"]
    assert extra["default_share"] == "d"
    assert extra["failover_state"]["active"] == "alt"
    assert extra["failover_state"]["last_error"] == "timeout"
    assert extra["failover_state"]["last_failover_at"] == "2026-01-01T00:00:00"
    assert repo.set_failover_state("missing", {"active": "alt"}) is False


# ── config_remote_storage：合并语义 + 手动切换 ───────────────────────────────


def _patch_service_repo(monkeypatch, tmp_path):
    from app.services import config_remote_storage

    repo = _make_repo(tmp_path)
    monkeypatch.setattr(
        config_remote_storage, "_get_remote_storage_repository", lambda: repo
    )
    return config_remote_storage, repo


def test_upsert_service_merges_alt_preserving_extra(monkeypatch, tmp_path):
    svc, repo = _patch_service_repo(monkeypatch, tmp_path)

    svc.upsert_remote_storage_profile(
        "nas",
        protocol="smb",
        host="nas.local",
        extra={"default_share": "data"},
        secret="pw",
    )
    svc.upsert_remote_storage_profile(
        "nas",
        protocol="smb",
        host="nas.local",
        extra=None,
        alt_host="tunnel.example.com",
        alt_port=4445,
        fallback_mode="manual",
    )
    info = svc.get_remote_storage_profile("nas")
    assert info["extra"]["default_share"] == "data"
    assert info["alt_host"] == "tunnel.example.com"
    assert info["alt_port"] == 4445
    assert info["fallback_mode"] == "manual"
    assert info["failover_state"] == {}
    # 密码保留
    assert repo.get_secret_bundle("nas")["secret"] == "pw"


def test_upsert_service_extra_explicit_clear_then_alt(monkeypatch, tmp_path):
    svc, _ = _patch_service_repo(monkeypatch, tmp_path)
    svc.upsert_remote_storage_profile(
        "p", protocol="sftp", host="h", extra={"default_share": "d"}
    )
    svc.upsert_remote_storage_profile(
        "p", protocol="sftp", host="h", extra={}, alt_url="https://t.example"
    )
    info = svc.get_remote_storage_profile("p")
    assert "default_share" not in info["extra"]
    assert info["alt_url"] == "https://t.example"


def test_probe_failover_requires_alt(monkeypatch, tmp_path):
    svc, _ = _patch_service_repo(monkeypatch, tmp_path)
    svc.upsert_remote_storage_profile("p", protocol="sftp", host="h")
    with pytest.raises(ValueError, match="未配置备用"):
        svc.probe_failover("p", "alt")
    result = svc.probe_failover("p", "primary")
    assert result["active"] == "primary"

    svc.upsert_remote_storage_profile("p", protocol="sftp", host="h", alt_host="t")
    result = svc.probe_failover("p", "alt")
    assert result["active"] == "alt"
    state = svc.get_remote_storage_profile("p")["failover_state"]
    assert state["active"] == "alt"
    assert "last_failover_at" in state
    with pytest.raises(ValueError, match="primary|alt"):
        svc.probe_failover("p", "both")


def test_build_probe_uri_by_protocol():
    from app.services.config_remote_storage import _build_probe_uri

    assert _build_probe_uri("filebrowser", "http://x", None, {}) is None
    assert _build_probe_uri("lan", r"\\nas\share", None, {}) is None
    assert _build_probe_uri("sftp", "h", 22, {}) == "sftp://h:22/"
    assert _build_probe_uri("gs", "bucket", 443, {}) == "gs://bucket/"
    assert _build_probe_uri("smb", "h", None, {"default_share": "d"}) == "smb://h/d/"
    assert _build_probe_uri("smb", "h", None, {}) == "MISSING_SMB_SHARE"
    assert (
        _build_probe_uri("https", "https://x.example", None, {}) == "https://x.example"
    )
    assert _build_probe_uri("http", "plain-host", 8080, {}) == "http://plain-host:8080/"
