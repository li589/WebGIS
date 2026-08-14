"""Phase F：ssh_sync 节点 server_type=远程存储 profile 的解析链。"""

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

import contracts  # noqa: E402, F401 — 先导入 contracts 打断循环依赖


@pytest.fixture()
def storage_repo(monkeypatch, tmp_path):
    from app.services.remote_storage_credentials_repository import (
        RemoteStorageCredentialsRepository,
    )

    repo = RemoteStorageCredentialsRepository(tmp_path / "rs.sqlite3", encryption_key="")
    monkeypatch.setattr(
        "app.services.config_remote_storage._get_remote_storage_repository",
        lambda: repo,
    )
    return repo


def _resolve(profile_id: str):
    from modules.download_nodes import _resolve_profile_server_config

    return _resolve_profile_server_config(profile_id)


def test_resolve_sftp_profile_with_secret(storage_repo):
    storage_repo.upsert(
        profile_id="lab-hpc",
        protocol="sftp",
        host="172.16.98.184",
        port=22,
        username="likr6008",
        secret="pw",
    )
    cfg = _resolve("lab-hpc")
    assert cfg.server_type == "hpc"
    assert cfg.host == "172.16.98.184"
    assert cfg.port == 22
    assert cfg.username == "likr6008"
    assert cfg.password == "pw"
    assert cfg.private_key_pem == ""


def test_resolve_filebrowser_profile_uses_extra_base_url(storage_repo):
    storage_repo.upsert(
        profile_id="lab-nas",
        protocol="filebrowser",
        host="",
        username="u",
        secret="p",
        extra={"base_url": "https://nas.local"},
    )
    cfg = _resolve("lab-nas")
    assert cfg.server_type == "nas"
    assert cfg.filebrowser_url == "https://nas.local"
    assert cfg.username == "u" and cfg.password == "p"


def test_resolve_honors_manual_alt_path(storage_repo):
    storage_repo.upsert(
        profile_id="lab-hpc",
        protocol="sftp",
        host="172.16.98.184",
        port=22,
        username="u",
        secret="p",
        extra={
            "alt": {"host": "tunnel.example.org", "port": 2222},
            "fallback_mode": "manual",
            "failover_state": {"active": "alt"},
        },
    )
    cfg = _resolve("lab-hpc")
    assert cfg.host == "tunnel.example.org"
    assert cfg.port == 2222


def test_resolve_filebrowser_alt_url(storage_repo):
    storage_repo.upsert(
        profile_id="lab-nas",
        protocol="filebrowser",
        host="",
        username="u",
        secret="p",
        extra={
            "base_url": "https://nas.local",
            "alt": {"url": "https://nas.personaltunnel.dpdns.org"},
            "failover_state": {"active": "alt"},
        },
    )
    cfg = _resolve("lab-nas")
    assert cfg.filebrowser_url == "https://nas.personaltunnel.dpdns.org"


def test_resolve_rejects_unsupported_protocol(storage_repo):
    storage_repo.upsert(profile_id="lab-smb", protocol="smb", host="files")
    with pytest.raises(ValueError, match="不支持 ssh_sync"):
        _resolve("lab-smb")


def test_resolve_missing_or_disabled_profile(storage_repo):
    with pytest.raises(ValueError, match="不存在或已禁用"):
        _resolve("ghost")
    storage_repo.upsert(
        profile_id="off-fb", protocol="filebrowser", host="", enabled=False
    )
    with pytest.raises(ValueError, match="不存在或已禁用"):
        _resolve("off-fb")


def test_sftp_connect_accepts_private_key_pem(monkeypatch):
    """_sftp_connect：private_key_pem → pkey=（优先级 key_filename > pem > password）。"""
    import io

    from ingest import remote_sync

    paramiko = remote_sync._get_paramiko()
    key = paramiko.RSAKey.generate(2048)
    buf = io.StringIO()
    key.write_private_key(buf)
    pem = buf.getvalue()

    connect_kwargs: dict = {}

    class _FakeClient:
        def set_missing_host_key_policy(self, _):
            pass

        def connect(self, **kwargs):
            connect_kwargs.update(kwargs)

        def open_sftp(self):
            return object()

    monkeypatch.setattr(paramiko, "SSHClient", lambda: _FakeClient())

    cfg = remote_sync.ServerConfig(
        server_type="hpc",
        host="h1",
        port=22,
        username="u",
        password="pw",
        private_key_pem=pem,
    )
    remote_sync._sftp_connect(cfg)

    assert "pkey" in connect_kwargs
    assert "password" not in connect_kwargs
    assert connect_kwargs["look_for_keys"] is False

    # 无 PEM 时回落 password
    connect_kwargs.clear()
    remote_sync._sftp_connect(
        remote_sync.ServerConfig(
            server_type="hpc", host="h1", port=22, username="u", password="pw"
        )
    )
    assert connect_kwargs["password"] == "pw"
