"""存量迁移 remote_sources 文件级条目 → 数据集授权（plan 阶段 3/6）。

覆盖：_infer_dataset 推断矩阵、dry_run 安全、site_compatible 升级、
grants 写入+归档、legacy 保留、safe 模式、幂等性、ALTER 幂等。
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def dual_repo(tmp_path: Path):
    """同时初始化 remote_sources（ALTER 后）与 remote_dataset_grants 双表环境。"""
    from app.services.remote_dataset_grants import RemoteDatasetGrantsRepository
    from app.services.remote_source_registry import RemoteSourceRegistryRepository

    # 同库路径（模拟 research_data_settings.sqlite3）
    db = tmp_path / "research_data_settings.sqlite3"
    sources = RemoteSourceRegistryRepository(db)
    grants = RemoteDatasetGrantsRepository(db)
    yield {"sources": sources, "grants": grants, "db": db}
    sources.close()
    grants.close()


@pytest.fixture()
def migrate_env(monkeypatch, dual_repo):
    from app.services import remote_dataset_grants as grants_svc
    from app.services import remote_source_migration as migr_svc
    from app.services import remote_source_registry as sources_svc

    monkeypatch.setattr(grants_svc, "_repo_instance", dual_repo["grants"])
    monkeypatch.setattr(sources_svc, "_repo_instance", dual_repo["sources"])
    yield dual_repo


# ── _infer_dataset 推断矩阵 ──────────────────────────────────────────────────


def test_infer_dataset_builtins():
    from app.services.remote_source_migration import _infer_dataset

    # GLDAS
    key, prefix = _infer_dataset("nasa_gldas", "data/GLDAS_NOAH025_3H/2025")
    assert key == "GLDAS_NOAH025_3H"
    assert "GLDAS" in prefix

    # NSIDC
    key, prefix = _infer_dataset("nsidc_data", "nsidc-cumulus-prod-protected/SPL3SMP_E/2025")
    assert key == "SPL3SMP_E"
    assert "SPL3SMP_E" in prefix

    # FY3D_MWRID（双组模式）
    key, prefix = _infer_dataset("cma_nsmc", "FY3D_MWRID_20251201")
    assert key == "FY3D_MWRID"
    assert prefix == "FY3D"  # path_prefix 取 group(1)

    # NOMADS
    key, prefix = _infer_dataset("noaa_nomads", "gfs/20251201/gfs.t00z.pgrb2.0p25")
    assert key == "GFS"
    assert "gfs" in prefix.lower() or "GFS" in prefix


def test_infer_dataset_generic_shortname():
    from app.services.remote_source_migration import _infer_dataset

    key, prefix = _infer_dataset("unknown_portal", "MOD09GQ/2025")
    assert key == "MOD09GQ"
    assert prefix == "MOD09GQ"


def test_infer_dataset_fallback():
    from app.services.remote_source_migration import _infer_dataset

    assert _infer_dataset("unknown_portal", "random/path") is None
    assert _infer_dataset("unknown_portal", "") is None


# ── migrate_legacy_remote_sources 场景测试 ───────────────────────────────────


def test_migrate_dry_run_no_writes(migrate_env):
    from app.services.remote_source_migration import migrate_legacy_remote_sources

    migrate_env["sources"].upsert(
        remote_source_id="gldas-old",
        kind="portal",
        ref_id="nasa_gldas",
        remote_path="data/GLDAS_NOAH025_3H/2025",
    )
    report = migrate_legacy_remote_sources(dry_run=True)
    assert report["dry_run"] is True
    assert report["migrated_to_grants"] == 1
    # dry_run 不落库
    assert migrate_env["grants"].find(
        portal_id="nasa_gldas", dataset_key="GLDAS_NOAH025_3H"
    ) is None
    entry = migrate_env["sources"].get("gldas-old")
    assert entry["access_mode"] == "legacy"
    assert entry["archived"] == 0


def test_migrate_site_compatible_upgrades(migrate_env):
    from app.services.remote_source_migration import migrate_legacy_remote_sources

    migrate_env["sources"].upsert(
        remote_source_id="cmr-all",
        kind="portal",
        ref_id="nasa_cmr",
        remote_path="",
    )
    migrate_env["sources"].upsert(
        remote_source_id="nas-profile",
        kind="storage_profile",
        ref_id="nas",
    )
    report = migrate_legacy_remote_sources()
    assert report["upgraded_site_compatible"] >= 2
    assert report["already_done"] is False
    cmr = migrate_env["sources"].get("cmr-all")
    assert cmr["access_mode"] == "site_compatible"
    nas = migrate_env["sources"].get("nas-profile")
    assert nas["access_mode"] == "site_compatible"


def test_migrate_grants_created(migrate_env):
    from app.services.remote_source_migration import migrate_legacy_remote_sources

    migrate_env["sources"].upsert(
        remote_source_id="gldas-2025",
        kind="portal",
        ref_id="nasa_gldas",
        remote_path="data/GLDAS_NOAH025_3H/2025",
    )
    report = migrate_legacy_remote_sources()
    assert report["migrated_to_grants"] == 1
    g = migrate_env["grants"].find(
        portal_id="nasa_gldas", dataset_key="GLDAS_NOAH025_3H"
    )
    assert g is not None
    assert g["migrated_from"] == "gldas-2025"
    src = migrate_env["sources"].get("gldas-2025")
    assert src["archived"] == 1


def test_migrate_kept_legacy_on_fail(migrate_env):
    from app.services.remote_source_migration import migrate_legacy_remote_sources

    migrate_env["sources"].upsert(
        remote_source_id="unknown-x",
        kind="portal",
        ref_id="unknown_portal",
        remote_path="random/path.json",
    )
    report = migrate_legacy_remote_sources()
    assert report["kept_legacy"] == 1
    entry = migrate_env["sources"].get("unknown-x")
    assert entry["access_mode"] == "legacy"
    assert entry["archived"] == 0


def test_migrate_safe_mode(migrate_env):
    from app.services.remote_source_migration import migrate_legacy_remote_sources

    migrate_env["sources"].upsert(
        remote_source_id="unknown-s",
        kind="portal",
        ref_id="unknown_portal",
        remote_path="random/path.json",
    )
    report = migrate_legacy_remote_sources(safe=True)
    assert report["kept_legacy"] == 0
    assert report["upgraded_site_compatible"] == 1
    entry = migrate_env["sources"].get("unknown-s")
    assert entry["access_mode"] == "site_compatible"


def test_migrate_idempotent(migrate_env):
    from app.services.remote_source_migration import migrate_legacy_remote_sources

    migrate_env["sources"].upsert(
        remote_source_id="gldas-a",
        kind="portal",
        ref_id="nasa_gldas",
        remote_path="data/GLDAS_NOAH025_3H",
    )
    report1 = migrate_legacy_remote_sources()
    assert report1["already_done"] is False
    assert report1["migrated_to_grants"] == 1

    report2 = migrate_legacy_remote_sources()
    assert report2["already_done"] is True
    assert report2["migrated_to_grants"] == 0


def test_migrate_alter_schema_idempotent(dual_repo):
    """_ensure_column 第二次调用不报错（幂等）。"""
    from app.services.remote_source_registry import RemoteSourceRegistryRepository

    # 第二次初始化同库（复用同 db 路径）——验证 _init_schema ALTER 幂等
    repo2 = RemoteSourceRegistryRepository(dual_repo["db"])
    try:
        # 无异常 = ALTER 幂等成功
        entry = repo2.get("nonexistent")
        assert entry is None
    finally:
        repo2.close()
