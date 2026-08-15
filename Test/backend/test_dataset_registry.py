"""Phase C：可用数据集注册表（dataset registry）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _patch_setting(request, monkeypatch, name: str, value) -> None:
    """settings 为 frozen dataclass，需 object.__setattr__ 打补丁（测试后恢复）。"""
    from app.core.config import settings

    old = getattr(settings, name)
    object.__setattr__(settings, name, value)
    request.addfinalizer(lambda: object.__setattr__(settings, name, old))


@pytest.fixture()
def registry(tmp_path: Path):
    from app.services.dataset_registry_service import DatasetRegistryRepository

    repo = DatasetRegistryRepository(tmp_path / "datasets.sqlite3")
    yield repo
    repo.close()


@pytest.fixture()
def registry_env(tmp_path: Path, monkeypatch, registry):
    """模块级 get_dataset_registry() 指向临时仓库（覆盖 _repo_instance 单例）。"""
    from app.services import dataset_registry_service as svc

    monkeypatch.setattr(svc, "_repo_instance", registry)
    yield registry


def test_upsert_and_get_roundtrip(registry) -> None:
    entry = registry.upsert(
        dataset_id=None,
        logical_name="SMAP_L3",
        path="Soil_Moisture/SMAP",
        file_format="h5",
        variables=["soil_moisture", "soil_temp"],
        time_range="2020-01-01~2021-01-01",
        resolution="9 km",
        tags=["soil", "smap"],
        description="SMAP L3 土壤水分",
        source="manual",
    )
    assert entry["dataset_id"]
    assert entry["source"] == "manual"
    assert entry["enabled"] is True
    assert entry["variables"] == ["soil_moisture", "soil_temp"]
    assert entry["tags"] == ["soil", "smap"]

    fetched = registry.get_by_logical_name("SMAP_L3")
    assert fetched is not None and fetched["dataset_id"] == entry["dataset_id"]
    assert registry.get(entry["dataset_id"]) is not None


def test_upsert_requires_logical_name_and_path(registry) -> None:
    from app.services.dataset_registry_service import DatasetRegistryError

    with pytest.raises(DatasetRegistryError, match="logical_name"):
        registry.upsert(dataset_id=None, logical_name="  ", path="x")
    with pytest.raises(DatasetRegistryError, match="path"):
        registry.upsert(dataset_id=None, logical_name="X", path="")


def test_logical_name_conflict_rejected(registry) -> None:
    from app.services.dataset_registry_service import DatasetRegistryError

    first = registry.upsert(dataset_id=None, logical_name="A", path="a")
    # 显式不同 dataset_id 复用他人 logical_name → 拒绝
    with pytest.raises(DatasetRegistryError, match="already used"):
        registry.upsert(
            dataset_id="other-id", logical_name="A", path="b", source="manual"
        )
    # dataset_id=None 同名 = 按 logical_name 更新（sync 路径），不报错
    updated = registry.upsert(dataset_id=None, logical_name="A", path="a2")
    assert updated["dataset_id"] == first["dataset_id"]
    assert updated["path"] == "a2"


def test_builtin_entries_protected(registry) -> None:
    from app.services.dataset_registry_service import DatasetRegistryError

    entry = registry.upsert(
        dataset_id=None,
        logical_name="SMAP_L3",
        path="Soil_Moisture/SMAP",
        source="algorithm_registry",
    )
    # 改名被拒
    with pytest.raises(DatasetRegistryError, match="cannot be renamed"):
        registry.upsert(
            dataset_id=entry["dataset_id"],
            logical_name="SMAP_L4",
            path="Soil_Moisture/SMAP",
        )
    # 删除被拒
    with pytest.raises(DatasetRegistryError, match="cannot be deleted"):
        registry.delete(entry["dataset_id"])
    # path 覆盖允许
    updated = registry.upsert(
        dataset_id=entry["dataset_id"],
        logical_name="SMAP_L3",
        path="Override/SMAP",
    )
    assert updated["path"] == "Override/SMAP"
    assert updated["source"] == "algorithm_registry"


def test_update_preserves_source(registry) -> None:
    entry = registry.upsert(
        dataset_id=None, logical_name="SCANNED", path="x/y", source="scan"
    )
    updated = registry.upsert(
        dataset_id=entry["dataset_id"],
        logical_name="SCANNED",
        path="x/y2",
        source="manual",  # 忽略：更新不改 source
    )
    assert updated["source"] == "scan"
    assert updated["path"] == "x/y2"


def test_disable_hides_entry(registry) -> None:
    registry.upsert(
        dataset_id=None, logical_name="D1", path="d1", source="manual", enabled=False
    )
    visible = registry.list_entries(include_disabled=False)
    assert all(e["logical_name"] != "D1" for e in visible)
    assert any(e["logical_name"] == "D1" for e in registry.list_entries())


# ── 算法包同步 ────────────────────────────────────────────────────────────────


_FAKE_DATASET_CONFIG = """
from types import SimpleNamespace

