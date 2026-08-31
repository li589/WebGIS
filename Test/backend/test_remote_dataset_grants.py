"""远程数据集授权注册表（「具体数据集选取模式」白名单，plan 阶段 1）。

覆盖：CRUD、UNIQUE(portal_id, dataset_key) 幂等合并、enabled 开关、
path_prefix 解析、policy 投影（managed/compatible/datasets）。
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def grants_repo(tmp_path: Path):
    from app.services.remote_dataset_grants import RemoteDatasetGrantsRepository

    r = RemoteDatasetGrantsRepository(tmp_path / "grants.sqlite3")
    yield r
    r.close()


@pytest.fixture()
def grants_env(monkeypatch, grants_repo):
    from app.services import remote_dataset_grants as svc

    monkeypatch.setattr(svc, "_repo_instance", grants_repo)
    yield grants_repo


@pytest.fixture()
def policy_env(monkeypatch, tmp_path: Path, grants_repo):
    """grants + remote_sources（同库）双仓库环境，供 policy 投影测试。"""
    from app.services import remote_dataset_grants as grants_svc
    from app.services import remote_source_registry as sources_svc
    from app.services.remote_source_registry import RemoteSourceRegistryRepository

    sources_repo = RemoteSourceRegistryRepository(tmp_path / "grants.sqlite3")
    monkeypatch.setattr(grants_svc, "_repo_instance", grants_repo)
    monkeypatch.setattr(sources_svc, "_repo_instance", sources_repo)
    yield {"grants": grants_repo, "sources": sources_repo}
    sources_repo.close()


def test_upsert_validates_inputs(grants_repo) -> None:
    from app.services.remote_dataset_grants import RemoteDatasetGrantsError

    with pytest.raises(RemoteDatasetGrantsError, match="portal_id"):
        grants_repo.upsert(portal_id=" ", dataset_key="GLDAS_NOAH025_3H")
    with pytest.raises(RemoteDatasetGrantsError, match="dataset_key"):
        grants_repo.upsert(portal_id="nasa_gldas", dataset_key=" ")
    with pytest.raises(RemoteDatasetGrantsError, match="provider_kind"):
        grants_repo.upsert(
            portal_id="nasa_gldas",
            dataset_key="GLDAS_NOAH025_3H",
            provider_kind="galaxy",
        )
    with pytest.raises(RemoteDatasetGrantsError, match="search_meta"):
        grants_repo.upsert(
            portal_id="nasa_gldas",
            dataset_key="GLDAS_NOAH025_3H",
            search_meta="{not-json",
        )


def test_upsert_creates_and_merges_by_unique(grants_repo) -> None:
    """同 portal+dataset 幂等合并；grant_id 未指定时派生。"""
    entry = grants_repo.upsert(
        portal_id="nasa_gldas",
        dataset_key="GLDAS_NOAH025_3H",
        dataset_title="GLDAS Noah 0.25 deg",
        path_prefix="data/GLDAS_NOAH025_3H",
    )
    # grant_id 派生：portal__dataset
    assert entry["grant_id"] == "nasa_gldas__GLDAS_NOAH025_3H"
    assert entry["dataset_title"] == "GLDAS Noah 0.25 deg"
    created_at = entry["created_at"]

    # 同 portal+dataset 再 upsert（显式新 grant_id 也合并到既有条目）
    merged = grants_repo.upsert(
        portal_id="nasa_gldas",
        dataset_key="GLDAS_NOAH025_3H",
        dataset_title="GLDAS Noah L4 3 hourly 0.25 deg V2.1",
        time_start="2000-02-24T00:00:00Z",
    )
    assert merged["grant_id"] == "nasa_gldas__GLDAS_NOAH025_3H"
    assert merged["created_at"] == created_at  # created_at 保留
    assert "V2.1" in merged["dataset_title"]
    assert merged["time_start"] == "2000-02-24T00:00:00Z"

    # 同 portal 不同 dataset → 新条目
    other = grants_repo.upsert(
        portal_id="nasa_gldas", dataset_key="GLDAS_NOAH025_3H_D"
    )
    assert other["grant_id"] == "nasa_gldas__GLDAS_NOAH025_3H_D"

    assert len(grants_repo.list_entries()) == 2


def test_enabled_toggle_and_delete(grants_repo) -> None:
    entry = grants_repo.upsert(
        portal_id="nsidc_data", dataset_key="SPL3SMP_E_V6"
    )
    gid = entry["grant_id"]

    disabled = grants_repo.set_enabled(gid, False)
    assert disabled["enabled"] == 0

    re_enabled = grants_repo.set_enabled(gid, True)
    assert re_enabled["enabled"] == 1

    assert grants_repo.delete(gid) is True
    assert grants_repo.get(gid) is None
    assert grants_repo.delete(gid) is False


def test_parse_path_prefix() -> None:
    from app.services.remote_dataset_grants import parse_path_prefix

    assert parse_path_prefix("data/GLDAS\n /nsidc/SPL3SMP_E \n") == [
        "data/GLDAS",
        "nsidc/SPL3SMP_E",
    ]
    assert parse_path_prefix("") == []
    assert parse_path_prefix("///leading/slashes///") == ["leading/slashes"]


def test_policy_projection_managed_with_datasets(policy_env) -> None:
    from app.services.remote_dataset_grants import build_remote_dataset_policy

    policy_env["grants"].upsert(
        portal_id="nasa_gldas",
        dataset_key="GLDAS_NOAH025_3H",
        path_prefix="data/GLDAS_NOAH025_3H",
    )
    policy = {p["portal_id"]: p for p in build_remote_dataset_policy()}
    assert "nasa_gldas" in policy
    p = policy["nasa_gldas"]
    assert p["managed"] is True
    assert p["compatible"] is False  # 无 site_compatible 条目
    assert [d["dataset_key"] for d in p["datasets"]] == ["GLDAS_NOAH025_3H"]
    assert p["datasets"][0]["path_prefix"] == ["data/GLDAS_NOAH025_3H"]

    # 未列出的门户 = 未管控
    assert "nasa_cmr" not in policy


def test_policy_projection_compatible_only(policy_env) -> None:
    """仅有站点兼容开关（remote_path='' 的 portal 条目）→ managed + compatible。"""
    from app.services.remote_dataset_grants import build_remote_dataset_policy

    policy_env["sources"].upsert(
        remote_source_id="nasa-cmr-all",
        kind="portal",
        ref_id="nasa_cmr",
        remote_path="",
    )
    policy = {p["portal_id"]: p for p in build_remote_dataset_policy()}
    p = policy["nasa_cmr"]
    assert p["managed"] is True
    assert p["compatible"] is True
    assert p["datasets"] == []


def test_policy_projection_union_semantics(policy_env) -> None:
    """兼容开关 + 数据集授权并存（并集语义）。"""
    from app.services.remote_dataset_grants import build_remote_dataset_policy

    policy_env["sources"].upsert(
        remote_source_id="nasa-gldas-all",
        kind="portal",
        ref_id="nasa_gldas",
        remote_path="",
    )
    policy_env["grants"].upsert(
        portal_id="nasa_gldas", dataset_key="GLDAS_NOAH025_3H"
    )
    policy = {p["portal_id"]: p for p in build_remote_dataset_policy()}
    p = policy["nasa_gldas"]
    assert p["managed"] is True
    assert p["compatible"] is True
    assert len(p["datasets"]) == 1


def test_policy_projection_disabled_grant_excluded(policy_env) -> None:
    """停用/归档的 grant 不进策略（门户回到未管控或仅兼容态）。"""
    from app.services.remote_dataset_grants import build_remote_dataset_policy

    entry = policy_env["grants"].upsert(
        portal_id="nasa_gldas", dataset_key="GLDAS_NOAH025_3H"
    )
    policy_env["grants"].set_enabled(entry["grant_id"], False)
    policy = {p["portal_id"]: p for p in build_remote_dataset_policy()}
    assert "nasa_gldas" not in policy  # 唯一授权停用 → 未管控

    policy_env["grants"].set_enabled(entry["grant_id"], True)
    policy = {p["portal_id"]: p for p in build_remote_dataset_policy()}
    assert "nasa_gldas" in policy


def test_list_grants_with_badges(grants_env, monkeypatch) -> None:
    """徽标：portal 存在时 ref 带 search_capability；不存在时 ref=None。"""
    from app.services import remote_dataset_grants as svc

    # 内置门户 nasa_cmr 存在于 portal_catalog
    grants_env.upsert(
        portal_id="nasa_cmr",
        dataset_key="GLDAS_NOAH025_3H",
        provider_kind="cmr",
    )
    # 不存在的门户
    grants_env.upsert(portal_id="ghost_portal", dataset_key="X")

    items = {i["grant_id"]: i for i in svc.list_grants_with_badges()}
    cmr = items["nasa_cmr__GLDAS_NOAH025_3H"]
    assert cmr["ref_exists"] is True
    assert cmr["ref"]["search_capability"] == "cmr"
    ghost = items["ghost_portal__X"]
    assert ghost["ref_exists"] is False
    assert ghost["ref"] is None
