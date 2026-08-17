"""反演优化初值/边界防护测试（数值专项 C1+W3）。

锁定两条硬语义：

1. ``ddca_retrieve_pixel``：porosity∈(0.02, 0.2) 的低孔隙度像元
   （旧固定初值 x0=[0.2, 0.5] 会越 bounds）不得抛
   ``ValueError: x0 is infeasible``，须返回有限值或 NaN；
   porosity ≤ 0.02 或非有限时返回 (NaN, NaN)。
2. ``ddca_retrieve_grid``：含单个越界 porosity 像元的整批处理不崩，
   坏像元为 NaN、正常像元结果不受牵连。

背景：omega.py:1227-1247 已修同款（低孔隙度 clamp），此处补齐
inversion.py 的两处遗漏。
"""

from __future__ import annotations

import math

import numpy as np


def _pixel_inputs(porosity: float) -> dict[str, float]:
    return {
        "tbv": 250.0,
        "tbh": 240.0,
        "ts": 300.0,
        "tau_ini": 0.5,
        "h_value": 0.1,
        "clay_fraction": 0.3,
        "albedo": 0.05,
        "porosity": porosity,
        "freq_ghz": 1.4,
        "theta_deg": 40.0,
    }


def test_ddca_pixel_low_porosity_does_not_raise() -> None:
    """porosity=0.1 < 旧固定初值 0.2：不抛异常，返回有限值或 NaN。"""
    from algorithms.inversion import ddca_retrieve_pixel

    sm, vod = ddca_retrieve_pixel(**_pixel_inputs(porosity=0.1))
    assert math.isfinite(sm) or math.isnan(sm)
    assert math.isfinite(vod) or math.isnan(vod)
    if math.isfinite(sm):
        # 有限解必须落在物理 bounds 内
        assert 0.02 <= sm <= 0.1
        assert 0.0 <= vod <= 5.0


def test_ddca_pixel_porosity_at_bound_returns_finite() -> None:
    """porosity=0.05（仍 <0.2）也应正常返回。"""
    from algorithms.inversion import ddca_retrieve_pixel

    sm, vod = ddca_retrieve_pixel(**_pixel_inputs(porosity=0.05))
    assert math.isfinite(sm) or math.isnan(sm)


def test_ddca_pixel_invalid_porosity_returns_nan() -> None:
    """porosity ≤ 0.02 / inf / NaN：统一 NaN 出口，不进入优化器。"""
    from algorithms.inversion import ddca_retrieve_pixel

    for bad in (0.01, 0.0, -0.5, float("inf"), float("nan")):
        sm, vod = ddca_retrieve_pixel(**_pixel_inputs(porosity=bad))
        assert math.isnan(sm), f"porosity={bad!r} 期望 sm=NaN，实得 {sm!r}"
        assert math.isnan(vod), f"porosity={bad!r} 期望 vod=NaN，实得 {vod!r}"


def test_ddca_grid_single_bad_pixel_does_not_crash_batch() -> None:
    """单个越界 porosity 像元不得令整批崩溃；坏像元 NaN、好像元有限。"""
    from algorithms.inversion import ddca_retrieve_grid

    grid = {
        "tbv": np.array([[250.0, 250.0]], dtype=np.float64),
        "tbh": np.array([[240.0, 240.0]], dtype=np.float64),
        "ts": np.array([[300.0, 300.0]], dtype=np.float64),
        "tau_ini": np.array([[0.5, 0.5]], dtype=np.float64),
        "h_value": np.array([[0.1, 0.1]], dtype=np.float64),
        "clay_fraction": np.array([[0.3, 0.3]], dtype=np.float64),
        "albedo": np.array([[0.05, 0.05]], dtype=np.float64),
        "porosity": np.array([[0.45, 0.01]], dtype=np.float64),
        "freq_ghz": 1.4,
        "theta_deg": np.array([[40.0, 40.0]], dtype=np.float64),
    }
    sm, vod = ddca_retrieve_grid(**grid)
    assert np.isnan(sm[0, 1]), f"坏像元 sm 应为 NaN，实得 {sm[0, 1]!r}"
    assert np.isnan(vod[0, 1])
    assert np.isfinite(sm[0, 0]), f"好像元 sm 应有限，实得 {sm[0, 0]!r}"
    assert np.isfinite(vod[0, 0])


def test_ddca_grid_all_invalid_porosity_returns_all_nan() -> None:
    """全部像元 porosity 无效 → 整批 NaN，不抛异常。"""
    from algorithms.inversion import ddca_retrieve_grid

    grid = {
        "tbv": np.full((2, 2), 250.0),
        "tbh": np.full((2, 2), 240.0),
        "ts": np.full((2, 2), 300.0),
        "tau_ini": np.full((2, 2), 0.5),
        "h_value": np.full((2, 2), 0.1),
        "clay_fraction": np.full((2, 2), 0.3),
        "albedo": np.full((2, 2), 0.05),
        "porosity": np.full((2, 2), 0.005),
        "freq_ghz": 1.4,
        "theta_deg": np.full((2, 2), 40.0),
    }
    sm, vod = ddca_retrieve_grid(**grid)
    assert np.isnan(sm).all()
    assert np.isnan(vod).all()
