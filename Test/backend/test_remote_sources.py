"""Remote URI parsing + transport registry + config route auth."""

from __future__ import annotations

import sys
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parents[2]
# 注意必须带 Code/ 前缀：mat2py editable finder 只映射 data_access 等包、
# 不映射 path_utils 等顶层模块，故必须显式挂上真实 provider 根目录。
for _p in (
    _CODE_ROOT / "Code" / "algorithms" / "providers" / "Python",
    _CODE_ROOT,
):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


def test_parse_sftp_uri_with_cred():
    from shared.remote_sources.uri import parse_remote_uri

    parsed = parse_remote_uri("sftp://user@nas.local:2222/data/a.tif?cred=nas-lab")
    assert parsed.scheme == "sftp"
    assert parsed.host == "nas.local"
    assert parsed.port == 2222
    assert parsed.username == "user"
    assert parsed.path == "/data/a.tif"
    assert parsed.cred_profile == "nas-lab"


def test_parse_smb_share():
    from shared.remote_sources.uri import parse_remote_uri

    parsed = parse_remote_uri("smb://fileserver/datasets/soil/x.hdf?cred=smb1")
    assert parsed.share == "datasets"
    assert parsed.path_without_share == "soil/x.hdf"


def test_reject_path_traversal():
    from shared.remote_sources.uri import parse_remote_uri
    import pytest

    with pytest.raises(ValueError, match="traversal"):
        parse_remote_uri("sftp://host/../../etc/passwd?cred=x")


def test_reject_password_in_uri():
    from shared.remote_sources.uri import parse_remote_uri
    import pytest

    with pytest.raises(ValueError, match="Passwords embedded"):
        parse_remote_uri("sftp://user:secret@host/path?cred=x")


def test_redact_uri_strips_cred():
    from shared.remote_sources.uri import redact_uri

    redacted = redact_uri("sftp://user@host:22/data?cred=nas-lab")
    assert "nas-lab" not in redacted
    assert "cred=" in redacted and "***" in redacted.replace("%2A", "*")
    assert "user@" not in redacted


def test_connectivity_probe_uri_uses_share_and_port():
    from shared.remote_sources.uri import build_connectivity_probe_uri

    uri = build_connectivity_probe_uri(
        "smb://files/datasets/a.tif?cred=p1", default_port=445
    )
    assert uri.startswith("smb://files:445/datasets/")
    assert "cred=p1" in uri


def test_effective_port_prefers_uri_then_auth():
    from shared.remote_sources.protocol import RemoteAuth, effective_port
    from shared.remote_sources.uri import parse_remote_uri

    parsed = parse_remote_uri("sftp://host/data?cred=x")
    auth = RemoteAuth(port=2222)
    assert effective_port(parsed, auth, 22) == 2222
    parsed_port = parse_remote_uri("sftp://host:29/data?cred=x")
    assert effective_port(parsed_port, auth, 22) == 29


def test_transport_registry_has_first_batch_schemes():
    from shared.remote_sources.registry import get_default_transport_registry

    schemes = set(get_default_transport_registry().registered_schemes())
    assert {"sftp", "smb", "ftp", "ftps", "gs"}.issubset(schemes)


def test_data_access_registers_remote_schemes():
    from data_access.registry import build_default_source_registry

    schemes = set(build_default_source_registry().registered_schemes())
    assert {"sftp", "smb", "ftp", "gs"}.issubset(schemes)


def test_source_fetcher_supports_remote_and_s3():
    from app.services.source_fetcher import source_fetcher_registry

    assert (
        source_fetcher_registry.resolve("sftp://h/p").__class__.__name__
        == "RemoteProtocolSourceFetcher"
    )
    assert (
        source_fetcher_registry.resolve("smb://h/share/p").__class__.__name__
        == "RemoteProtocolSourceFetcher"
    )
    assert (
        source_fetcher_registry.resolve("s3://bucket/key").__class__.__name__
        == "MinioSourceFetcher"
    )


