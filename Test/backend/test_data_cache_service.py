"""Tests for static data cache overview/evict helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch


def test_overview_and_evict() -> None:
    from app.services import data_cache_service as svc

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "materialized"
        root.mkdir()
        (root / "a.bin").write_bytes(b"abc")
        (root / "b.bin").write_bytes(b"xyz")

        with patch.object(svc, "resolve_static_cache_root", return_value=root):
            overview = svc.get_data_cache_overview()
            assert overview["entry_count"] == 2, 'overview["entry_count"] == 2'
            assert overview["total_bytes"] >= 6, 'overview["total_bytes"] >= 6'

            result = svc.evict_data_cache(uri_or_name="a.bin")
            assert result["removed_count"] == 1, 'result["removed_count"] == 1'
            assert not (root / "a.bin").exists(), '(root / "a.bin").exists() is falsy'
            assert (root / "b.bin").exists(), '(root / "b.bin").exists() is truthy'
