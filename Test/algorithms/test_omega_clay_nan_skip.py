"""Invalid clay / NDVI extrema must skip Mironov context build, not raise."""

from __future__ import annotations

import unittest

import numpy as np

from algorithms.omega import (
    OmegaConfig,
    OmegaFieldConfig,
    execute_omega_retrieval,
    retrieve_omega_pixel_timeseries,
)


def _base_pixel_kwargs(**overrides):
    nt = 4
    date_keys = [f"2025120{i}" for i in range(3, 3 + nt)]
    kwargs = {
        "date_keys": date_keys,
        "tbv": np.full(nt, 250.0),
        "tbh": np.full(nt, 230.0),
        "ts": np.full(nt, 290.0),
        "tc": None,
        "tg": None,
        "ia": np.full(nt, 40.0),
        "sm_ref": np.full(nt, 0.2),
        "ndvi": np.full(nt, 0.4),
        "sf_col": np.full(nt, 1.0),
        "ndvi_max_value": 0.8,
        "ndvi_min_value": 0.1,
        "albedo_value": 0.1,
        "b_value": 0.1,
        "landcover_value": 10.0,
        "clay_fraction_value": 0.3,
        "bulk_density_value": 1.3,
        "h_static_value": 0.1,
        "fixed_omega_value": float("nan"),
        "exp0_h_value": float("nan"),
        "exp0_alpha_value": float("nan"),
        "config": OmegaConfig(temp_scheme="ORIG_TS", exp_mode="DH", block_days=8),
    }
    kwargs.update(overrides)
    return kwargs


class OmegaClayNanSkipTests(unittest.TestCase):
    def test_retrieve_skips_nan_clay_without_raising(self) -> None:
        result = retrieve_omega_pixel_timeseries(
            **_base_pixel_kwargs(clay_fraction_value=float("nan"))
        )
        self.assertTrue(np.all(np.isnan(result["OMEGA"])))
        self.assertEqual(result["n_use"], 0)

    def test_retrieve_skips_out_of_range_clay(self) -> None:
        result = retrieve_omega_pixel_timeseries(
            **_base_pixel_kwargs(clay_fraction_value=1.5)
        )
        self.assertTrue(np.all(np.isnan(result["OMEGA"])))

    def test_execute_skips_nan_clay_pixels(self) -> None:
        nt, npix = 3, 4
        payload = {
            "date_keys": [f"2025120{i}" for i in range(3, 3 + nt)],
            "TBv_mat": np.full((nt, npix), 250.0),
            "TBh_mat": np.full((nt, npix), 230.0),
            "IA_mat": np.full((nt, npix), 40.0),
            "Ts_mat": np.full((nt, npix), 290.0),
            "SMref_mat": np.full((nt, npix), 0.2),
            "NDVI_mat": np.full((nt, npix), 0.4),
            "SF_mat": np.full((nt, npix), 1.0),
            "Albedo": np.full(npix, 0.1),
            "B": np.full(npix, 0.1),
            "CF": np.array([0.25, np.nan, 0.35, np.nan]),
            "BD": np.full(npix, 1.3),
            "H": np.full(npix, 0.1),
            "LC": np.full(npix, 10.0),
            "NDVI_v_max": np.full(npix, 0.8),
            "NDVI_v_min": np.full(npix, 0.1),
        }
        result = execute_omega_retrieval(
            payload,
            config=OmegaConfig(temp_scheme="ORIG_TS", exp_mode="DH", block_days=8),
            field_config=OmegaFieldConfig(),
        )
        omega = result["OMEGA_mat"]
        self.assertTrue(np.all(np.isnan(omega[:, 1])))
        self.assertTrue(np.all(np.isnan(omega[:, 3])))
        # Finite-CF columns should attempt retrieval (may still be NaN if residual fails,
        # but must not raise and should leave an array of shape (nt, npix)).
        self.assertEqual(omega.shape, (nt, npix))


if __name__ == "__main__":
    unittest.main()
