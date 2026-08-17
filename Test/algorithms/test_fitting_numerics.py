"""曲线拟合数值防护测试（数值专项 W2）。

1. polyfit 阶数上限 1..6：越界显式 ValueError（高阶 Vandermonde 病态）。
2. 指数拟合初值量纲感知：亮温量级（~300）数据收敛到真实参数。
3. 拟合曲线溢出（inf）截为 NaN——NaN 尾部触发外推溢出是真实路径：
   有效样本只占前段、全时间轴求值时末端 exp(b·t) 上溢。
"""

from __future__ import annotations

import numpy as np
import pytest

import contracts.job  # noqa: F401  (先行导入打破 modules 循环导入)
from modules.fitting import _fit_exponential, _fit_polynomial


def test_polynomial_degree_bounds() -> None:
    values = np.arange(10, dtype=np.float64)
    for bad_degree in (0, -1, 7, 50):
        with pytest.raises(ValueError, match="degree"):
            _fit_polynomial(values, bad_degree)


def test_polynomial_valid_degree_passes() -> None:
    values = np.arange(10, dtype=np.float64)
    for ok_degree in (1, 3, 6):
        result = _fit_polynomial(values, ok_degree)
        assert result["method"] == "polynomial"
        assert np.isfinite(np.asarray(result["fitted_curve"])).all()


def test_exponential_large_magnitude_converges() -> None:
    """亮温量级 y=300·exp(-0.02t)：初值量纲感知后应收敛到真实参数。"""
    t = np.arange(50, dtype=np.float64)
    values = 300.0 * np.exp(-0.02 * t)
    result = _fit_exponential(values)
    a = result["params"]["a"]
    b = result["params"]["b"]
    assert a == pytest.approx(300.0, rel=0.05)
    assert b == pytest.approx(-0.02, rel=0.05)


def test_exponential_nan_tail_overflow_truncated_to_nan() -> None:
    """有效样本仅前段 + 尾部 NaN：全轴求值末端 exp(b·t) 上溢 → NaN 而非 inf。"""
    n = 1500
    values = np.full(n, np.nan)
    head = 5
    values[:head] = np.exp(0.5 * np.arange(head, dtype=np.float64))
    result = _fit_exponential(values)
    fitted = np.asarray(result["fitted_curve"], dtype=np.float64)
    assert not np.isinf(fitted).any(), "拟合曲线含 inf，将污染 MAT/CSV 落盘"
    # 尾部（有效样本外）要么 NaN 要么有限，绝不允许 inf
    assert np.isnan(fitted).any() or np.isfinite(fitted).all()
    # 头部（有效样本内）必须有限且贴合数据
    assert np.isfinite(fitted[:head]).all()
    np.testing.assert_allclose(fitted[:head], values[:head], rtol=1e-6)
