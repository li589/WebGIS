"""SMAP-02: data cleaning - invalid fill / out-of-range values become NaN."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from ingest.smap import SmapFieldSpec, _sanitize_array, read_smap_am_fields


class SmapDataCleaningTests(unittest.TestCase):
    """SMAP-02: invalid fill values and out-of-range values become NaN."""

    def test_invalid_fill_converted_to_nan(self) -> None:
        spec = SmapFieldSpec(output_name="test", hdf5_path="/test", invalid_fill=-9999.0, transpose=False)
        raw = np.array([[1.0, -9999.0, 3.0], [-9999.0, 5.0, -9999.0]], dtype=np.float64)
        result = _sanitize_array(raw, spec)
        expected = np.array([[1.0, np.nan, 3.0], [np.nan, 5.0, np.nan]], dtype=np.float64)
        np.testing.assert_array_equal(np.isnan(result), np.isnan(expected))
        np.testing.assert_array_equal(result[~np.isnan(result)], expected[~np.isnan(expected)])

    def test_min_valid_threshold_converted_to_nan(self) -> None:
        spec = SmapFieldSpec(output_name="Ts", hdf5_path="/test", min_valid=253.15, invalid_fill=-9999.0, transpose=False)
        raw = np.array([[250.0, 260.0, 300.0]], dtype=np.float64)
        result = _sanitize_array(raw, spec)
        self.assertTrue(np.isnan(result[0, 0]))
        self.assertFalse(np.isnan(result[0, 1]))
        self.assertFalse(np.isnan(result[0, 2]))

    def test_max_valid_threshold_converted_to_nan(self) -> None:
        spec = SmapFieldSpec(output_name="TBh", hdf5_path="/test", max_valid=330.0, invalid_fill=-9999.0, transpose=False)
        raw = np.array([[320.0, 335.0, 340.0]], dtype=np.float64)
        result = _sanitize_array(raw, spec)
        self.assertFalse(np.isnan(result[0, 0]))
        self.assertTrue(np.isnan(result[0, 1]))
        self.assertTrue(np.isnan(result[0, 2]))

    def test_combined_invalid_fill_and_out_of_range(self) -> None:
        spec = SmapFieldSpec(output_name="TBv", hdf5_path="/test", max_valid=330.0, invalid_fill=-9999.0, transpose=False)
        raw = np.array([[-9999.0, 300.0, -9999.0], [400.0, -9999.0, 310.0]], dtype=np.float64)
        result = _sanitize_array(raw, spec)
        self.assertTrue(np.isnan(result[0, 0]))
        self.assertFalse(np.isnan(result[0, 1]))
        self.assertTrue(np.isnan(result[0, 2]))
        self.assertTrue(np.isnan(result[1, 0]))
        self.assertTrue(np.isnan(result[1, 1]))
        self.assertFalse(np.isnan(result[1, 2]))

    def test_vwc_valid_range(self) -> None:
        spec = SmapFieldSpec(output_name="vwc", hdf5_path="/test", min_valid=0.0, max_valid=30.0, invalid_fill=-9999.0, transpose=False)
        raw = np.array([[-1.0, 5.0, 50.0, -9999.0]], dtype=np.float64)
        result = _sanitize_array(raw, spec)
        self.assertTrue(np.isnan(result[0, 0]))
        self.assertFalse(np.isnan(result[0, 1]))
        self.assertTrue(np.isnan(result[0, 2]))
        self.assertTrue(np.isnan(result[0, 3]))

    def test_read_smap_am_fields_applies_all_cleaning(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp())
        h5_path = tmp_dir / "test_smap.h5"

        with h5py.File(h5_path, "w") as h5:
            h5.create_dataset("/Soil_Moisture_Retrieval_Data_AM/tb_h_corrected", data=np.array([[-9999], [280], [350]], dtype=np.float64))
            h5.create_dataset("/Soil_Moisture_Retrieval_Data_AM/tb_v_corrected", data=np.array([[250], [290], [-9999]], dtype=np.float64))
            h5.create_dataset("/Soil_Moisture_Retrieval_Data_AM/surface_temperature", data=np.array([[240], [280], [320]], dtype=np.float64))
            h5.create_dataset("/Soil_Moisture_Retrieval_Data_AM/vegetation_water_content", data=np.array([[-1], [5], [50]], dtype=np.float64))
            h5.create_dataset("/Soil_Moisture_Retrieval_Data_AM/boresight_incidence", data=np.array([[40], [50], [60]], dtype=np.float64))
            h5.create_dataset("/Soil_Moisture_Retrieval_Data_AM/soil_moisture_dca", data=np.array([[-9999], [0.1], [0.2]], dtype=np.float64))
            h5.create_dataset("/Soil_Moisture_Retrieval_Data_AM/soil_moisture_scav", data=np.array([[0.05], [0.15], [0.25]], dtype=np.float64))
            h5.create_dataset("/Soil_Moisture_Retrieval_Data_AM/vegetation_opacity_dca", data=np.array([[0.1], [0.2], [0.3]], dtype=np.float64))
            h5.create_dataset("/Soil_Moisture_Retrieval_Data_AM/vegetation_opacity_scav", data=np.array([[0.05], [0.1], [0.15]], dtype=np.float64))

        results = read_smap_am_fields(h5_path)

        # TBh: transpose True; HDF5 (3,1) → result (1,3)
        # [-9999, 280, 350]: -9999 → NaN (invalid fill), 280 is valid (< 330), 350 → NaN (>330)
        self.assertTrue(np.isnan(results["TBh"][0, 0]))
        self.assertFalse(np.isnan(results["TBh"][0, 1]))
        self.assertTrue(np.isnan(results["TBh"][0, 2]))

        # TBv: transpose True; HDF5 (3,1) → result (1,3)
        # 250 < 330, 290 < 330, -9999 → NaN (invalid fill)
        self.assertFalse(np.isnan(results["TBv"][0, 0]))
        self.assertFalse(np.isnan(results["TBv"][0, 1]))
        self.assertTrue(np.isnan(results["TBv"][0, 2]))

        # Ts: 240 < 253.15 → NaN, 320 > 313.15 → NaN
        self.assertTrue(np.isnan(results["Ts"][0, 0]))
        self.assertFalse(np.isnan(results["Ts"][0, 1]))
        self.assertTrue(np.isnan(results["Ts"][0, 2]))

        # vwc: -1 < 0 → NaN, 50 > 30 → NaN
        self.assertTrue(np.isnan(results["vwc"][0, 0]))
        self.assertFalse(np.isnan(results["vwc"][0, 1]))
        self.assertTrue(np.isnan(results["vwc"][0, 2]))

        # sm_dca: -9999 → NaN
        self.assertTrue(np.isnan(results["sm_dca"][0, 0]))
        self.assertFalse(np.isnan(results["sm_dca"][0, 1]))
        self.assertFalse(np.isnan(results["sm_dca"][0, 2]))


if __name__ == "__main__":
    unittest.main()
