"""Physics kernel prototypes preserve current Mironov/Fresnel behavior."""
from __future__ import annotations

import unittest

from algorithms.physics import (
    _SCALAR_KERNELS_USE_NUMBA,
    _fresnel_reflectance_kernel,
    _fresnel_reflectance_kernel_py,
    _load_scalar_kernel_impls,
    _mironov_dielectric_kernel,
    _mironov_dielectric_kernel_py,
    build_fresnel_context,
    build_mironov_context,
    fresnel_reflectance,
    fresnel_reflectance_from_context,
    mironov_dielectric,
    mironov_dielectric_from_context,
)


class PhysicsKernelPrototypeTests(unittest.TestCase):
    def test_force_python_loader_returns_fallback_implementations(self) -> None:
        mironov_impl, fresnel_impl, use_numba = _load_scalar_kernel_impls(force_python=True)

        self.assertIs(mironov_impl, _mironov_dielectric_kernel_py)
        self.assertIs(fresnel_impl, _fresnel_reflectance_kernel_py)
        self.assertFalse(use_numba)

    def test_mironov_kernel_matches_context_api_on_both_branches(self) -> None:
        context = build_mironov_context(1.4, 0.32)
        soil_moistures = (0.02, context.zxmvt, 0.18, 0.37)

        for soil_moisture in soil_moistures:
            with self.subTest(soil_moisture=soil_moisture):
                epsilon = mironov_dielectric_from_context(soil_moisture, context)
                epsilon_real, epsilon_imag = _mironov_dielectric_kernel(
                    soil_moisture,
                    context.zxmvt,
                    context.znd,
                    context.zkd,
                    context.znb,
                    context.zkb,
                    context.znu,
                    context.zku,
                )
                self.assertAlmostEqual(epsilon.real, epsilon_real)
                self.assertAlmostEqual(epsilon.imag, epsilon_imag)

    def test_mironov_public_api_still_matches_context_path(self) -> None:
        freq_ghz = 1.4
        clay_fraction = 0.28
        context = build_mironov_context(freq_ghz, clay_fraction)

        for soil_moisture in (0.03, 0.11, 0.24, 0.41):
            with self.subTest(soil_moisture=soil_moisture):
                expected = mironov_dielectric(freq_ghz, soil_moisture, clay_fraction)
                actual = mironov_dielectric_from_context(soil_moisture, context)
                self.assertAlmostEqual(expected.real, actual.real)
                self.assertAlmostEqual(expected.imag, actual.imag)

    def test_fresnel_kernel_matches_context_api(self) -> None:
        context = build_fresnel_context(40.0)
        epsilons = (
            complex(6.5, 0.8),
            complex(12.0, 1.6),
            complex(23.5, 4.2),
        )

        for epsilon in epsilons:
            with self.subTest(epsilon=epsilon):
                expected_rh, expected_rv = fresnel_reflectance_from_context(epsilon, context)
                actual_rh, actual_rv = _fresnel_reflectance_kernel(
                    float(epsilon.real),
                    float(epsilon.imag),
                    context.cos_theta,
                    context.sin_theta_sq,
                )
                self.assertAlmostEqual(expected_rh, actual_rh)
                self.assertAlmostEqual(expected_rv, actual_rv)

    def test_loaded_kernel_matches_python_baseline(self) -> None:
        context = build_mironov_context(1.4, 0.31)
        epsilon_real, epsilon_imag = _mironov_dielectric_kernel(0.21, context.zxmvt, context.znd, context.zkd, context.znb, context.zkb, context.znu, context.zku)
        epsilon_real_py, epsilon_imag_py = _mironov_dielectric_kernel_py(
            0.21,
            context.zxmvt,
            context.znd,
            context.zkd,
            context.znb,
            context.zkb,
            context.znu,
            context.zku,
        )
        self.assertAlmostEqual(epsilon_real, epsilon_real_py)
        self.assertAlmostEqual(epsilon_imag, epsilon_imag_py)

        fresnel = build_fresnel_context(40.0)
        rh, rv = _fresnel_reflectance_kernel(epsilon_real, epsilon_imag, fresnel.cos_theta, fresnel.sin_theta_sq)
        rh_py, rv_py = _fresnel_reflectance_kernel_py(
            epsilon_real_py,
            epsilon_imag_py,
            fresnel.cos_theta,
            fresnel.sin_theta_sq,
        )
        self.assertAlmostEqual(rh, rh_py)
        self.assertAlmostEqual(rv, rv_py)
        self.assertIsInstance(_SCALAR_KERNELS_USE_NUMBA, bool)

    def test_fresnel_public_api_still_matches_context_path(self) -> None:
        theta_deg = 40.0
        context = build_fresnel_context(theta_deg)
        epsilon = complex(14.25, 2.35)

        expected = fresnel_reflectance(theta_deg, epsilon)
        actual = fresnel_reflectance_from_context(epsilon, context)

        self.assertAlmostEqual(expected[0], actual[0])
        self.assertAlmostEqual(expected[1], actual[1])


if __name__ == "__main__":
    unittest.main()
