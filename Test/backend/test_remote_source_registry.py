"""Phase C：可访问远程数据源注册表（别名 + 能力徽标）。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def repo(tmp_path: Path):
    from app.services.remote_source_registry import RemoteSourceRegistryRepository

    r = RemoteSourceRegistryRepository(tmp_path / "remote_sources.sqlite3")
    yield r
    r.close()


@pytest.fixture()
def registry_env(monkeypatch, repo):
    from app.services import remote_source_registry as svc

    monkeypatch.setattr(svc, "_repo_instance", repo)
    yield repo


def test_upsert_validates_inputs(repo) -> None:
    from app.services.remote_source_registry import RemoteSourceRegistryError

    with pytest.raises(RemoteSourceRegistryError, match="remote_source_id"):
        repo.upsert(remote_source_id="  ", kind="portal", ref_id="nasa_cmr")
    with pytest.raises(RemoteSourceRegistryError, match="kind"):
        repo.upsert(remote_source_id="x", kind="ftp", ref_id="nasa_cmr")
    with pytest.raises(RemoteSourceRegistryError, match="ref_id"):
        repo.upsert(remote_source_id="x", kind="portal", ref_id=" ")
    with pytest.raises(RemoteSourceRegistryError, match="cache_policy"):
        repo.upsert(
            remote_source_id="x",
            kind="portal",
            ref_id="nasa_cmr",
            cache_policy="always",
        )


def test_upsert_creates_and_updates(repo) -> None:
    entry = repo.upsert(
        remote_source_id="nas-fy-2025-12",
        kind="storage_profile",
        ref_id="nas",
        remote_path="/fy4/FY4A",
        display_name="NAS FY-4 数据",
    )
    assert entry["remote_source_id"] == "nas-fy-2025-12"
    assert entry["kind"] == "storage_profile"
    assert entry["cache_policy"] == "standard"
    created_at = entry["created_at"]

    updated = repo.upsert(
        remote_source_id="nas-fy-2025-12",
        kind="storage_profile",
        ref_id="nas",
        remote_path="/fy4/FY4B",
        display_name="NAS FY-4（新）",
        cache_policy="aggressive",
    )
    assert updated["remote_path"] == "/fy4/FY4B"
    assert updated["cache_policy"] == "aggressive"
    assert updated["created_at"] == created_at  # 更新保留创建时间
    assert len(repo.list_entries()) == 1


def test_delete(repo) -> None:
    repo.upsert(remote_source_id="p1", kind="portal", ref_id="nasa_cmr")
    assert repo.delete("p1") is True
    assert repo.delete("p1") is False
    assert repo.list_entries() == []


def test_capabilities_badges_for_storage_profile(monkeypatch, registry_env) -> None:
    from app.services import remote_source_registry as svc

    registry_env.upsert(
        remote_source_id="lab-nas",
        kind="storage_profile",
        ref_id="nas",
        remote_path="/data",
    )
    monkeypatch.setattr(
        "app.services.config_remote_storage.list_remote_storage_profiles",
        lambda include_disabled=True: [
            {
                "profile_id": "nas",
                "protocol": "smb",
                "enabled": True,
                "last_test_status": "ok",
                "display_name": "实验室 NAS",
            }
        ],
    )

    entries = svc.list_remote_sources_with_capabilities()
    assert len(entries) == 1
    item = entries[0]
    assert item["ref_exists"] is True
    assert item["ref"]["protocol"] == "smb"
    assert item["ref"]["enabled"] is True
    assert item["ref"]["last_test_status"] == "ok"


def test_capabilities_badges_for_portal(monkeypatch, registry_env) -> None:
    from app.services import remote_source_registry as svc
    from app.services.portal_catalog import DEFAULT_PORTAL_CATALOG

    registry_env.upsert(
        remote_source_id="cmr-granules",
        kind="portal",
        ref_id="nasa_cmr",
        remote_path="MOD09GQ.061/",
    )
    monkeypatch.setattr(
        "app.services.config_remote_storage.list_remote_storage_profiles",
        lambda include_disabled=True: [],
    )
    monkeypatch.setattr(
        "app.services.portal_catalog.list_portal_defs",
        lambda repo=None: {"nasa_cmr": DEFAULT_PORTAL_CATALOG["nasa_cmr"]},
    )

    entries = svc.list_remote_sources_with_capabilities()
    item = entries[0]
    assert item["ref_exists"] is True
    assert item["ref"]["search_capability"] == "cmr"
    assert item["ref"]["protocol"] == "http"


def test_missing_ref_marks_ref_exists_false(monkeypatch, registry_env) -> None:
    from app.services import remote_source_registry as svc

    registry_env.upsert(
        remote_source_id="ghost",
        kind="storage_profile",
        ref_id="deleted-profile",
    )
    monkeypatch.setattr(
        "app.services.config_remote_storage.list_remote_storage_profiles",
        lambda include_disabled=True: [],
    )
    monkeypatch.setattr(
        "app.services.portal_catalog.list_portal_defs",
        lambda repo=None: {},
    )

    entries = svc.list_remote_sources_with_capabilities()
    assert entries[0]["ref"] is None
    assert entries[0]["ref_exists"] is False


def test_config_service_wrappers(registry_env) -> None:
    from app.services import config_service

    entry = config_service.upsert_remote_source_entry(
        "lab-nas",
        {
            "kind": "storage_profile",
            "ref_id": "nas",
            "remote_path": "/data",
            "display_name": "NAS",
        },
    )
    assert entry["remote_source_id"] == "lab-nas"

    with pytest.raises(ValueError, match="kind"):
        config_service.upsert_remote_source_entry(
            "bad", {"kind": "ftp", "ref_id": "x"}
        )

    assert config_service.delete_remote_source_entry("lab-nas") is True
    assert config_service.delete_remote_source_entry("lab-nas") is False
