"""fy_daily NAS 预投影逐波段 TIF 直转 mat 路径测试。

覆盖：
- build_fy_daily_job_plans 无 HDF 时自动接受 *.tif 并标记 input_format=tif
- build_fy_daily_mat_payload_from_band_tifs 缩放/nodata/IA 标称角/网格校验
- FyDailyModule tif 计划跳过 GDAL 命令链直接落盘 YYYYMMDD.mat
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

PROVIDER_ROOT = Path(__file__).resolve().parents[2] / "Code" / "algorithms" / "providers" / "Python"
sys.path.insert(0, str(PROVIDER_ROOT))

import contracts.job  # noqa: F401, E402  # break modules.registry ↔ workflow.panel_schema cycle

from algorithms.fy import (  # noqa: E402
    FY_NOMINAL_INCIDENCE_DEG,
    build_fy_daily_mat_payload_from_band_tifs,
)
from ingest.fy import build_fy_daily_job_plans  # noqa: E402

EASE_ROWS, EASE_COLS = 1624, 3856


def _write_band_tif(path: Path, *, fill: float) -> None:
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    arr = np.full((EASE_ROWS, EASE_COLS), fill, dtype=np.float32)
    transform = from_bounds(-17367530.45, -7314540.83, 17367530.45, 7314540.83,
                            EASE_COLS, EASE_ROWS)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=EASE_COLS,
        height=EASE_ROWS,
        count=1,
        dtype="float32",
        crs="EPSG:6933",
        transform=transform,
        nodata=-32767.0,
    ) as dst:
        dst.write(arr, 1)


class TestPlanTifDetection(unittest.TestCase):
    def test_tif_only_dir_builds_tif_plans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw"
            raw.mkdir()
            _write_band_tif(raw / "FY3D_GBAL_L1_10V_20251227_MWRID_0.tif", fill=-8000.0)
            _write_band_tif(raw / "FY3D_GBAL_L1_10H_20251227_MWRID_0.tif", fill=-9000.0)

            plans = build_fy_daily_job_plans(
                input_dir=raw,
                output_root=Path(tmp) / "out",
                start_time=datetime(2025, 12, 27),
                end_time=datetime(2025, 12, 27),
                orbit_mode="MWRID",
            )
            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].metadata["input_format"], "tif")
            self.assertEqual(len(plans[0].input_files), 2)

    def test_no_files_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw"
            raw.mkdir()
            with self.assertRaises(FileNotFoundError):
                build_fy_daily_job_plans(
                    input_dir=raw,
                    output_root=Path(tmp) / "out",
                    start_time=datetime(2025, 12, 27),
                    end_time=datetime(2025, 12, 27),
                    orbit_mode="MWRID",
                )


class TestBandTifPayload(unittest.TestCase):
    def test_scaling_nodata_and_nominal_ia(self) -> None:
        import numpy as np
        from scipy.io import loadmat

        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            # raw=-8000 → TB = -80 + 327.68 = 247.68K；10H -9000 → 237.68K
            v_tif = raw / "FY3D_GBAL_L1_10V_20251227_MWRID_0.tif"
            h_tif = raw / "FY3D_GBAL_L1_10H_20251227_MWRID_0.tif"
            _write_band_tif(v_tif, fill=-8000.0)
            _write_band_tif(h_tif, fill=-9000.0)

            payload = build_fy_daily_mat_payload_from_band_tifs(
                [str(h_tif), str(v_tif)], "FY3D"
            )
            self.assertAlmostEqual(float(np.nanmedian(payload["TBv"])), 247.68, places=2)
            self.assertAlmostEqual(float(np.nanmedian(payload["TBh"])), 237.68, places=2)
            # IA 标称角填充
            self.assertAlmostEqual(
                float(np.nanmedian(payload["IA"])), FY_NOMINAL_INCIDENCE_DEG, places=6
            )

    def test_missing_band_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            only_v = Path(tmp) / "FY3D_GBAL_L1_10V_20251227_MWRID_0.tif"
            _write_band_tif(only_v, fill=-8000.0)
            with self.assertRaises(ValueError) as cm:
                build_fy_daily_mat_payload_from_band_tifs([str(only_v)], "FY3D")
            self.assertIn("10H", str(cm.exception))

    def test_grid_mismatch_rejected(self) -> None:
        import numpy as np
        import rasterio

        with tempfile.TemporaryDirectory() as tmp:
            # 双波段齐全但 10V 网格不符（100×200 ≠ 3856×1624）
            bad = Path(tmp) / "FY3D_GBAL_L1_10V_20251227_MWRID_0.tif"
            good = Path(tmp) / "FY3D_GBAL_L1_10H_20251227_MWRID_0.tif"
            arr = np.zeros((100, 200), dtype=np.float32)
            with rasterio.open(
                bad, "w", driver="GTiff", width=200, height=100, count=1,
                dtype="float32", crs="EPSG:6933",
            ) as dst:
                dst.write(arr, 1)
            _write_band_tif(good, fill=-9000.0)
            with self.assertRaises(ValueError) as cm:
                build_fy_daily_mat_payload_from_band_tifs(
                    [str(bad), str(good)], "FY3D"
                )
            self.assertIn("grid mismatch", str(cm.exception))


class TestFyDailyModuleTifBranch(unittest.TestCase):
    def test_tif_plan_produces_mat_without_gdal(self) -> None:
        from modules.fy import FyDailyModule

        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw"
            raw.mkdir()
            out_root = Path(tmp) / "fy3d"
            _write_band_tif(raw / "FY3D_GBAL_L1_10V_20251227_MWRID_0.tif", fill=-8000.0)
            _write_band_tif(raw / "FY3D_GBAL_L1_10H_20251227_MWRID_0.tif", fill=-9000.0)

            plans = build_fy_daily_job_plans(
                input_dir=raw,
                output_root=out_root,
                start_time=datetime(2025, 12, 27),
                end_time=datetime(2025, 12, 27),
                orbit_mode="MWRID",
            )
            module = FyDailyModule()
            products = module._build_fy_data_products(
                plans, out_root, execute_commands=False
            )
            mats = [p for p in products if p.type == "fy_daily_mat"]
            self.assertEqual(len(mats), 1)
            mat_path = Path(mats[0].uri)
            self.assertEqual(mat_path.name, "20251227.mat")
            self.assertTrue(mat_path.exists())

            import numpy as np
            from scipy.io import loadmat

            d = loadmat(str(mat_path))
            self.assertAlmostEqual(
                float(np.nanmedian(d["TBv"])), 247.68, places=2
            )


class TestHdfExtensionTolerance(unittest.TestCase):
    """discover_fy_orbit_files 默认模式应大小写不敏感并接受 .hdf/.hdf5 变体。"""

    def test_hdf5_and_case_variants_discovered(self) -> None:
        from ingest.fy import discover_fy_orbit_files

        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw"
            raw.mkdir()
            for name in (
                "FY3D_GBAL_L1_20251227_MWRID_0.HDF",
                "FY3D_GBAL_L1_20251228_MWRID_0.hdf",
                "FY3D_GBAL_L1_20251229_MWRID_0.hdf5",
            ):
                (raw / name).write_bytes(b"")
            files = discover_fy_orbit_files(raw)
            self.assertEqual(
                [f.file_name for f in files],
                [
                    "FY3D_GBAL_L1_20251227_MWRID_0.HDF",
                    "FY3D_GBAL_L1_20251228_MWRID_0.hdf",
                    "FY3D_GBAL_L1_20251229_MWRID_0.hdf5",
                ],
            )
            self.assertEqual(
                [f.date_key for f in files],
                ["20251227", "20251228", "20251229"],
            )
            self.assertTrue(all(f.orbit_type == "MWRID" for f in files))

    def test_explicit_pattern_stays_exact(self) -> None:
        from ingest.fy import discover_fy_orbit_files

        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw"
            raw.mkdir()
            (raw / "FY3D_GBAL_L1_20251227_MWRID_0.HDF").write_bytes(b"")
            (raw / "FY3D_GBAL_L1_20251227_MWRID_0.tif").write_bytes(b"")
            files = discover_fy_orbit_files(raw, pattern="*.tif")
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].file_name.endswith(".tif"))


if __name__ == "__main__":
    unittest.main()
