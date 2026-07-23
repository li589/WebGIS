"""验证指标与 KDE 密度估计算法。

对应 Matlab Function/metrics.m 与 Function/scatter_kde.m：
  - ``compute_validation_metrics``: r / p / rmse / bias / ubrmse
  - ``scatter_kde_density``: 逐点核密度估计（用于散点着色）

量纲约定:
  - r / p: 无量纲
  - rmse / bias / ubrmse: 与输入同量纲
  - KDE 密度: 无量纲概率密度
"""

from __future__ import annotations

import numpy as np
from scipy.stats import gaussian_kde, pearsonr

# 显著性水平（对应 metrics.m 的 "Alpha",0.05）
_METRICS_ALPHA = 0.05
# pearsonr 所需的最小有效样本数
_MIN_SAMPLES_FOR_PEARSON = 2
# gaussian_kde 默认带宽方法（与 Matlab ksdensity 默认行为接近）
_KDE_DEFAULT_BW_METHOD = "scott"
# 协方差奇异（数据共线/近共线）时的抖动正则化相对尺度
_KDE_FALLBACK_JITTER_REL = 1e-6


def compute_validation_metrics(
    predicted: np.ndarray,
    observed: np.ndarray,
) -> dict[str, float]:
    """计算 predicted vs observed 的验证指标（对应 metrics.m）。

    量纲: 输入 predicted/observed 为同量纲数组（任意物理量）。
    输出 r/p 无量纲；rmse/bias/ubrmse 与输入同量纲。

    指标定义（与 metrics.m 一致）:
      - r:      Pearson 相关系数（scipy.stats.pearsonr 替代 corrcoef）
      - p:      双侧显著性 p 值
      - rmse:   sqrt(mean((x - y)^2))
      - bias:   mean(x - y)
      - ubrmse: sqrt(max(0, rmse^2 - bias^2))  # clamp 防浮点负值

    NaN 处理: 仅保留两边均有限的配对；有效样本 < 2 或零方差时 r/p 返回 nan。
    """
    x = np.asarray(predicted, dtype=float).ravel()
    y = np.asarray(observed, dtype=float).ravel()
    if x.shape != y.shape:
        raise ValueError(f"predicted/observed 形状不匹配: {x.shape} vs {y.shape}")

    mask = np.isfinite(x) & np.isfinite(y)
    x_finite = x[mask]
    y_finite = y[mask]

    nan_result: dict[str, float] = {
        "r": float("nan"),
        "p": float("nan"),
        "rmse": float("nan"),
        "bias": float("nan"),
        "ubrmse": float("nan"),
    }
    if x_finite.size == 0:
        return nan_result

    diff = x_finite - y_finite
    rmse = float(np.sqrt(np.mean(diff * diff)))
    bias = float(np.mean(diff))
    # ubrmse = sqrt(rmse^2 - bias^2)；浮点误差可能令 rmse^2 - bias^2 微负，clamp 到 0
    ubrmse = float(np.sqrt(max(0.0, rmse * rmse - bias * bias)))

    std_x = float(np.std(x_finite))
    std_y = float(np.std(y_finite))
    if x_finite.size >= _MIN_SAMPLES_FOR_PEARSON and std_x > 0.0 and std_y > 0.0:
        result = pearsonr(x_finite, y_finite)
        r_val = float(result[0])
        p_val = float(result[1])
    else:
        r_val = float("nan")
        p_val = float("nan")

    return {
        "r": r_val,
        "p": p_val,
        "rmse": rmse,
        "bias": bias,
        "ubrmse": ubrmse,
    }


def scatter_kde_density(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """逐点核密度估计（对应 scatter_kde.m 的 ksdensity）。

    量纲: 输入 x/y 为同长度 1D 数组（任意物理量）。输出为无量纲概率密度，
    长度等于输入长度，用于前端散点着色。

    实现: scipy.stats.gaussian_kde 替代 Matlab ksdensity；
    输入展平为 (2, N)，对每个样本点求密度。非有限值位置返回 nan。
    """
    x_arr = np.asarray(x, dtype=float).ravel()
    y_arr = np.asarray(y, dtype=float).ravel()
    if x_arr.shape != y_arr.shape:
        raise ValueError(f"x/y 形状不匹配: {x_arr.shape} vs {y_arr.shape}")

    mask = np.isfinite(x_arr) & np.isfinite(y_arr)
    density = np.full(x_arr.shape, np.nan, dtype=float)
    if mask.sum() == 0:
        return density

    samples = np.vstack([x_arr[mask], y_arr[mask]])
    try:
        kernel = gaussian_kde(samples, bw_method=_KDE_DEFAULT_BW_METHOD)
        density_finite = kernel(samples)
    except np.linalg.LinAlgError:
        # 协方差奇异（数据共线/近共线，如 predicted≈observed 几乎无散布）：
        # 加微小抖动正则化后重试，保证密度估计可计算。
        scale = float(np.std(samples)) * _KDE_FALLBACK_JITTER_REL
        if scale == 0.0:
            scale = _KDE_FALLBACK_JITTER_REL
        rng = np.random.default_rng(0)
        jittered = samples + rng.normal(0.0, scale, size=samples.shape)
        kernel = gaussian_kde(jittered, bw_method=_KDE_DEFAULT_BW_METHOD)
        density_finite = kernel(samples)
    density[mask] = density_finite
    return density