def test_remote_storage_routes_require_write_access():
    from app.api import config_routes
    from app.api.deps import require_config_management_access, require_write_access

    # RBAC v2: 高危配置路由可使用 require_config_management_access（admin 级）
    # 替代 require_write_access，二者均提供写保护。
    accepted_write_guards = {require_write_access, require_config_management_access}

    # 浏览/搜索为只读 POST（不落库不改配置），standard 角色可用（read 权限）
    read_only_post = {
        "/config/remote-storage/{profile_id}/browse",
        "/config/remote-storage/{profile_id}/search",
    }

    mutating = [
        route
        for route in config_routes.router.routes
        if getattr(route, "methods", None)
        and route.methods & {"PUT", "POST", "DELETE"}
        and "/remote-storage" in getattr(route, "path", "")
        and route.path not in read_only_post
    ]
    assert mutating
    for route in mutating:
        calls = [
            d.call
            for d in (route.dependant.dependencies or [])
            if getattr(d, "call", None)
        ]
        assert accepted_write_guards & set(calls), route.path


def test_upsert_preserves_secret_extra_enabled(tmp_path, monkeypatch):
    from app.services.remote_storage_credentials_repository import (
        RemoteStorageCredentialsRepository,
    )

    monkeypatch.setenv("BACKEND_ENVIRONMENT", "development")
    repo = RemoteStorageCredentialsRepository(
        tmp_path / "remote.sqlite3", encryption_key=""
    )
    repo.upsert(
        profile_id="nas",
        protocol="sftp",
        host="NAS.LOCAL",
        port=2222,
        username="u",
        secret="s3cret",
        extra={"host_key_policy": "auto_add"},
        enabled=False,
    )
    # Preserve secret/extra/enabled when omitted (None)
    repo.upsert(
        profile_id="nas",
        protocol="sftp",
        host="nas.local",
        port=2222,
        username="u2",
        secret=None,
        extra=None,
        enabled=None,
    )
    bundle = repo.get_secret_bundle("nas", include_disabled=True)
    assert bundle is not None
    assert bundle["secret"] == "s3cret"
    assert bundle["extra"].get("host_key_policy") == "auto_add"
    assert bundle["enabled"] is False
    assert bundle["username"] == "u2"

    found = repo.find_by_host_protocol("sftp", "nas.local")
    # disabled profiles are not matched by host lookup
    assert found is None
    repo.set_enabled("nas", True)
    found = repo.find_by_host_protocol("sftp", "NAS.local")
    assert found is not None
    assert found["port"] == 2222


# ── 算法包 RemoteSource：双路径回退 ──────────────────────────────────────────


class _FakeStat:
    size = 10


def _install_fake_download(monkeypatch, behavior):
    """behavior(uri) -> ('ok', stat) | ('raise', exc)；记录调用顺序。"""
    from data_access.sources import remote as remote_mod

    calls: list[str] = []

    def fake_download(uri, auth, *, target_dir, max_bytes):
        calls.append(uri)
        action = behavior(uri)
        if action[0] == "raise":
            raise action[1]
        return Path(str(target_dir)) / "staged.tif", action[1]

    monkeypatch.setattr(remote_mod, "download_remote_uri", fake_download)
    return remote_mod, calls


def _auth_with_alt(fallback_mode: str = "auto"):
    from shared.remote_sources.protocol import RemoteAuth

    return RemoteAuth(
        username="u",
        extra={
            "alt_json": '{"host": "tunnel.example.com", "port": 2222}',
            "fallback_mode": fallback_mode,
        },
    )


def test_remote_source_alt_retry_on_network_error(monkeypatch, tmp_path):
    remote_mod, calls = _install_fake_download(
        monkeypatch,
        lambda uri: (
            ("raise", ConnectionRefusedError("primary unreachable"))
            if "primary.host" in uri
            else ("ok", _FakeStat())
        ),
    )
    src = remote_mod.RemoteSource()
    ref = src.locate(
        "sftp://primary.host:22/data/a.tif?cred=nas",
        metadata={"auth": _auth_with_alt()},
    )
    result = src.materialize(ref, target_dir=tmp_path)

    assert len(calls) == 2
    assert calls[0].startswith("sftp://primary.host:22/")
    assert "tunnel.example.com:2222" in calls[1]
    assert "?cred=nas" in calls[1]
    assert result.metadata["remote_size"] == 10


# ── http/https 存储源连通性探测（_probe_http_connectivity） ─────────────────


