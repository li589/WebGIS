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


class TestGldasInterpolateField(unittest.TestCase):
    """数值专项 C4：NaN 不涂抹 + 坐标单调性校验。"""

    LAT = [10.0, 10.5, 11.0, 11.5, 12.0]
    LON = [100.0, 100.5, 101.0, 101.5, 102.0]

    def _make_nc(self, root: Path, field, lat=None, lon=None) -> Path:
        import numpy as np
        import xarray as xr

        lat = self.LAT if lat is None else lat
        lon = self.LON if lon is None else lon
        ds = xr.Dataset(
            {"ts": (("time", "lat", "lon"), np.asarray(field, dtype=np.float64)[None])},
            coords={
                "time": [np.datetime64("2025-01-01T00:00")],
                "lat": np.asarray(lat, dtype=np.float64),
                "lon": np.asarray(lon, dtype=np.float64),
            },
        )
        path = root / "gldas.nc4"
        ds.to_netcdf(path)
        return path

    def _linear_field(self):
        import numpy as np

        lat = np.asarray(self.LAT)
        lon = np.asarray(self.LON)
        return lat[:, None] + 0.1 * lon[None, :]

    def test_nan_center_does_not_smear_to_neighbors(self) -> None:
        """场中心一个 NaN：其邻域目标格点不得变 NaN（凸包内有效）。"""
        import numpy as np

        from ingest.gldas_nc4_to_mat import _interpolate_nc4_field

        field = self._linear_field()
        field[2, 2] = np.nan  # 中心 (lat=11.0, lon=101.0)
        with tempfile.TemporaryDirectory() as tmp:
            nc = self._make_nc(Path(tmp), field)
            # 目标点取 NaN 点四邻胞内的中心——旧实现会被涂抹为 NaN
            lat_tgt = np.array([[11.2, 11.2], [10.8, 10.8]])
            lon_tgt = np.array([[101.2, 100.8], [101.2, 100.8]])
            out = _interpolate_nc4_field(nc, "ts", lat_tgt, lon_tgt)
        self.assertTrue(np.isfinite(out).all(), f"NaN 涂抹: {out}")
        for i in range(2):
            for j in range(2):
                expected = lat_tgt[i, j] + 0.1 * lon_tgt[i, j]
                self.assertAlmostEqual(out[i, j], expected, places=10)

    def test_descending_lat_axis_is_flipped_not_rejected(self) -> None:
        """降序 lat（北→南排列）应翻转后正常插值。"""
        import numpy as np

        from ingest.gldas_nc4_to_mat import _interpolate_nc4_field

        field = self._linear_field()[::-1, :]  # 对应降序 lat
        with tempfile.TemporaryDirectory() as tmp:
            nc = self._make_nc(
                Path(tmp), field, lat=self.LAT[::-1]
            )
            lat_tgt = np.array([[11.0, 10.5]])
            lon_tgt = np.array([[101.0, 101.0]])
            out = _interpolate_nc4_field(nc, "ts", lat_tgt, lon_tgt)
        self.assertAlmostEqual(out[0, 0], 11.0 + 0.1 * 101.0, places=10)
        self.assertAlmostEqual(out[0, 1], 10.5 + 0.1 * 101.0, places=10)

    def test_non_monotonic_axis_raises(self) -> None:
        """乱序坐标轴必须显式失败，不得静默产出错位数据。"""
        import numpy as np

        from ingest.gldas_nc4_to_mat import _interpolate_nc4_field

        field = self._linear_field()
        shuffled_lat = [10.0, 12.0, 11.0, 11.5, 10.5]
        with tempfile.TemporaryDirectory() as tmp:
            nc = self._make_nc(Path(tmp), field, lat=shuffled_lat)
            with self.assertRaises(ValueError):
                _interpolate_nc4_field(
                    nc, "ts", np.array([[11.0]]), np.array([[101.0]])
                )

    def test_all_finite_field_fast_path(self) -> None:
        """全有限场走规则网格快路径，线性场精确复现。"""
        import numpy as np

        from ingest.gldas_nc4_to_mat import _interpolate_nc4_field

        with tempfile.TemporaryDirectory() as tmp:
            nc = self._make_nc(Path(tmp), self._linear_field())
            lat_tgt, lon_tgt = np.meshgrid(
                np.array([10.2, 11.3]), np.array([100.4, 101.6])
            )
            out = _interpolate_nc4_field(nc, "ts", lat_tgt, lon_tgt)
        self.assertTrue(np.isfinite(out).all())
        expected = lat_tgt + 0.1 * lon_tgt
        np.testing.assert_allclose(out, expected, rtol=0, atol=1e-9)


if __name__ == "__main__":
    unittest.main()
