"""Tests for system seed sync orphan cleanup.

覆盖 2026-08-17 种子审计修补 A：``_sync_system_seeds`` 在同步后自动移除
运行时 system 目录中已无对应种子的孤儿定义，使"删除种子"成为自洽操作
（无需手工清理 ``.data/workflow_definitions/system/``）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import workflow_definition_service as wds


def _make_seed(workflow_id: str) -> dict[str, object]:
    return {
        "_meta": {
            "kind": "system",
            "engine": "python_provider",
            "name": f"Seed {workflow_id}",
            "description": "seed sync test",
            "author": "system",
            "readonly": True,
            "is_template": True,
            "linked_layer_id": None,
            "tags": ["analysis"],
            "category": "analysis",
            "resource_profile": "standard",
        },
        "workflow_id": workflow_id,
        "name": f"Seed {workflow_id}",
        "description": "seed sync test",
        "nodes": [{"id": 1, "type": "data/source", "pos": [80, 160], "properties": {}}],
        "links": [],
    }


def _write_seed(seed_dir: Path, workflow_id: str) -> None:
    (seed_dir / f"{workflow_id}.json").write_text(
        json.dumps(_make_seed(workflow_id), indent=2), encoding="utf-8"
    )


@pytest.fixture()
def isolated_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    seed_dir = tmp_path / "seeds"
    seed_dir.mkdir(parents=True)
    system_dir = tmp_path / "definitions" / "system"
    user_dir = tmp_path / "definitions" / "user"
    monkeypatch.setattr(wds, "_SEED_SYSTEM_DIR", seed_dir)
    monkeypatch.setattr(wds, "_SYSTEM_DIR", system_dir)
    monkeypatch.setattr(wds, "_USER_DIR", user_dir)
    return seed_dir, system_dir, user_dir


def test_orphan_removed_after_seed_deletion(
    isolated_dirs: tuple[Path, Path, Path],
) -> None:
    seed_dir, system_dir, _ = isolated_dirs
    _write_seed(seed_dir, "keep_flow")
    _write_seed(seed_dir, "dropped_flow")
    wds._ensure_dirs()
    assert (system_dir / "keep_flow.json").exists()
    assert (system_dir / "dropped_flow.json").exists()

    (seed_dir / "dropped_flow.json").unlink()
    wds._sync_system_seeds()

    assert (system_dir / "keep_flow.json").exists()
    assert not (system_dir / "dropped_flow.json").exists()


def test_user_definitions_untouched_by_cleanup(
    isolated_dirs: tuple[Path, Path, Path],
) -> None:
    seed_dir, system_dir, user_dir = isolated_dirs
    _write_seed(seed_dir, "old_flow")
    wds._ensure_dirs()
    created = wds.create_definition(
        {
            "workflow_id": "user_flow",
            "name": "User flow",
            "nodes": [],
            "links": [],
        }
    )
    assert created["workflow_id"] == "user_flow"

    (seed_dir / "old_flow.json").unlink()
    wds._sync_system_seeds()

    assert not (system_dir / "old_flow.json").exists()
    assert (user_dir / "user_flow.json").exists()
    assert wds.get_definition("user_flow") is not None


def test_sync_idempotent_skip_keeps_file_untouched(
    isolated_dirs: tuple[Path, Path, Path],
) -> None:
    seed_dir, system_dir, _ = isolated_dirs
    _write_seed(seed_dir, "stable_flow")
    wds._ensure_dirs()
    target = system_dir / "stable_flow.json"
    first = target.read_text(encoding="utf-8")
    mtime_first = target.stat().st_mtime_ns

    wds._sync_system_seeds()

    # 幂等跳过：内容与 mtime 均不变（未重写文件）
    assert target.read_text(encoding="utf-8") == first
    assert target.stat().st_mtime_ns == mtime_first


def test_seed_content_change_propagates(
    isolated_dirs: tuple[Path, Path, Path],
) -> None:
    seed_dir, system_dir, _ = isolated_dirs
    _write_seed(seed_dir, "updated_flow")
    wds._ensure_dirs()

    seed = _make_seed("updated_flow")
    seed["nodes"].append(
        {"id": 2, "type": "stats/histogram", "pos": [380, 160], "properties": {}}
    )
    (seed_dir / "updated_flow.json").write_text(
        json.dumps(seed, indent=2), encoding="utf-8"
    )
    wds._sync_system_seeds()

    runtime = json.loads((system_dir / "updated_flow.json").read_text(encoding="utf-8"))
    assert len(runtime["nodes"]) == 2


def test_missing_seed_dir_leaves_runtime_untouched(
    isolated_dirs: tuple[Path, Path, Path],
) -> None:
    seed_dir, system_dir, _ = isolated_dirs
    _write_seed(seed_dir, "any_flow")
    wds._ensure_dirs()
    assert (system_dir / "any_flow.json").exists()

    # 模拟种子包整体缺失：同步应提前返回，不得清空运行时定义
    (seed_dir / "any_flow.json").unlink()
    seed_dir.rmdir()
    wds._sync_system_seeds()

    assert (system_dir / "any_flow.json").exists()