class _ProbeResp:
    def __init__(self, status: int):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _install_probe(monkeypatch, handler):
    """Patch safe_urlopen + resolve_remote_auth；返回 (method, url, headers) 调用记录。"""
    from types import SimpleNamespace

    import app.core.ssrf as ssrf_mod
    import app.services.remote_auth_resolver as auth_mod
    from app.services import config_remote_storage as svc

    calls: list[tuple[str, str, dict]] = []

    def fake_safe_urlopen(url, timeout=None, headers=None, method="GET"):
        calls.append((method, url, dict(headers or {})))
        return handler(method, url)

    monkeypatch.setattr(ssrf_mod, "safe_urlopen", fake_safe_urlopen)
    monkeypatch.setattr(
        auth_mod,
        "resolve_remote_auth",
        lambda _uri: SimpleNamespace(username="u", password="p"),
    )
    return svc, calls


def test_probe_http_success_strips_cred_and_adds_basic_auth(monkeypatch):
    svc, calls = _install_probe(monkeypatch, lambda method, _url: _ProbeResp(200))

    uri = "https://data.example.org/dir/index.html?cred=nas-lab"
    assert svc._probe_http_connectivity(uri) == uri

    assert len(calls) == 1
    method, url, headers = calls[0]
    assert method == "HEAD"
    # 内部 cred 标记参数必须剥离，凭据以 Basic Auth 头携带
    assert "cred=" not in url
    assert url == "https://data.example.org/dir/index.html"
    assert headers.get("Authorization", "").startswith("Basic ")


def test_probe_http_falls_back_to_get_on_405(monkeypatch):
    from urllib.error import HTTPError

    def handler(method, url):
        if method == "HEAD":
            raise HTTPError(url, 405, "Method Not Allowed", None, None)
        return _ProbeResp(204)

    svc, calls = _install_probe(monkeypatch, handler)

    assert svc._probe_http_connectivity("https://data.example.org/") == "https://data.example.org/"
    assert [m for m, _, _ in calls] == ["HEAD", "GET"]


def test_probe_http_terminal_status_raises(monkeypatch):
    import pytest
    from urllib.error import HTTPError

    def handler(method, url):
        raise HTTPError(url, 404, "Not Found", None, None)

    svc, calls = _install_probe(monkeypatch, handler)

    with pytest.raises(ConnectionError, match="404"):
        svc._probe_http_connectivity("https://data.example.org/missing")
    # 终态 404 不做 GET 退化
    assert [m for m, _, _ in calls] == ["HEAD"]


def test_remote_source_no_alt_reraises_network_error(monkeypatch, tmp_path):
    import pytest

    from shared.remote_sources.protocol import RemoteAuth

    remote_mod, calls = _install_fake_download(
        monkeypatch,
        lambda uri: ("raise", ConnectionRefusedError("down")),
    )
    src = remote_mod.RemoteSource()
    ref = src.locate(
        "sftp://primary.host:22/data/a.tif?cred=nas",
        metadata={"auth": RemoteAuth(username="u")},
    )
    with pytest.raises(ConnectionRefusedError):
        src.materialize(ref, target_dir=tmp_path)
    assert len(calls) == 1


def test_remote_source_manual_mode_no_retry(monkeypatch, tmp_path):
    import pytest

    remote_mod, calls = _install_fake_download(
        monkeypatch,
        lambda uri: ("raise", ConnectionRefusedError("down")),
    )
    src = remote_mod.RemoteSource()
    ref = src.locate(
        "sftp://primary.host:22/data/a.tif?cred=nas",
        metadata={"auth": _auth_with_alt(fallback_mode="manual")},
    )
    with pytest.raises(ConnectionRefusedError):
        src.materialize(ref, target_dir=tmp_path)
    assert len(calls) == 1


def test_remote_source_auth_error_not_retried(monkeypatch, tmp_path):
    import pytest

    remote_mod, calls = _install_fake_download(
        monkeypatch,
        lambda uri: ("raise", ValueError("SMB 认证失败")),
    )
    src = remote_mod.RemoteSource()
    ref = src.locate(
        "sftp://primary.host:22/data/a.tif?cred=nas",
        metadata={"auth": _auth_with_alt()},
    )
    with pytest.raises(ValueError, match="认证失败"):
        src.materialize(ref, target_dir=tmp_path)
    assert len(calls) == 1
