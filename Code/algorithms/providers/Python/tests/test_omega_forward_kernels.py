"""OMEGA forward kernel prototypes preserve single-temp behavior."""
from __future__ import annotations

import unittest

from algorithms.physics import build_fresnel_context, build_mironov_context
from algorithms.omega import (
    OmegaTbForwardContext,
    _tb_forward_dual_temp_kernel,
    _tb_forward_dual_temp_with_context,
    _tb_forward_single_temp_kernel,
    _tb_forward_single_temp_with_context,
    tb_forward_dual_temp,
    tb_forward_single_temp,
)


class OmegaForwardKernelPrototypeTests(unittest.TestCase):
    def test_single_temp_kernel_matches_public_forward_without_context(self) -> None:
        freq_ghz = 1.4
        clay_fraction = 0.31
        theta_deg = 40.0
        dielectric = build_mironov_context(freq_ghz, clay_fraction)
        fresnel = build_fresnel_context(theta_deg)
        cases = (
            (0.09, 0.15, 0.65, 0.18, 0.10, 296.0, 1.0),
            (0.21, 0.42, 1.10, 0.12, 0.06, 302.5, 0.95),
            (0.34, 0.80, 0.75, -0.10, 0.18, 289.5, 1.0),
        )

        for case in cases:
            with self.subTest(case=case):
                soil_moisture, tau_value, h_value, alpha_value, omega_value, ts_value, scale = case
                expected_tbv, expected_tbh = tb_forward_single_temp(
                    soil_moisture,
                    tau_value,
                    h_value,
                    alpha_value,
                    omega_value,
                    ts_value,
                    theta_deg,
                    clay_fraction,
                    freq_ghz,
                    scale,
                    None,
                )
                actual_tbv, actual_tbh = _tb_forward_single_temp_kernel(
                    soil_moisture,
                    tau_value,
                    h_value,
                    alpha_value,
                    omega_value,
                    ts_value,
                    scale,
                    dielectric.zxmvt,
                    dielectric.znd,
                    dielectric.zkd,
                    dielectric.znb,
                    dielectric.zkb,
                    dielectric.znu,
                    dielectric.zku,
                    fresnel.cos_theta,
                    fresnel.sin_theta_sq,
                    fresnel.cos_theta_sq,
                )
                self.assertAlmostEqual(expected_tbv, actual_tbv)
                self.assertAlmostEqual(expected_tbh, actual_tbh)

    def test_single_temp_with_context_matches_public_forward_context_path(self) -> None:
        freq_ghz = 1.4
        clay_fraction = 0.28
        theta_deg = 52.5
        context = OmegaTbForwardContext(
            dielectric=build_mironov_context(freq_ghz, clay_fraction),
            fresnel=build_fresnel_context(theta_deg),
        )

        expected_tbv, expected_tbh = tb_forward_single_temp(
            0.19,
            0.33,
            0.84,
            0.16,
            0.11,
            300.2,
            theta_deg,
            clay_fraction,
            freq_ghz,
            1.0,
            context,
        )
        actual_tbv, actual_tbh = _tb_forward_single_temp_with_context(
            0.19,
            0.33,
            0.84,
            0.16,
            0.11,
            300.2,
            1.0,
            context,
        )

        self.assertAlmostEqual(expected_tbv, actual_tbv)
        self.assertAlmostEqual(expected_tbh, actual_tbh)

    def test_dual_temp_kernel_matches_public_forward_without_context(self) -> None:
        freq_ghz = 1.4
        clay_fraction = 0.31
        theta_deg = 40.0
        dielectric = build_mironov_context(freq_ghz, clay_fraction)
        fresnel = build_fresnel_context(theta_deg)
        cases = (
            (0.09, 0.15, 0.65, 0.18, 0.10, 298.0, 294.0, 1.0),
            (0.21, 0.42, 1.10, 0.12, 0.06, 301.5, 304.5, 0.95),
            (0.34, 0.80, 0.75, -0.10, 0.18, 292.0, 287.5, 1.0),
        )

        for case in cases:
            with self.subTest(case=case):
                soil_moisture, tau_value, h_value, alpha_value, omega_value, tc_value, tg_value, scale = case
                expected_tbv, expected_tbh = tb_forward_dual_temp(
                    soil_moisture,
                    tau_value,
                    h_value,
                    alpha_value,
                    omega_value,
                    tc_value,
                    tg_value,
                    theta_deg,
                    clay_fraction,
                    freq_ghz,
                    scale,
                    None,
                )
                actual_tbv, actual_tbh = _tb_forward_dual_temp_kernel(
                    soil_moisture,
                    tau_value,
                    h_value,
                    alpha_value,
                    omega_value,
                    tc_value,
                    tg_value,
                    scale,
                    dielectric.zxmvt,
                    dielectric.znd,
                    dielectric.zkd,
                    dielectric.znb,
                    dielectric.zkb,
                    dielectric.znu,
                    dielectric.zku,
                    fresnel.cos_theta,
                    fresnel.sin_theta_sq,
                    fresnel.cos_theta_sq,
                )
                self.assertAlmostEqual(expected_tbv, actual_tbv)
                self.assertAlmostEqual(expected_tbh, actual_tbh)

    def test_dual_temp_with_context_matches_public_forward_context_path(self) -> None:
        freq_ghz = 1.4
        clay_fraction = 0.28
        theta_deg = 52.5
        context = OmegaTbForwardContext(
            dielectric=build_mironov_context(freq_ghz, clay_fraction),
            fresnel=build_fresnel_context(theta_deg),
        )

        expected_tbv, expected_tbh = tb_forward_dual_temp(
            0.19,
            0.33,
            0.84,
            0.16,
            0.11,
            302.2,
            296.7,
            theta_deg,
            clay_fraction,
            freq_ghz,
            1.0,
            context,
        )
        actual_tbv, actual_tbh = _tb_forward_dual_temp_with_context(
            0.19,
            0.33,
            0.84,
            0.16,
            0.11,
            302.2,
            296.7,
            1.0,
            context,
        )

        self.assertAlmostEqual(expected_tbv, actual_tbv)
        self.assertAlmostEqual(expected_tbh, actual_tbh)


if __name__ == "__main__":
    unittest.main()
