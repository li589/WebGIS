"""节点产物缓存扫描与清理 API 测试（cleanup_router node-caches）。"""
from __future__ import annotations

from pathlib import Path
import tempfile
from unittest import mock

from app.api.routers.cleanup_router import (
    NodeCacheCleanupRequest,
    NodeCacheCleanupResponse,
    _scan_node_caches,
    cleanup_node_caches,
)


def test_scan_lists_module_dirs_with_size_and_count() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "products"
        (root / "omega_block").mkdir(parents=True)
        (root / "omega_block" / "a.mat").write_bytes(b"x" * 1024)
        (root / "omega_block" / "b.mat").write_bytes(b"y" * 2048)
        (root / "charts").mkdir()
        (root / "charts" / "c.png").write_bytes(b"z" * 512)
        # 非目录文件忽略
        (root / "notes.txt").write_text("ignore me")

        with mock.patch(
            "app.api.routers.cleanup_router._node_cache_root",
            return_value=root,
        ):
            entries = _scan_node_caches()

        names = {e.name for e in entries}
        assert names == {"omega_block", "charts"}, 'names == {"omega_block", "charts"}'
        omega = next(e for e in entries if e.name == "omega_block")
        assert omega.size_bytes == 3072, 'omega.size_bytes == 3072'
        assert omega.file_count == 2, 'omega.file_count == 2'
        assert omega.modified_at is not None, 'omega.modified_at is not None'
        assert "omega_block" in omega.path, '"omega_block" in omega.path'


def test_scan_missing_root_returns_empty() -> None:
    with mock.patch(
        "app.api.routers.cleanup_router._node_cache_root",
        return_value=Path("Z:/definitely-not-exist-xyz"),
    ):
        assert _scan_node_caches() == [], '_scan_node_caches() == []'


def test_cleanup_all_deletes_dirs_and_reports_freed() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "products"
        (root / "omega_block").mkdir(parents=True)
        (root / "omega_block" / "a.mat").write_bytes(b"x" * 1024)
        (root / "omega_sf").mkdir()
        (root / "omega_sf" / "b.mat").write_bytes(b"y" * 2048)

        with mock.patch(
            "app.api.routers.cleanup_router._node_cache_root",
            return_value=root,
        ):
            resp: NodeCacheCleanupResponse = cleanup_node_caches(
                NodeCacheCleanupRequest(names=None)
            )

        assert sorted(resp.deleted) == ["omega_block", "omega_sf"], 'sorted(resp.deleted) == ["omega_block", "omega_sf"]'
        assert resp.failed == [], 'resp.failed == []'
        assert resp.freed_bytes == 3072, 'resp.freed_bytes == 3072'
        assert not (root / "omega_block").exists(), '(root / "omega_block").exists() is falsy'
        assert not (root / "omega_sf").exists(), '(root / "omega_sf").exists() is falsy'


def test_cleanup_selected_names_only() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "products"
        (root / "keep").mkdir(parents=True)
        (root / "keep" / "a.mat").write_bytes(b"k" * 512)
        (root / "remove").mkdir()
        (root / "remove" / "b.mat").write_bytes(b"r" * 512)

        with mock.patch(
            "app.api.routers.cleanup_router._node_cache_root",
            return_value=root,
        ):
            resp = cleanup_node_caches(
                NodeCacheCleanupRequest(names=["remove"])
            )

        assert resp.deleted == ["remove"], 'resp.deleted == ["remove"]'
        assert (root / "keep").exists(), '(root / "keep").exists() is truthy'
        assert not (root / "remove").exists(), '(root / "remove").exists() is falsy'


def test_cleanup_unknown_name_reported_failed() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "products"
        root.mkdir(parents=True)

        with mock.patch(
            "app.api.routers.cleanup_router._node_cache_root",
            return_value=root,
        ):
            resp = cleanup_node_caches(
                NodeCacheCleanupRequest(names=["ghost"])
            )

        assert resp.deleted == [], 'resp.deleted == []'
        assert resp.failed == ["ghost"], 'resp.failed == ["ghost"]'
        assert resp.freed_bytes == 0, 'resp.freed_bytes == 0'
