"""Direct unit tests for the module-level block-solve helpers extracted from
``retrieve_omega_pixel_timeseries``.

These complement ``test_omega_retrieval_golden.py`` (which locks end-to-end
numerics) by exercising each helper in isolation: shape/finite-ness, the
fixed-mode short-circuit, bounded-scalar bounds, and the EXP2 L-curve scan.
"""

from __future__ import annotations

import unittest

import numpy as np

from algorithms.omega import (
    OmegaConfig,
    _build_tb_forward_contexts,
    _evaluate_block_fit,
    _make_block_residual_fun,
    _scan_exp2_lambda,
    _select_tb_forward_contexts,
    _solve_block_omega,
    make_date_blocks,
)


def _block_payload(nt_use: int = 4, is_dual: bool = False) -> dict:
    ia = np.full(nt_use, 40.0)
    ctx_all = _build_tb_forward_contexts(ia, 1.4, 0.3)
    use = np.arange(nt_use, dtype=np.int64)
    return {
        "use": use,
        "tbv": np.array([250.0, 252.0, 248.0, 251.0][:nt_use]),
        "tbh": np.array([230.0, 232.0, 228.0, 231.0][:nt_use]),
        "ts": np.array([290.0, 292.0, 288.0, 291.0][:nt_use]),
        "tc": np.array([286.0, 288.0, 284.0, 287.0][:nt_use]) if is_dual else None,
        "tg": np.array([283.0, 285.0, 281.0, 284.0][:nt_use]) if is_dual else None,
        "tau_star": np.full(nt_use, 0.3),
        "sm_ref": np.full(nt_use, 0.2),
        "ia": ia,
        "model_contexts": _select_tb_forward_contexts(ctx_all, use),
    }


class MakeBlockResidualFunTests(unittest.TestCase):
    def test_single_temp_returns_finite_vector(self) -> None:
        bp = _block_payload()
        h = np.full(4, 0.6)
        alpha = np.full(4, 0.12)
        rf = _make_block_residual_fun(
            bp, 0.0, float("nan"),
            is_dual=False, h_series=h, alpha_series=alpha,
            clay_fraction_value=0.3, freq_ghz=1.4,
        )
        r = np.asarray(rf(0.1))
        self.assertEqual(r.ndim, 1)
        self.assertGreaterEqual(r.size, 2 * 4)
        self.assertTrue(np.all(np.isfinite(r)))

    def test_dual_temp_returns_finite_vector(self) -> None:
        bp = _block_payload(is_dual=True)
        h = np.full(4, 0.6)
        alpha = np.full(4, 0.12)
        rf = _make_block_residual_fun(
            bp, 1.0, 0.05,
            is_dual=True, h_series=h, alpha_series=alpha,
            clay_fraction_value=0.3, freq_ghz=1.4,
        )
        r = np.asarray(rf(0.1))
        self.assertEqual(r.ndim, 1)
        self.assertGreaterEqual(r.size, 2 * 4)
        self.assertTrue(np.all(np.isfinite(r)))


class EvaluateBlockFitTests(unittest.TestCase):
    def test_empty_use_returns_nan_triple(self) -> None:
        bp = _block_payload()
        bp["use"] = np.array([], dtype=np.int64)
        v, h, hv = _evaluate_block_fit(
            bp, 0.1, is_dual=False, h_series=np.zeros(4), alpha_series=np.zeros(4),
        )
        self.assertTrue(np.isnan(v) and np.isnan(h) and np.isnan(hv))

    def test_single_temp_returns_finite_triple(self) -> None:
        bp = _block_payload()
        h = np.full(4, 0.6)
        alpha = np.full(4, 0.12)
        v, hh, hv = _evaluate_block_fit(
            bp, 0.1, is_dual=False, h_series=h, alpha_series=alpha,
        )
        for val in (v, hh, hv):
            self.assertTrue(np.isfinite(val), f"{val} not finite")
        self.assertGreaterEqual(v, 0.0)
        self.assertGreaterEqual(hh, 0.0)
        self.assertGreaterEqual(hv, 0.0)


class SolveBlockOmegaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = OmegaConfig(temp_scheme="ORIG_TS", exp_mode="DH", block_days=8)
        self.bp = _block_payload()
        self.h = np.full(4, 0.6)
        self.alpha = np.full(4, 0.12)
        self.kw = dict(
            config=self.cfg, is_dual=False,
            h_series=self.h, alpha_series=self.alpha, clay_fraction_value=0.3,
        )

    def test_fixed_mode_short_circuits_to_omega_fixed(self) -> None:
        res = _solve_block_omega(
            self.bp, 0.0, float("nan"), fixed_mode=True, omega_fixed=0.1, **self.kw,
        )
        self.assertEqual(res["algorithm"], "FIXED")
        self.assertAlmostEqual(res["omega"], 0.1)
        self.assertEqual(res["exitflag"], 9.0)
        self.assertTrue(np.isfinite(res["final_cost"]))

    def test_scalar_bounded_within_bounds(self) -> None:
        res = _solve_block_omega(
            self.bp, 0.0, float("nan"), fixed_mode=False, omega_fixed=float("nan"),
            **self.kw,
        )
        self.assertEqual(res["algorithm"], "SCALAR_BOUNDED")
        lo, hi = self.cfg.bounds_omega
        self.assertGreaterEqual(res["omega"], lo)
        self.assertLessEqual(res["omega"], hi)
        self.assertTrue(np.isfinite(res["final_cost"]))
        self.assertTrue(np.isfinite(res["firstorderopt"]))


class ScanExp2LambdaTests(unittest.TestCase):
    def test_returns_lambda_star_finite(self) -> None:
        nt = 12
        date_keys = [f"202512{i+1:02d}" for i in range(nt)]
        cfg = OmegaConfig(temp_scheme="ORIG_TS", exp_mode="EXP2", block_days=8)
        blocks, block_start_dates = make_date_blocks(date_keys, cfg.block_days)
        block_index_arrays = [np.asarray(b, dtype=np.int64) for b in blocks]
        ia = np.full(nt, 40.0)
        ctx_all = _build_tb_forward_contexts(ia, 1.4, 0.3)
        tbv = 255.0 + 8.0 * np.sin(np.linspace(0, 3 * np.pi, nt))
        tbh = 235.0 + 7.0 * np.cos(np.linspace(0, 3 * np.pi, nt))
        ts = 292.0 + 4.0 * np.sin(np.linspace(0, 2 * np.pi, nt) + 0.5)
        h = np.full(nt, 0.6)
        alpha = np.full(nt, 0.12)
        block_payloads = []
        for bia in block_index_arrays:
            block_payloads.append({
                "use": bia,
                "tbv": tbv[bia], "tbh": tbh[bia], "ts": ts[bia],
                "tau_star": np.full(bia.size, 0.3),
                "sm_ref": np.full(bia.size, 0.2),
                "ia": ia[bia],
                "model_contexts": _select_tb_forward_contexts(ctx_all, bia),
            })
        info = _scan_exp2_lambda(
            config=cfg, kb=len(blocks), block_start_dates=block_start_dates,
            block_payloads=block_payloads, is_dual=False, h_series=h,
            alpha_series=alpha, clay_fraction_value=0.3, omega_fixed=float("nan"),
        )
        self.assertTrue(np.isfinite(info["lambda_star"]))
        self.assertEqual(np.asarray(info["misfit"]).ndim, 1)
        self.assertEqual(np.asarray(info["roughness"]).ndim, 1)


if __name__ == "__main__":
    unittest.main()
