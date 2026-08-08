"""节点产物缓存扫描与清理 API 测试（cleanup_router node-caches）。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app.api.routers.cleanup_router import (
    NodeCacheCleanupRequest,
    NodeCacheCleanupResponse,
    _scan_node_caches,
    cleanup_node_caches,
)


class NodeCacheScanTests(unittest.TestCase):
    def test_scan_lists_module_dirs_with_size_and_count(self) -> None:
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
            self.assertEqual(names, {"omega_block", "charts"})
            omega = next(e for e in entries if e.name == "omega_block")
            self.assertEqual(omega.size_bytes, 3072)
            self.assertEqual(omega.file_count, 2)
            self.assertIsNotNone(omega.modified_at)
            self.assertIn("omega_block", omega.path)

    def test_scan_missing_root_returns_empty(self) -> None:
        with mock.patch(
            "app.api.routers.cleanup_router._node_cache_root",
            return_value=Path("Z:/definitely-not-exist-xyz"),
        ):
            self.assertEqual(_scan_node_caches(), [])


class NodeCacheCleanupTests(unittest.TestCase):
    def test_cleanup_all_deletes_dirs_and_reports_freed(self) -> None:
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

            self.assertEqual(sorted(resp.deleted), ["omega_block", "omega_sf"])
            self.assertEqual(resp.failed, [])
            self.assertEqual(resp.freed_bytes, 3072)
            self.assertFalse((root / "omega_block").exists())
            self.assertFalse((root / "omega_sf").exists())

    def test_cleanup_selected_names_only(self) -> None:
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

            self.assertEqual(resp.deleted, ["remove"])
            self.assertTrue((root / "keep").exists())
            self.assertFalse((root / "remove").exists())

    def test_cleanup_unknown_name_reported_failed(self) -> None:
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

            self.assertEqual(resp.deleted, [])
            self.assertEqual(resp.failed, ["ghost"])
            self.assertEqual(resp.freed_bytes, 0)


if __name__ == "__main__":
    unittest.main()
