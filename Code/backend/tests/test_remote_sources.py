"""Remote URI parsing + transport registry + config route auth."""
from __future__ import annotations

import sys
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parents[2]
for _p in (_CODE_ROOT / "algorithms" / "providers" / "Python", _CODE_ROOT):
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

    uri = build_connectivity_probe_uri("smb://files/datasets/a.tif?cred=p1", default_port=445)
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

    assert source_fetcher_registry.resolve("sftp://h/p").__class__.__name__ == "RemoteProtocolSourceFetcher"
    assert source_fetcher_registry.resolve("smb://h/share/p").__class__.__name__ == "RemoteProtocolSourceFetcher"
    assert source_fetcher_registry.resolve("s3://bucket/key").__class__.__name__ == "MinioSourceFetcher"


def test_remote_storage_routes_require_write_access():
    from app.api import config_routes
    from app.api.deps import require_write_access

    mutating = [
        route
        for route in config_routes.router.routes
        if getattr(route, "methods", None)
        and route.methods & {"PUT", "POST", "DELETE"}
        and "/remote-storage" in getattr(route, "path", "")
    ]
    assert mutating
    for route in mutating:
        calls = [d.call for d in (route.dependant.dependencies or []) if getattr(d, "call", None)]
        assert require_write_access in calls, route.path


def test_upsert_preserves_secret_extra_enabled(tmp_path, monkeypatch):
    from app.services.remote_storage_credentials_repository import RemoteStorageCredentialsRepository

    monkeypatch.setenv("BACKEND_ENVIRONMENT", "development")
    repo = RemoteStorageCredentialsRepository(tmp_path / "remote.sqlite3", encryption_key="")
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
