"""Unit tests for validation algorithm (algorithms/validation.py).

Covers:
  - compute_validation_metrics: r/p/rmse/bias/ubrmse (corresponds to Matlab metrics.m)
  - scatter_kde_density: per-point KDE density (corresponds to Matlab scatter_kde.m)

The provider package has a circular import (contracts <-> workflow); importing
``contracts`` first breaks the cycle (same pattern as test_omega_avg_algorithm.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# ── Provider path setup (must precede algorithm imports) ─────────────────────
_PROVIDER_ROOT = (
    Path(__file__).resolve().parents[2] / "algorithms" / "providers" / "Python"
)
if str(_PROVIDER_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROVIDER_ROOT))

import contracts  # noqa: E402, F401 — break circular import: contracts first
from algorithms.validation import (  # noqa: E402
    compute_validation_metrics,
    scatter_kde_density,
)


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_compute_validation_metrics_known_values() -> None:
    """已知 r/rmse/bias 的数组验证计算正确性。

    x = [1,2,3,4,5], y = x + 1 → diff 全为 -1:
      bias = -1, rmse = 1, ubrmse = sqrt(1 - 1) = 0, r = 1.0 (完美线性), p < 0.05。
    """
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = x + 1.0  # [2,3,4,5,6]

    metrics = compute_validation_metrics(x, y)

    assert metrics["bias"] == pytest.approx(-1.0, abs=1e-12)
    assert metrics["rmse"] == pytest.approx(1.0, abs=1e-12)
    # ubrmse = sqrt(max(0, rmse^2 - bias^2)) = sqrt(0) = 0
    assert metrics["ubrmse"] == pytest.approx(0.0, abs=1e-10)
    # 完美正相关
    assert metrics["r"] == pytest.approx(1.0, abs=1e-10)
    # 高度显著
    assert metrics["p"] < 0.05


def test_compute_validation_metrics_handles_nan() -> None:
    """含 NaN 的输入应被过滤，不传播到结果。

    x = [1, 2, nan, 4, 5], y = [2, 3, 4, nan, 6]
    有效配对: (1,2), (2,3), (5,6) → diff 全 -1 → bias=-1, rmse=1, ubrmse=0, r=1.0。
    """
    x = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
    y = np.array([2.0, 3.0, 4.0, np.nan, 6.0])

    metrics = compute_validation_metrics(x, y)

    # 所有指标应为有限值（NaN 已被过滤）
    for key in ("r", "p", "rmse", "bias", "ubrmse"):
        assert np.isfinite(metrics[key]), f"{key} 不应为 NaN: {metrics[key]}"

    assert metrics["bias"] == pytest.approx(-1.0, abs=1e-12)
    assert metrics["rmse"] == pytest.approx(1.0, abs=1e-12)
    assert metrics["ubrmse"] == pytest.approx(0.0, abs=1e-10)
    assert metrics["r"] == pytest.approx(1.0, abs=1e-10)


def test_compute_validation_metrics_shape_mismatch_raises() -> None:
    """形状不匹配应抛 ValueError。"""
    x = np.array([1.0, 2.0, 3.0])
    y = np.array([1.0, 2.0])
    with pytest.raises(ValueError, match="形状不匹配"):
        compute_validation_metrics(x, y)


def test_scatter_kde_density_returns_per_point_density() -> None:
    """随机 100 点: 密度数组长度 == 100, 全部非负有限。"""
    rng = np.random.default_rng(seed=42)
    x = rng.normal(0.0, 1.0, size=100)
    y = x * 2.0 + rng.normal(0.0, 0.5, size=100)

    density = scatter_kde_density(x, y)

    assert density.shape == (100,)
    assert np.all(np.isfinite(density)), "密度应全部有限"
    assert np.all(density >= 0.0), "密度应非负"


def test_scatter_kde_density_preserves_nan_positions() -> None:
    """含 NaN 的位置应在输出中保持 NaN, 其余位置为有限密度。

    使用非共线数据（避免 gaussian_kde 协方差奇异 → LinAlgError）。
    """
    x = np.array([1.0, 2.5, np.nan, 4.0, 5.0, 3.0])
    y = np.array([2.0, 3.0, 4.0, 5.5, 6.0, 3.8])

    density = scatter_kde_density(x, y)

    assert density.shape == (6,)
    assert np.isnan(density[2]), "NaN 输入位置应保持 NaN"
    finite_mask = np.array([True, True, False, True, True, True])
    assert np.all(np.isfinite(density[finite_mask])), "有效位置密度应有限"
    assert np.all(density[finite_mask] >= 0.0), "有效位置密度应非负"
