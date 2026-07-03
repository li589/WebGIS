from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from ingest.daily_bundle import DailyBundleConfig
from ingest.timeseries_bundle import build_timeseries_bundle


class TimeSeriesBundleTests(unittest.TestCase):
    def test_missing_file_only_populates_missing_dates_and_keeps_other_days(self) -> None:
        config = DailyBundleConfig()
        static_bundle = {
            "Albedo": np.array([0.1, 0.2], dtype=np.float64),
            "B": np.array([0.3, 0.4], dtype=np.float64),
            "CF": np.array([0.5, 0.6], dtype=np.float64),
            "BD": np.array([1.2, 1.3], dtype=np.float64),
            "H": np.array([0.7, 0.8], dtype=np.float64),
            "porosity": np.array([0.4, 0.5], dtype=np.float64),
            "LC": np.array([1, 2], dtype=np.float64),
            "NDVI_v_max": np.array([0.9, 0.95], dtype=np.float64),
            "NDVI_v_min": np.array([0.1, 0.15], dtype=np.float64),
            "lat_9km": np.array([10.0, 11.0], dtype=np.float64),
            "lon_9km": np.array([100.0, 101.0], dtype=np.float64),
        }

        def fake_daily_bundle(date_key, config, datasource_selection, lin_pix=None):
            _ = (config, datasource_selection, lin_pix)
            if date_key == "20200102":
                raise FileNotFoundError("missing file")
            return {
                "TBv": np.array([1.0, 2.0], dtype=np.float64),
                "TBh": np.array([3.0, 4.0], dtype=np.float64),
                "IA": np.array([5.0, 6.0], dtype=np.float64),
                "Ts": np.array([7.0, 8.0], dtype=np.float64),
                "SM_ref": np.array([0.2, 0.3], dtype=np.float64),
                "NDVI": np.array([0.4, 0.5], dtype=np.float64),
                "SF": np.array([0.6, 0.7], dtype=np.float64),
                "vwc": np.array([0.8, 0.9], dtype=np.float64),
            }

        with patch("ingest.timeseries_bundle.load_static_ancillary_bundle", return_value=static_bundle) as static_loader, patch(
            "ingest.timeseries_bundle.build_daily_bundle_for_date",
            side_effect=fake_daily_bundle,
        ):
            bundle = build_timeseries_bundle(
                date_keys=["20200101", "20200102", "20200103"],
                config=config,
                datasource_selection={"anc_root": "dummy-root"},
            )

        static_loader.assert_called_once_with(
            "dummy-root",
            config,
            lin_pix=None,
            ndvi_extrema_mat=None,
        )
        self.assertEqual(bundle.missing_dates, ["20200102"])
        self.assertEqual(bundle.pixel_count, 2)
        self.assertTrue(np.isnan(bundle.data["TBv_mat"][1, :]).all())
        self.assertTrue(np.allclose(bundle.data["TBv_mat"][0, :], [1.0, 2.0]))
        self.assertTrue(np.allclose(bundle.data["TBv_mat"][2, :], [1.0, 2.0]))

    def test_structural_errors_are_not_reclassified_as_missing_dates(self) -> None:
        config = DailyBundleConfig()
        static_bundle = {
            "Albedo": np.array([0.1], dtype=np.float64),
            "B": np.array([0.3], dtype=np.float64),
            "CF": np.array([0.5], dtype=np.float64),
            "BD": np.array([1.2], dtype=np.float64),
            "H": np.array([0.7], dtype=np.float64),
            "porosity": np.array([0.4], dtype=np.float64),
            "LC": np.array([1], dtype=np.float64),
            "NDVI_v_max": np.array([0.9], dtype=np.float64),
            "NDVI_v_min": np.array([0.1], dtype=np.float64),
            "lat_9km": np.array([10.0], dtype=np.float64),
            "lon_9km": np.array([100.0], dtype=np.float64),
        }

        with patch("ingest.timeseries_bundle.load_static_ancillary_bundle", return_value=static_bundle), patch(
            "ingest.timeseries_bundle.build_daily_bundle_for_date",
            side_effect=KeyError("missing TBv field"),
        ):
            with self.assertRaises(KeyError):
                build_timeseries_bundle(
                    date_keys=["20200101"],
                    config=config,
                    datasource_selection={"anc_root": "dummy-root"},
                )


if __name__ == "__main__":
    unittest.main()
