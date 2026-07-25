"""Algorithm kernel floating-point edge cases (no change to nominal physics)."""

from __future__ import annotations

import math
import unittest

import numpy as np

from algorithms.physics import (
    _fresnel_reflectance_kernel_py,
    tau_from_ndvi,
    vwc_from_ndvi,
)
from algorithms.omega import tb_forward_single_temp
from algorithms.omega_sf import _forward_tb
from algorithms.inversion import build_tb_model_context


class PhysicsFpEdgeTests(unittest.TestCase):
    def test_vwc_from_ndvi_rejects_ndvi_min_near_one(self) -> None:
        ndvi = np.array([0.5, 0.6])
        out = vwc_from_ndvi(
            ndvi,
            ndvi_max=0.8,
            ndvi_min=1.0,
            landcover=np.array([10, 10]),
            stem_factor=3.0,
        )
        self.assertTrue(np.all(np.isnan(out)))
        self.assertFalse(np.any(np.isinf(out)))

    def test_vwc_from_ndvi_rejects_tiny_denom(self) -> None:
        out = vwc_from_ndvi(
            np.array([0.5]),
            ndvi_max=0.8,
            ndvi_min=1.0 - 1e-15,
            landcover=np.array([12]),
            stem_factor=2.0,
        )
        self.assertTrue(math.isnan(float(out[0])))
        self.assertFalse(math.isinf(float(out[0])))

    def test_tau_from_ndvi_rejects_grazing_angle(self) -> None:
        for theta in (89.999, 90.0, 90.001):
            with self.subTest(theta=theta):
                tau = tau_from_ndvi(
                    ndvi=0.4,
                    ndvi_max=0.7,
                    ndvi_min=0.1,
                    landcover=10,
                    b_param=0.12,
                    stem_factor=2.0,
                    theta_deg=theta,
                )
                self.assertTrue(np.all(np.isnan(np.asarray(tau))))

    def test_fresnel_near_singular_denom_is_nan_or_finite(self) -> None:
        # 掠射 + 极端介电：不得产生 inf
        rh, rv = _fresnel_reflectance_kernel_py(1.0000001, 0.0, 1e-16, 1.0)
        for value in (rh, rv):
            self.assertTrue(math.isnan(value) or math.isfinite(value))
            if math.isfinite(value):
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0 + 1e-9)


class OmegaForwardFpTests(unittest.TestCase):
    def test_tb_forward_small_tau_finite(self) -> None:
        tbv, tbh = tb_forward_single_temp(
            soil_moisture=0.2,
            tau_value=1e-10,
            h_value=0.5,
            alpha_value=0.1,
            omega_value=0.05,
            ts_value=300.0,
            theta_deg=40.0,
            clay_fraction=0.3,
            freq_ghz=1.4,
        )
        self.assertTrue(math.isfinite(tbv) and math.isfinite(tbh))

    def test_tb_forward_large_tau_finite(self) -> None:
        tbv, tbh = tb_forward_single_temp(
            soil_moisture=0.2,
            tau_value=5.0,
            h_value=0.5,
            alpha_value=0.1,
            omega_value=0.05,
            ts_value=300.0,
            theta_deg=40.0,
            clay_fraction=0.3,
            freq_ghz=1.4,
        )
        self.assertTrue(math.isfinite(tbv) and math.isfinite(tbh))


class OmegaSfForwardFpTests(unittest.TestCase):
    def test_forward_tb_uses_theta_and_returns_finite(self) -> None:
        ctx = build_tb_model_context(1.4, 0.3, 40.0)
        tbv, tbh = _forward_tb(
            0.2, 0.3, 0.05, 0.5, 295.0, 0.3, 0.1, 40.0, 1.4, ctx
        )
        self.assertTrue(math.isfinite(tbv) and math.isfinite(tbh))

    def test_forward_tb_grazing_returns_nan(self) -> None:
        ctx = build_tb_model_context(1.4, 0.3, 40.0)
        tbv, tbh = _forward_tb(
            0.2, 0.3, 0.05, 0.5, 295.0, 0.3, 0.1, 90.0, 1.4, ctx
        )
        self.assertTrue(math.isnan(tbv) and math.isnan(tbh))


if __name__ == "__main__":
    unittest.main()
