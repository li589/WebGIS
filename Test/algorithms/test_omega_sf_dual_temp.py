"""SF 双温度方案（temp_scheme=DUAL）行为测试。

覆盖四层：
1. 数学层 parity：omega_sf._forward_tb_dual / _ddca_dual_temp 与
   algorithms.omega 已验证的 tb_forward_dual_temp / ddca_dual_temp 数值一致
2. 残差结构：_resid_halpha_dual_temp / _resid_omega_block_dual_temp 的
   残差向量长度、正则尾项与自洽归零
3. 像元反演 round-trip：由 _forward_tb_dual 生成无噪合成 TB →
   execute_pixel_inversion（DUAL）回收 h*/alpha*/omega/sm
4. 有效性掩码：_build_chunk_validity_mask 的 DUAL 分支（tc/tsoil1/tsoil2）
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math

import numpy as np
import pytest

from algorithms.inversion import build_tb_model_context
from algorithms.omega import ddca_dual_temp as ref_ddca_dual_temp
from algorithms.omega import tb_forward_dual_temp as ref_tb_forward_dual_temp
from algorithms.omega_sf import (
    OmegaSfConfig,
    _build_chunk_validity_mask,
    _ddca_dual_temp,
    _forward_tb_dual,
    _resid_halpha_dual_temp,
    _resid_omega_block_dual_temp,
    _step0_compute_tau_star,
    execute_pixel_inversion,
    make_viirs8_blocks,
)
from ingest.daily_bundle import build_effective_soil_temperature_scheme

_FREQ = 1.41
_CLAY = 0.31
_THETA = 40.0


# ─── 1. 数学层 parity（对照 algorithms.omega 参考实现） ──────────────────────


class TestForwardParity:
    @pytest.mark.parametrize(
        "sm,tau,h,alpha,omega,tc,tg",
        [
            (0.10, 0.15, 0.65, 0.18, 0.10, 296.0, 288.0),
            (0.21, 0.42, 1.10, 0.12, 0.06, 302.5, 291.0),
            (0.34, 0.80, 0.75, 0.10, 0.18, 289.5, 285.0),
        ],
    )
    def test_matches_reference_forward(self, sm, tau, h, alpha, omega, tc, tg) -> None:
        model_ctx = build_tb_model_context(_FREQ, _CLAY, _THETA)
        expected = ref_tb_forward_dual_temp(
            sm, tau, h, alpha, omega, tc, tg, _THETA, _CLAY, _FREQ, 1.0, None
        )
        actual = _forward_tb_dual(
            sm, tau, omega, h, tc, tg, _CLAY, _THETA, _FREQ, model_ctx, alpha=alpha
        )
        assert actual[0] == pytest.approx(expected[0], abs=1e-9)
        assert actual[1] == pytest.approx(expected[1], abs=1e-9)

    def test_alpha_none_defaults_to_01771(self) -> None:
        model_ctx = build_tb_model_context(_FREQ, _CLAY, _THETA)
        expected = ref_tb_forward_dual_temp(
            0.22, 0.3, 0.15, 0.1771, 0.10, 295.0, 290.0, _THETA, _CLAY, _FREQ, 1.0, None
        )
        actual = _forward_tb_dual(
            0.22, 0.3, 0.10, 0.15, 295.0, 290.0, _CLAY, _THETA, _FREQ, model_ctx
        )
        assert actual == pytest.approx(expected, abs=1e-9)

    def test_nan_inputs_propagate(self) -> None:
        model_ctx = build_tb_model_context(_FREQ, _CLAY, _THETA)
        tbv, tbh = _forward_tb_dual(
            float("nan"), 0.3, 0.1, 0.15, 295.0, 290.0, _CLAY, _THETA, _FREQ, model_ctx
        )
        assert math.isnan(tbv)
        assert math.isnan(tbh)


class TestDdcaParity:
    def test_recovers_truth_and_matches_reference(self) -> None:
        # 由参考前向生成自洽观测 → 两个 DDCA 应同时回收真值且彼此一致
        sm_true, tau_true = 0.22, 0.35
        h, alpha, omega = 0.15, 0.1771, 0.10
        tc, tg = 295.0, 290.0
        porosity, lambda_tau = 0.5, 20.0
        tbv, tbh = ref_tb_forward_dual_temp(
            sm_true, tau_true, h, alpha, omega, tc, tg, _THETA, _CLAY, _FREQ, 1.0, None
        )
        model_ctx = build_tb_model_context(_FREQ, _CLAY, _THETA)
        sm_sf, vod_sf = _ddca_dual_temp(
            tbv, tbh, tc, tg, tau_true, h, _CLAY, omega, porosity,
            _FREQ, _THETA, alpha, lambda_tau, model_ctx,
        )
        sm_ref, vod_ref = ref_ddca_dual_temp(
            tbv, tbh, tc, tg, tau_true, h, _CLAY, omega, porosity,
            _FREQ, _THETA, alpha, lambda_tau, None,
        )
        assert sm_sf == pytest.approx(sm_true, abs=1e-4)
        assert vod_sf == pytest.approx(tau_true, abs=1e-4)
        assert sm_sf == pytest.approx(sm_ref, abs=1e-8)
        assert vod_sf == pytest.approx(vod_ref, abs=1e-8)


# ─── 2. 残差结构 ──────────────────────────────────────────────────────────────


def _self_consistent_block(k: int = 4):
    """生成自洽双温度样本（观测 = 真值处前向）。"""
    model_ctx = build_tb_model_context(_FREQ, _CLAY, _THETA)
    h_true, alpha_true, omega_true = 0.15, 0.1771, 0.10
    sm = np.linspace(0.10, 0.32, k)
    tau = np.linspace(0.10, 0.50, k)
    tc = np.linspace(293.0, 297.0, k)
    tg = np.linspace(288.0, 292.0, k)
    theta = np.full(k, _THETA)
    tbv = np.zeros(k)
    tbh = np.zeros(k)
    for i in range(k):
        tbv[i], tbh[i] = _forward_tb_dual(
            float(sm[i]), float(tau[i]), omega_true, h_true,
            float(tc[i]), float(tg[i]), _CLAY, _THETA, _FREQ, model_ctx,
            alpha=alpha_true,
        )
    return model_ctx, h_true, alpha_true, omega_true, sm, tau, tc, tg, theta, tbv, tbh


class TestResidualStructure:
    def test_halpha_residual_shape_and_regularization_tail(self) -> None:
        (model_ctx, h_true, alpha_true, _omega, sm, tau, tc, tg, theta, tbv, tbh) = (
            _self_consistent_block(k=4)
        )
        lam_alpha, alpha0 = 1.0, 0.1771
        r = _resid_halpha_dual_temp(
            np.array([h_true, alpha_true]), tbv, tbh, tc, tg, tau, sm, theta,
            _CLAY, _FREQ, omega_low=0.10, alpha0=alpha0, lam_alpha=lam_alpha,
            w_v=1.0, w_h=1.0, model_ctx=model_ctx,
        )
        assert r.shape == (2 * 4 + 1,)
        # 自洽数据 → 数据残差归零，仅剩正则项
        np.testing.assert_allclose(r[:-1], 0.0, atol=1e-8)
        assert r[-1] == pytest.approx(math.sqrt(lam_alpha) * (alpha_true - alpha0))

    def test_halpha_residual_penalizes_wrong_h(self) -> None:
        (model_ctx, h_true, *_rest) = _self_consistent_block(k=4)
        (sm, tau, tc, tg, theta, tbv, tbh) = _rest[2:9]
        r_true = _resid_halpha_dual_temp(
            np.array([h_true, 0.1771]), tbv, tbh, tc, tg, tau, sm, theta,
            _CLAY, _FREQ, 0.10, 0.1771, 1.0, 1.0, 1.0, model_ctx,
        )
        r_wrong = _resid_halpha_dual_temp(
            np.array([h_true + 0.5, 0.1771]), tbv, tbh, tc, tg, tau, sm, theta,
            _CLAY, _FREQ, 0.10, 0.1771, 1.0, 1.0, 1.0, model_ctx,
        )
        assert np.linalg.norm(r_wrong) > np.linalg.norm(r_true)

    def test_omega_block_residual_shape(self) -> None:
        (model_ctx, _h, _a, omega_true, sm, tau, tc, tg, theta, tbv, tbh) = (
            _self_consistent_block(k=3)
        )
        h_series = np.full(3, 0.15)
        alpha_series = np.full(3, 0.1771)
        common = dict(
            tbv=tbv, tbh=tbh, tc=tc, tg=tg, tau=tau, sm_ref=sm, theta=theta,
            clay_fraction=_CLAY, freq_ghz=_FREQ, h_series=h_series,
            alpha_series=alpha_series, w_v=1.0, w_h=1.0, model_ctx=model_ctx,
        )
        # omega_prev=NaN 且 lam_smooth>0 → 无平滑尾项
        r = _resid_omega_block_dual_temp(
            omega_true, lam_smooth=1.0, omega_prev=float("nan"), **common
        )
        assert r.shape == (2 * 3,)
        np.testing.assert_allclose(r, 0.0, atol=1e-8)
        # omega_prev 有限 → 追加 sqrt(lam_smooth)·(ω-ω_prev)
        r2 = _resid_omega_block_dual_temp(
            omega_true, lam_smooth=4.0, omega_prev=0.05, **common
        )
        assert r2.shape == (2 * 3 + 1,)
        assert r2[-1] == pytest.approx(math.sqrt(4.0) * (omega_true - 0.05))


# ─── 3. 像元反演 round-trip（DUAL 全链路） ────────────────────────────────────


def _make_roundtrip_scenario(nt: int = 16):
    """构造无噪 DUAL 像元场景。

    TB 由 _forward_tb_dual 在真值处生成；TG 由
    build_effective_soil_temperature_scheme（PAPER_CT）按真值 sm 合成，
    与 execute_pixel_inversion 内部重建路径完全一致。
    """
    omega_true, h_true, alpha_true = 0.10, 0.15, 0.1771
    dates = [datetime(2025, 1, 1) + timedelta(days=i) for i in range(nt)]
    t = np.linspace(0.0, 2.0 * np.pi, nt)

    ia = np.full(nt, _THETA)
    ndvi = np.full(nt, 0.45)
    sf_col = np.full(nt, 0.5)
    ndvi_max, ndvi_min = 0.8, 0.1
    b_param = 0.32  # tau=b·VWC/cosθ 需为正；负值会被 (tau<0)→NaN 过滤
    landcover = 12
    tau_star = _step0_compute_tau_star(
        ndvi, ia, sf_col, ndvi_max, ndvi_min, landcover, b_param, nt
        )
    assert np.all(np.isfinite(tau_star)), "合成场景 tau_star 应全有限"

    sm_true = 0.20 + 0.08 * np.sin(t)
    tsoil1 = 292.0 + 3.0 * np.sin(t + 0.5)
    tsoil2 = 288.0 + 2.0 * np.cos(t)
    tc = 295.0 + 2.0 * np.sin(t)
    _ct, tg = build_effective_soil_temperature_scheme(
        sm_true, tsoil1, tsoil2,
        dual_tg_mode="PAPER_CT", ct_smref=0.30, ct_exp=0.30,
    )

    model_ctx = build_tb_model_context(_FREQ, _CLAY, _THETA)
    tbv = np.zeros(nt)
    tbh = np.zeros(nt)
    for k in range(nt):
        tbv[k], tbh[k] = _forward_tb_dual(
            float(sm_true[k]), float(tau_star[k]), omega_true, h_true,
            float(tc[k]), float(tg[k]), _CLAY, _THETA, _FREQ, model_ctx,
            alpha=alpha_true,
        )

    config = OmegaSfConfig.from_params(
        {"tb_source": "SMAP", "temp_scheme": "DUAL", "enable_parallel": False}
    )
    block_struct = make_viirs8_blocks(dates, config.block_days)
    return {
        "config": config,
        "block_struct": block_struct,
        "tbv": tbv,
        "tbh": tbh,
        "ia": ia,
        "ts": np.full(nt, np.nan),  # DUAL 路径不使用 Ts
        "sm_ref": sm_true.copy(),
        "ndvi": ndvi,
        "sf_col": sf_col,
        "ndvi_max": ndvi_max,
        "ndvi_min": ndvi_min,
        # Step-1 低 τ 模式 ω_low=albedo（Matlab ALBEDO_ij）；
        # round-trip 场景须令 albedo 与 ω 真值一致才能精确回收 h*
        "albedo": omega_true,
        "b_param": b_param,
        "clay": _CLAY,
        "porosity": 0.5,
        "h_static": 0.10,
        "landcover": landcover,
        "tc": tc,
        "tsoil1": tsoil1,
        "tsoil2": tsoil2,
        "omega_true": omega_true,
        "h_true": h_true,
        "alpha_true": alpha_true,
        "sm_true": sm_true,
        "tau_true": tau_star,
    }


class TestPixelInversionRoundTrip:
    def test_recovers_truth(self) -> None:
        s = _make_roundtrip_scenario()
        result = execute_pixel_inversion(
            s["tbv"], s["tbh"], s["ia"], s["ts"], s["sm_ref"], s["ndvi"],
            s["sf_col"], s["ndvi_max"], s["ndvi_min"], s["albedo"], s["b_param"],
            s["clay"], s["porosity"], s["h_static"], s["landcover"],
            s["config"], s["block_struct"],
            omega_fixed=None,
            tc=s["tc"], tsoil1=s["tsoil1"], tsoil2=s["tsoil2"],
        )
        assert result is not None
        # h/alpha（Step 1，低 τ 样本联合拟合）
        assert result.h_star == pytest.approx(s["h_true"], abs=0.02)
        assert result.alpha_star == pytest.approx(s["alpha_true"], abs=0.05)
        # omega（Step 2，块级优化）
        omega_valid = result.omega[np.isfinite(result.omega)]
        assert omega_valid.size >= 8
        assert float(np.median(omega_valid)) == pytest.approx(s["omega_true"], abs=0.03)
        # SM/VOD（Step 3，DDCA 逐日）
        sm_valid = result.sm[np.isfinite(result.sm)]
        tau_err = np.abs(result.vod - s["tau_true"])[np.isfinite(result.vod)]
        sm_err = np.abs(result.sm - s["sm_true"])[np.isfinite(result.sm)]
        assert sm_valid.size >= 8
        assert float(np.median(sm_err)) < 0.02
        assert float(np.median(tau_err)) < 0.10

    def test_dual_ignores_ts(self) -> None:
        """DUAL 下 Ts 全 NaN 不影响反演（温度真源为 GLDAS 三温度）。"""
        s = _make_roundtrip_scenario()
        result = execute_pixel_inversion(
            s["tbv"], s["tbh"], s["ia"], np.full(16, np.nan), s["sm_ref"],
            s["ndvi"], s["sf_col"], s["ndvi_max"], s["ndvi_min"], s["albedo"],
            s["b_param"], s["clay"], s["porosity"], s["h_static"], s["landcover"],
            s["config"], s["block_struct"],
            omega_fixed=None,
            tc=s["tc"], tsoil1=s["tsoil1"], tsoil2=s["tsoil2"],
        )
        assert result is not None
        assert np.any(np.isfinite(result.sm))

    def test_all_nan_temperatures_short_circuit(self) -> None:
        """tc 全 NaN → 有效性掩码为空 → 返回 None。"""
        s = _make_roundtrip_scenario()
        result = execute_pixel_inversion(
            s["tbv"], s["tbh"], s["ia"], s["ts"], s["sm_ref"], s["ndvi"],
            s["sf_col"], s["ndvi_max"], s["ndvi_min"], s["albedo"], s["b_param"],
            s["clay"], s["porosity"], s["h_static"], s["landcover"],
            s["config"], s["block_struct"],
            omega_fixed=None,
            tc=np.full(16, np.nan), tsoil1=s["tsoil1"], tsoil2=s["tsoil2"],
        )
        assert result is None


# ─── 4. 有效性掩码（DUAL 分支） ───────────────────────────────────────────────


def _mask_chunk_data(nt: int = 3, npix: int = 4):
    """3 天 × 4 像元合成 chunk：像元 1 的 tc 全缺、像元 2 的 tsoil2 全缺。"""
    data = {
        "tbv": np.full((nt, npix), 255.0),
        "tbh": np.full((nt, npix), 235.0),
        "ia": np.full((nt, npix), 40.0),
        "ts": np.full((nt, npix), 290.0),
        "sm_ref": np.full((nt, npix), 0.2),
        "ndvi": np.full((nt, npix), 0.4),
        "sf": np.full((nt, npix), 0.5),
        "tc": np.full((nt, npix), 295.0),
        "tsoil1": np.full((nt, npix), 292.0),
        "tsoil2": np.full((nt, npix), 288.0),
    }
    data["tc"][:, 1] = np.nan
    data["tsoil2"][:, 2] = np.nan
    return data


class TestChunkValidityMaskDual:
    def test_dual_requires_all_three_gldas_temperatures(self) -> None:
        data = _mask_chunk_data()
        anc = {
            "clay": np.full(4, 0.3),
            "porosity": np.full(4, 0.5),
        }
        lin_pix = np.array([0, 1, 2, 3], dtype=np.int64)
        config = OmegaSfConfig.from_params({"tb_source": "SMAP", "temp_scheme": "DUAL"})
        mask = _build_chunk_validity_mask(data, anc, lin_pix, config)
        # 像元 0/3 完整 → True；1 缺 tc、2 缺 tsoil2 → False
        np.testing.assert_array_equal(mask, [True, False, False, True])

    def test_orig_ts_still_uses_ts(self) -> None:
        """ORIG_TS：ts 全有限 → 温度项通过（与 GLDAS 键无关）。"""
        data = _mask_chunk_data()
        anc = {"clay": np.full(4, 0.3), "porosity": np.full(4, 0.5)}
        lin_pix = np.array([0, 1, 2, 3], dtype=np.int64)
        config = OmegaSfConfig.from_params({"tb_source": "SMAP"})
        mask = _build_chunk_validity_mask(data, anc, lin_pix, config)
        np.testing.assert_array_equal(mask, [True, True, True, True])

    def test_dual_missing_keys_treated_as_nan(self) -> None:
        """DUAL 但 chunk_data 无温度键（预读退化）→ 温度项全 False。"""
        data = _mask_chunk_data()
        for key in ("tc", "tsoil1", "tsoil2"):
            data.pop(key)
        anc = {"clay": np.full(4, 0.3), "porosity": np.full(4, 0.5)}
        config = OmegaSfConfig.from_params({"tb_source": "SMAP", "temp_scheme": "DUAL"})
        mask = _build_chunk_validity_mask(
            data, anc, np.array([0, 1, 2, 3], dtype=np.int64), config
        )
        # 掩码按 chunk 像元展开（形状随 chunk_data 而非 lin_pix）
        assert mask.shape == (4,)
        assert not mask.any()
