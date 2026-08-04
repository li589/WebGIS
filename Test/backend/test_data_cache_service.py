"""Tests for static data cache overview/evict helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class DataCacheServiceTests(unittest.TestCase):
    def test_overview_and_evict(self) -> None:
        from app.services import data_cache_service as svc

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "materialized"
            root.mkdir()
            (root / "a.bin").write_bytes(b"abc")
            (root / "b.bin").write_bytes(b"xyz")

            with patch.object(svc, "resolve_static_cache_root", return_value=root):
                overview = svc.get_data_cache_overview()
                self.assertEqual(overview["entry_count"], 2)
                self.assertGreaterEqual(overview["total_bytes"], 6)

                result = svc.evict_data_cache(uri_or_name="a.bin")
                self.assertEqual(result["removed_count"], 1)
                self.assertFalse((root / "a.bin").exists())
                self.assertTrue((root / "b.bin").exists())


if __name__ == "__main__":
    unittest.main()
