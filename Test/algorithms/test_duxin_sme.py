"""DuXin 时序土壤水分估算算法移植正确性测试。

对照 MATLAB 原版（providers/Matlab/Original-Time_series_soil_moisture_estimation-DuXin）
验证：Fresnel 公式、查找表单调性、滑窗 alpha 解析解、查表反演、Topp 模型
以及端到端主流程。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PROVIDER_ROOT = Path(__file__).resolve().parents[2] / "Code" / "algorithms" / "providers" / "Python"
if str(PROVIDER_ROOT) not in sys.path:
    sys.path.insert(0, str(PROVIDER_ROOT))

from algorithms.duxin_sme import (  # noqa: E402
    DuxinSmeConfig,
    AlphaLUT,
    alpha_calculation_hh,
    alpha_calculation_vv,
    alpha_to_epsilon,
    build_alpha_lut,
    run_time_series_sme,
    time_series_alpha_retrieval,
    topp_soil_moisture,
)


# ─── Fresnel 幅值公式（忠实移植验证）──────────────────────────────────────


class TestAlphaCalculation:
    def test_hh_matches_matlab_formula_by_hand(self):
        # theta=0.5 rad, epsilon=10：
        # sin²(0.5)=0.229849, cos(0.5)=0.877583, sqrt(10-0.229849)=3.125716
        # alpha = 9 / (0.877583+3.125716)² = 9 / 16.02640 = 0.561571
        value = float(alpha_calculation_hh(0.5, 10.0))
        assert value == pytest.approx(0.561571, abs=1e-5)

    def test_hh_equals_fresnel_field_amplitude(self):
        """实数 ε 下 HH 公式等于 Fresnel 场强反射系数幅值：
        (ε-1)/(cosθ+√(ε-sin²θ))² == |(cosθ-√(ε-sin²θ))/(cosθ+√(ε-sin²θ))|
        （因 (cosθ-r)(cosθ+r) = 1-ε，标准功率反射率为其平方）。"""
        rng = np.random.default_rng(42)
        theta = rng.uniform(0.3, 1.2, 50)
        epsilon = rng.uniform(4.0, 35.0, 50)
        ours = alpha_calculation_hh(theta, epsilon)
        root = np.sqrt(epsilon - np.sin(theta) ** 2)
        field_amplitude = np.abs((np.cos(theta) - root) / (np.cos(theta) + root))
        np.testing.assert_allclose(ours, field_amplitude, rtol=1e-10)
        # alpha² == 标准功率反射率
        power_reflectance = field_amplitude**2
        np.testing.assert_allclose(ours**2, power_reflectance, rtol=1e-10)

    def test_vv_matches_matlab_formula_by_hand(self):
        # theta=0.5, epsilon=10：
        # sin²=0.229849, cos=0.877583, sqrt(10-0.229849)=3.125716
        # B_a = |9×(0.229849 - 10×1.229849)| = 108.61775
        # den = (10×0.877583 + 3.125716)² = (11.901542)² = 141.64670
        # alpha = 108.61775/141.64670 = 0.766823
        value = float(alpha_calculation_vv(0.5, 10.0))
        assert value == pytest.approx(0.766823, abs=1e-5)

    def test_hh_monotonic_in_epsilon(self):
        """HH alpha 对 epsilon 单调递增（查表反演的前提）。"""
        theta = np.full(311, 0.7)
        epsilon = np.linspace(4.0, 35.0, 311)
        alpha = alpha_calculation_hh(theta, epsilon)
        assert np.all(np.diff(alpha) > 0)

    def test_broadcast_shapes(self):
        theta = np.array([0.3, 0.7, 1.2])
        epsilon = np.array([[4.0, 10.0], [20.0, 35.0], [6.0, 8.0]])
        assert alpha_calculation_hh(theta[:, None], epsilon).shape == (3, 2)


# ─── 查找表 ────────────────────────────────────────────────────────────────


class TestAlphaLUT:
    def test_lut_grid_matches_matlab_defaults(self):
        lut = build_alpha_lut(polarization="hh")
        assert lut.theta_grid.shape == (901,)
        assert lut.epsilon_grid.shape == (311,)
        assert lut.theta_grid[0] == pytest.approx(0.3)
        assert lut.theta_grid[-1] == pytest.approx(1.2)
        assert lut.epsilon_grid[0] == pytest.approx(4.0)
        assert lut.epsilon_grid[-1] == pytest.approx(35.0)

    def test_lut_values_equal_direct_formula(self):
        lut = build_alpha_lut(polarization="hh")
        assert float(lut.table[0, 0]) == pytest.approx(
            float(alpha_calculation_hh(0.3, 4.0)), rel=1e-12
        )
        assert float(lut.table[-1, -1]) == pytest.approx(
            float(alpha_calculation_hh(1.2, 35.0)), rel=1e-12
        )

    def test_column_for_theta_interpolates(self):
        lut = build_alpha_lut(polarization="hh")
        mid_theta = 0.5 * (lut.theta_grid[100] + lut.theta_grid[101])
        column = lut.column_for_theta(float(mid_theta))
        expected = 0.5 * (lut.table[100] + lut.table[101])
        np.testing.assert_allclose(column, expected, rtol=1e-12)

    def test_vv_lut_distinct_from_hh(self):
        hh = build_alpha_lut(polarization="hh")
        vv = build_alpha_lut(polarization="vv")
        assert not np.allclose(hh.table, vv.table)


# ─── Topp 模型 ─────────────────────────────────────────────────────────────


class TestToppModel:
    def test_topp_known_values(self):
        # ε=4: -5.3 + 2.92*4 - 0.055*16 + 0.0004*64 = -5.3+11.68-0.88+0.0256 = 5.5256
        assert topp_soil_moisture(4.0) == pytest.approx(5.5256, abs=1e-10)
        # ε=20: -5.3 + 58.4 - 22.0 + 3.2 = 34.3
        assert topp_soil_moisture(20.0) == pytest.approx(34.3, abs=1e-10)

    def test_topp_monotonic_in_range(self):
        epsilon = np.linspace(4.0, 35.0, 200)
        assert np.all(np.diff(topp_soil_moisture(epsilon)) > 0)

    def test_topp_accepts_arrays(self):
        result = topp_soil_moisture(np.array([4.0, 10.0, 20.0]))
        assert result.shape == (3,)


# ─── 时序 alpha 反演 ───────────────────────────────────────────────────────


class TestTimeSeriesAlphaRetrieval:
    def test_constant_observation_gives_constant_alpha_within_bounds(self):
        """常数观测序列：零空间 v=常数，t 中点应落在 alpha 物理界内。"""
        rng = np.random.default_rng(7)
        rows, cols, n = 3, 4, 8
        obsv = rng.uniform(0.05, 0.5, (rows, cols))[:, :, None].repeat(n, axis=2)
        ang = np.full((rows, cols), 0.6)
        alpha = time_series_alpha_retrieval(obsv, ang)
        assert alpha.shape == (rows, cols, n)
        # 常数序列：所有期 alpha 相同
        for i in range(rows):
            for j in range(cols):
                np.testing.assert_allclose(alpha[i, j], alpha[i, j, 0], rtol=1e-12)
        # alpha 非负
        assert np.all(alpha >= 0)

    def test_alpha_within_physical_bounds(self):
        """解出的 alpha 必须落在 [alpha(θ,ε_min), alpha(θ,ε_max)] 内。"""
        rng = np.random.default_rng(11)
        rows, cols, n = 4, 4, 6
        obsv = rng.uniform(0.02, 0.8, (rows, cols, n))
        ang = rng.uniform(0.35, 1.15, (rows, cols))
        alpha = time_series_alpha_retrieval(obsv, ang, polarization="hh")
        lb = alpha_calculation_hh(ang, 4.0)
        ub = alpha_calculation_hh(ang, 35.0)
        # 逐像素严格验证（0 解跳过）
        for i in range(rows):
            for j in range(cols):
                for k in range(n):
                    if alpha[i, j, k] > 0:
                        assert alpha[i, j, k] >= lb[i, j] * 0.999
                        assert alpha[i, j, k] <= ub[i, j] * 1.001

    def test_sliding_window_average_smooths(self):
        """多窗口 nanmean 输出应与窗内解一致量级（构造平滑序列）。"""
        n = 6
        obsv = np.full((1, 1, n), 0.2)
        obsv[0, 0, :] = 0.2 + 0.01 * np.arange(n)
        ang = np.full((1, 1), 0.6)
        alpha_full = time_series_alpha_retrieval(obsv, ang, num_step=n)
        alpha_win4 = time_series_alpha_retrieval(obsv, ang, num_step=4)
        # 单调平滑序列的 alpha 也应近似单调
        assert np.all(np.diff(alpha_full[0, 0]) >= -1e-9)
        assert np.all(np.diff(alpha_win4[0, 0]) >= -1e-9)

    def test_invalid_observations_yield_zero(self):
        """非正/NaN 观测 → alpha=0（对应原版 NaN/Inf→0）。"""
        obsv = np.ones((2, 2, 4))
        obsv[0, 0, :] = 0.0  # 全零观测
        obsv[0, 1, 2] = np.nan
        ang = np.full((2, 2), 0.6)
        alpha = time_series_alpha_retrieval(obsv, ang)
        assert np.all(alpha[0, 0] == 0.0)

    def test_rejects_bad_shapes(self):
        with pytest.raises(ValueError):
            time_series_alpha_retrieval(np.ones((3, 4)), np.ones((3, 4)))
        with pytest.raises(ValueError):
            time_series_alpha_retrieval(np.ones((3, 4, 5)), np.ones((2, 4)))
        with pytest.raises(ValueError):
            time_series_alpha_retrieval(np.ones((3, 4, 5)), np.ones((3, 4)), num_step=99)


# ─── 查表反演 + 端到端 ─────────────────────────────────────────────────────


class TestAlphaToEpsilon:
    def test_roundtrip_epsilon_via_lut(self):
        """正问题：给定 (θ, ε) 算 alpha；反问题：查表应还原 ε（误差 < 0.2）。"""
        lut = build_alpha_lut(polarization="hh")
        rng = np.random.default_rng(3)
        theta = rng.uniform(0.32, 1.18, 6)
        epsilon_true = rng.uniform(5.0, 34.0, 6)
        alpha = alpha_calculation_hh(theta, epsilon_true)
        alpha_stack = alpha[:, None, None].transpose(1, 2, 0)  # (1,1,6)
        ang = theta[0] * np.ones((1, 1))
        # 每个像素单测（theta 不同）
        for idx in range(6):
            single = np.array([[[alpha[idx]]]])
            single_ang = np.array([[theta[idx]]])
            epsilon_est = alpha_to_epsilon(single, single_ang, lut=lut)
            assert float(epsilon_est[0, 0, 0]) == pytest.approx(epsilon_true[idx], abs=0.2)

    def test_out_of_range_alpha_returns_zero(self):
        lut = build_alpha_lut(polarization="hh")
        alpha = np.array([[[alpha_calculation_hh(0.6, 3.0)]]])  # ε<4 → 越下界
        ang = np.array([[0.6]])
        assert float(alpha_to_epsilon(alpha, ang, lut=lut)[0, 0, 0]) == 0.0


class TestRunTimeSeriesSme:
    def test_end_to_end_physical_range(self):
        """端到端：合成时序 → 水分输出在物理合理范围 [0, 60%]。"""
        rng = np.random.default_rng(21)
        rows, cols, n = 5, 6, 8
        # 合成平滑后向散射（模拟干到湿渐变）
        base = rng.uniform(0.05, 0.3, (rows, cols))
        trend = np.linspace(0.8, 1.6, n)
        obsv = base[:, :, None] * trend[None, None, :]
        ang = rng.uniform(0.35, 1.15, (rows, cols))
        result = run_time_series_sme(obsv, ang, DuxinSmeConfig(polarization="hh"))
        assert set(result) == {"soil_alpha", "soil_epsilon", "soil_moisture"}
        moisture = result["soil_moisture"]
        assert moisture.shape == (rows, cols, n)
        valid = moisture > 0
        if valid.any():
            assert moisture[valid].max() <= 60.0
            assert moisture[valid].min() >= 0.0
        # epsilon 有效处 Topp 关系成立
        epsilon = result["soil_epsilon"]
        eps_valid = epsilon > 0
        if eps_valid.any():
            expected = topp_soil_moisture(epsilon[eps_valid])
            np.testing.assert_allclose(moisture[eps_valid], expected, rtol=1e-10)

    def test_vv_channel_runs(self):
        rng = np.random.default_rng(5)
        obsv = rng.uniform(0.05, 0.4, (3, 3, 5))
        ang = np.full((3, 3), 0.6)
        result = run_time_series_sme(obsv, ang, DuxinSmeConfig(polarization="vv"))
        assert result["soil_moisture"].shape == (3, 3, 5)

    def test_rejects_invalid_polarization(self):
        with pytest.raises(ValueError):
            run_time_series_sme(np.ones((2, 2, 3)), np.ones((2, 2)), DuxinSmeConfig(polarization="hv"))


# ─── module 注册 ──────────────────────────────────────────────────────────


class TestModuleRegistration:
    def test_module_registered_in_registry(self):
        from modules.registry import get_module, list_modules

        names = list_modules()
        assert "duxin_time_series_sme" in names
        module = get_module("duxin_time_series_sme")
        assert module.name == "duxin_time_series_sme"
        # 别名解析
        assert get_module("duxin_sme") is module

    def test_module_ports_declared(self):
        from modules.registry import get_module

        module = get_module("duxin_time_series_sme")
        input_names = [p.name for p in module.input_ports]
        output_names = [p.name for p in module.output_ports]
        assert "datasource_selection" in input_names
        assert "algorithm_params" in input_names
        assert "manifest" in output_names
