from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path


class TestGldasUtcTemplate(unittest.TestCase):
    def test_utc_to_slot_basic(self) -> None:
        from ingest.gldas_utc_template import utc_to_slot_index_and_day_offset

        base = datetime(2025, 1, 1)
        # Exactly on 06:00 UTC slot → slot 3 (0,3,6 → 1-based index 3), day 0
        slot, offset = utc_to_slot_index_and_day_offset(
            datetime(2025, 1, 1, 6, 0), base
        )
        self.assertEqual(slot, 3)
        self.assertEqual(offset, 0)

        # Near previous-day 21:00 → day_offset -1, last slot
        slot, offset = utc_to_slot_index_and_day_offset(
            datetime(2024, 12, 31, 21, 10), base
        )
        self.assertEqual(slot, 8)
        self.assertEqual(offset, -1)

    def test_build_writes_smap_and_fy_containers(self) -> None:
        import numpy as np
        from scipy.io import savemat

        from ingest.gldas_utc_template import build_gldas_utc_template
        from ingest.mat_bundle import load_mat_file

        with tempfile.TemporaryDirectory() as tmp:
            anc = Path(tmp) / "IGBP_9km_12.mat"
            lon = np.linspace(100.0, 110.0, 8, dtype=np.float64)
            lat = np.linspace(40.0, 39.0, 6, dtype=np.float64)
            lon2d, _ = np.meshgrid(lon, lat)
            savemat(anc, {"lon_9km": lon2d, "lat_9km": lon2d}, do_compression=True)
            out = Path(tmp) / "gldas_utc_template_global.mat"
            result = build_gldas_utc_template(ancillary_mat=anc, output_path=out)
            self.assertTrue(out.is_file())
            self.assertEqual(result.nrows, 6)
            self.assertEqual(result.ncols, 8)
            payload = load_mat_file(out)
            for name in ("SMAP_template", "FY3D_template", "FY3B_template"):
                self.assertIn(name, payload)
                container = payload[name]
                if isinstance(container, dict):
                    si = container["slot_index"]
                    do = container["slot_day_offset"]
                else:
                    si = getattr(container, "slot_index")
                    do = getattr(container, "slot_day_offset")
                si = np.asarray(si)
                do = np.asarray(do)
                self.assertEqual(si.shape, (6, 8))
                self.assertEqual(do.shape, (6, 8))
                self.assertTrue(np.isfinite(si).all())
                self.assertTrue(np.isfinite(do).all())


if __name__ == "__main__":
    unittest.main()