DATASET_REGISTRY = {
    "TEST_SMAP": SimpleNamespace(
        relative_path="Soil_Moisture/SMAP",
        variables=("soil_moisture",),
        time_range=("2020-01-01", "2021-01-01"),
        resolution="9 km",
        tags=("soil",),
        file_format="h5",
        description="fake smap",
    ),
    "NO_PATH": SimpleNamespace(description="skip me"),
}
"""


def test_sync_algorithm_datasets(tmp_path: Path, monkeypatch, request, registry_env) -> None:
    from app.services import dataset_registry_service as svc

    provider_root = tmp_path / "provider"
    provider_root.mkdir()
    (provider_root / "dataset_config.py").write_text(
        _FAKE_DATASET_CONFIG, encoding="utf-8"
    )
    _patch_setting(request, monkeypatch, "python_provider_root", str(provider_root))
    # 防止已导入的 dataset_config 缓存干扰（测试后由 monkeypatch 恢复）
    monkeypatch.delitem(sys.modules, "dataset_config", raising=False)

    synced = svc.sync_algorithm_datasets()
    assert synced == 1  # NO_PATH 无 relative_path 被跳过

    entry = registry_env.get_by_logical_name("TEST_SMAP")
    assert entry is not None
    assert entry["source"] == "algorithm_registry"
    assert entry["path"] == "Soil_Moisture/SMAP"
    assert entry["variables"] == ["soil_moisture"]
    assert entry["time_range"] == "2020-01-01~2021-01-01"

    # 用户 path 覆盖不被回写
    registry_env.upsert(
        dataset_id=entry["dataset_id"],
        logical_name="TEST_SMAP",
        path="Override/SMAP",
    )
    assert svc.sync_algorithm_datasets() == 1
    assert registry_env.get_by_logical_name("TEST_SMAP")["path"] == "Override/SMAP"


def test_sync_dataset_id_collision_appends_suffix(
    tmp_path: Path, monkeypatch, request, registry_env
) -> None:
    """派生 id 被其它 logical_name 占用时，sync 追加序号而非 ON CONFLICT 静默覆盖。"""
    from app.services import dataset_registry_service as svc

    # 手工条目抢占 TEST_SMAP 的派生 id "test-smap"
    registry_env.upsert(
        dataset_id="test-smap", logical_name="MANUAL", path="manual", source="manual"
    )

    provider_root = tmp_path / "provider"
    provider_root.mkdir()
    (provider_root / "dataset_config.py").write_text(
        _FAKE_DATASET_CONFIG, encoding="utf-8"
    )
    _patch_setting(request, monkeypatch, "python_provider_root", str(provider_root))
    monkeypatch.delitem(sys.modules, "dataset_config", raising=False)

    assert svc.sync_algorithm_datasets() == 1

    entry = registry_env.get_by_logical_name("TEST_SMAP")
    assert entry is not None
    assert entry["dataset_id"] == "test-smap-2"
    # 占用者未被覆盖
    manual = registry_env.get("test-smap")
    assert manual is not None and manual["logical_name"] == "MANUAL"


def test_sync_preserves_user_disabled_state(
    tmp_path: Path, monkeypatch, request, registry_env
) -> None:
    """用户禁用的内置条目不得被启动 sync 复活。"""
    from app.services import dataset_registry_service as svc

    provider_root = tmp_path / "provider"
    provider_root.mkdir()
    (provider_root / "dataset_config.py").write_text(
        _FAKE_DATASET_CONFIG, encoding="utf-8"
    )
    _patch_setting(request, monkeypatch, "python_provider_root", str(provider_root))
    monkeypatch.delitem(sys.modules, "dataset_config", raising=False)

    assert svc.sync_algorithm_datasets() == 1
    ds_id = registry_env.get_by_logical_name("TEST_SMAP")["dataset_id"]
    registry_env.upsert(
        dataset_id=ds_id, logical_name="TEST_SMAP", path="Soil_Moisture/SMAP", enabled=False
    )
    assert registry_env.get_by_logical_name("TEST_SMAP")["enabled"] is False

    # 再次 sync（模拟服务重启）后仍保持禁用
    assert svc.sync_algorithm_datasets() == 1
    assert registry_env.get_by_logical_name("TEST_SMAP")["enabled"] is False


def test_sync_algorithm_datasets_missing_root(monkeypatch, request, registry_env) -> None:
    _patch_setting(
        request, monkeypatch, "python_provider_root", "Z:/__nonexistent_provider_root__"
    )
    from app.services.dataset_registry_service import sync_algorithm_datasets

    assert sync_algorithm_datasets() == 0


# ── 数据根扫描 ────────────────────────────────────────────────────────────────


def test_rescan_data_root(tmp_path: Path, monkeypatch, request, registry_env) -> None:
    from app.services.dataset_registry_service import rescan_data_root

    root = tmp_path / "Geograph_DataSet"
    (root / "Soil_Moisture" / "SMAP").mkdir(parents=True)
    (root / "Soil_Moisture" / "SMAP" / "a.h5").write_bytes(b"x")
    (root / "Soil_Moisture" / "SMAP" / "b.h5").write_bytes(b"x")
    (root / "Admin_Boundary").mkdir(parents=True)
    _patch_setting(request, monkeypatch, "data_root", str(root))

    result = rescan_data_root()
    assert result["created"] == 3  # Soil_Moisture / SMAP / Admin_Boundary
    by_name = {e["logical_name"]: e for e in result["entries"]}
    assert by_name["SMAP"]["source"] == "scan"
    assert by_name["SMAP"]["path"] == "Soil_Moisture/SMAP"
    assert by_name["SMAP"]["file_count"] == 2
    assert by_name["SMAP"]["last_scanned_at"]

    # 二次扫描：无新增，仅刷新
    result2 = rescan_data_root()
    assert result2["created"] == 0
    assert result2["refreshed"] == 3


# ── readiness 联动 ────────────────────────────────────────────────────────────


def test_resolve_dataset_path(tmp_path: Path, monkeypatch, request, registry_env) -> None:
    from app.services.dataset_registry_service import resolve_dataset_path

    root = tmp_path / "Geograph_DataSet"
    (root / "Soil_Moisture" / "SMAP").mkdir(parents=True)
    _patch_setting(request, monkeypatch, "data_root", str(root))

    # 相对路径 → data_root 解析且存在
    registry_env.upsert(
        dataset_id=None,
        logical_name="SMAP_L3",
        path="Soil_Moisture/SMAP",
        source="manual",
    )
    resolved = resolve_dataset_path("SMAP_L3")
    assert resolved is not None and resolved.name == "SMAP"

    # 绝对路径
    abs_dir = tmp_path / "abs_data"
    abs_dir.mkdir()
    registry_env.upsert(
        dataset_id=None, logical_name="ABS", path=str(abs_dir), source="manual"
    )
    assert resolve_dataset_path("ABS") == abs_dir

    # 不存在 → None
    registry_env.upsert(
        dataset_id=None, logical_name="GONE", path="missing/dir", source="manual"
    )
    assert resolve_dataset_path("GONE") is None

    # 禁用 → None
    registry_env.upsert(
        dataset_id=None,
        logical_name="DISABLED",
        path="Soil_Moisture",
        source="manual",
        enabled=False,
    )
    assert resolve_dataset_path("DISABLED") is None


def test_rescan_reads_current_settings_object(
    tmp_path: Path, monkeypatch, registry_env
) -> None:
    """回归：服务不得在导入期绑定 settings 引用（split-brain 防护）。

    其他测试（test_config_* / test_data_root_policy）会以
    ``monkeypatch.setattr("app.core.config.settings", replace(settings, ...))``
    替换整个 settings 对象；若本服务模块在导入期用
    ``from app.core.config import settings`` 绑定引用，则会永久持有临时对象，
    导致此后一切属性补丁（_patch_setting 打在还原后的对象上）对本服务无效。
    """
    from dataclasses import replace

    from app.core import config
    from app.services.dataset_registry_service import rescan_data_root

    root = tmp_path / "geo"
    (root / "Alpha").mkdir(parents=True)
    (root / "Alpha" / "f.bin").write_bytes(b"x")
    monkeypatch.setattr(
        "app.core.config.settings", replace(config.settings, data_root=str(root))
    )

    result = rescan_data_root()
    assert result["created"] == 1
    assert result["entries"][0]["logical_name"] == "Alpha"


def test_invalidate_dataset_caches(monkeypatch) -> None:
    from app.services import dataset_registry_service as svc

    called = []
    monkeypatch.setattr(
        "app.services.workflow_request_resolver.invalidate_template_cache",
        lambda: called.append(True),
    )
    svc.invalidate_dataset_caches()
    assert called == [True]


# ── config_service 包装 ───────────────────────────────────────────────────────


def test_config_service_dataset_wrappers(monkeypatch, registry_env) -> None:
    from app.services import config_service

    entry = config_service.upsert_available_dataset(
        "new",
        {
            "logical_name": "WRAP_TEST",
            "path": "wrap/test",
            "variables": ["v1"],
            "enabled": True,
        },
    )
    assert entry["logical_name"] == "WRAP_TEST"
    assert any(
        e["logical_name"] == "WRAP_TEST"
        for e in config_service.list_available_datasets()
    )

    updated = config_service.upsert_available_dataset(
        entry["dataset_id"],
        {"logical_name": "WRAP_TEST", "path": "wrap/test2", "enabled": False},
    )
    assert updated["path"] == "wrap/test2"
    assert updated["enabled"] is False

    assert config_service.delete_available_dataset(entry["dataset_id"]) is True
    assert config_service.delete_available_dataset(entry["dataset_id"]) is False

    with pytest.raises(ValueError, match="logical_name"):
        config_service.upsert_available_dataset(
            "new", {"logical_name": "", "path": "x"}
        )
