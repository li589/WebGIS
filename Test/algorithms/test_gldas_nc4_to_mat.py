"""Tests for GLDAS nc4→mat conversion."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ingest.gldas_nc4_to_mat import (
    mat_name_for_nc4,
    parse_gldas_nc4_timestamp,
)


class TestGldasNc4ToMat(unittest.TestCase):
    def test_parse_timestamp_from_filename(self) -> None:
        name = "GLDAS_NOAH025_3H.A20251203.0000.021.nc4"
        parsed = parse_gldas_nc4_timestamp(name)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.strftime("%Y%m%d_%H%M"), "20251203_0000")
        self.assertEqual(mat_name_for_nc4(name), "20251203_0000.mat")

    def test_convert_directory_dry_run(self) -> None:
        from ingest.gldas_nc4_to_mat import convert_gldas_nc4_directory

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nc_dir = root / "nc4"
            out_dir = root / "mat"
            nc_dir.mkdir()
            (nc_dir / "GLDAS_NOAH025_3H.A20251203.0000.021.nc4").write_bytes(b"x")
            ancillary = root / "anc.mat"
            with patch(
                "ingest.gldas_nc4_to_mat.load_study_grid",
                return_value=([0.0], [0.0]),
            ), patch(
                "ingest.gldas_nc4_to_mat.convert_gldas_nc4_file",
                return_value=out_dir / "20251203_0000.mat",
            ) as mocked:
                result = convert_gldas_nc4_directory(
                    input_dir=nc_dir,
                    output_dir=out_dir,
                    ancillary_mat=ancillary,
                    dry_run=True,
                )
            self.assertEqual(result.total_nc4, 1)
            self.assertEqual(result.converted, 1)
            mocked.assert_called_once()

    def test_module_registered(self) -> None:
        import contracts.job  # noqa: F401
        from modules import registry as module_registry

        self.assertIn("gldas_nc4_to_mat", set(module_registry.list_modules()))


if __name__ == "__main__":
    unittest.main()
