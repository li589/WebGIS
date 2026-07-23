"""时间序列分析模块 — 趋势、异常、相关性"""

from __future__ import annotations

import os
import sys

# 支持独立运行: 将上级目录(Python providers 根目录)加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings

import numpy as np
from scipy import stats


class TrendAnalysis:
    """趋势分析"""

    def linear_trend(
        self,
        values: np.ndarray,
        time: np.ndarray | None = None,
    ) -> dict[str, float]:
        """线性回归趋势分析

        - 返回 {slope, intercept, r_value, p_value, std_err}
        - 使用 scipy.stats.linregress
        - 自动处理 NaN 值
        """
        values = np.asarray(values, dtype=np.float64)
        if time is None:
            time = np.arange(values.size, dtype=np.float64)
        else:
            time = np.asarray(time, dtype=np.float64)

        if values.shape != time.shape:
            raise ValueError("values 与 time 形状必须一致")

        # 仅保留双方均为有限值的样本
        valid_mask = np.isfinite(values) & np.isfinite(time)
        if valid_mask.sum() < 2:
            return {
                "slope": float("nan"),
                "intercept": float("nan"),
                "r_value": float("nan"),
                "p_value": float("nan"),
                "std_err": float("nan"),
            }

        result = stats.linregress(time[valid_mask], values[valid_mask])
        return {
            "slope": float(result.slope),
            "intercept": float(result.intercept),
            "r_value": float(result.rvalue),
            "p_value": float(result.pvalue),
            "std_err": float(result.stderr),
        }

    def mann_kendall(
        self,
        values: np.ndarray,
        significance: float = 0.05,
    ) -> dict[str, float | bool | None]:
        """Mann-Kendall 趋势检验

        - 非参数趋势检验
        - 返回 {trend, p_value, z_score, tau}
        - trend: True=上升趋势, False=下降趋势, None=无显著趋势
        """
        values = np.asarray(values, dtype=np.float64)
        x = values[np.isfinite(values)]
        n = x.size

        if n < 3:
            return {
                "trend": None,
                "p_value": float("nan"),
                "z_score": float("nan"),
                "tau": float("nan"),
            }

        # 计算 S 统计量
        s = 0
        for i in range(n - 1):
            s += int(np.sum(np.sign(x[i + 1 :] - x[i])))

        # 方差修正 (考虑并列值 ties)
        unique, counts = np.unique(x, return_counts=True)
        var_s = (n * (n - 1) * (2 * n + 5)) / 18.0
        tie_term = float(np.sum(counts * (counts - 1) * (2 * counts + 5)))
        var_s -= tie_term / 18.0

        # 计算 z 分数与双侧 p 值
        if var_s <= 0:
            z = 0.0
            p_value = 1.0
        else:
            if s > 0:
                z = (s - 1) / np.sqrt(var_s)
            elif s < 0:
                z = (s + 1) / np.sqrt(var_s)
            else:
                z = 0.0
            p_value = 2.0 * (1.0 - stats.norm.cdf(abs(z)))

        # Kendall tau
        tau = s / (n * (n - 1) / 2.0)

        # 判断趋势方向 (在显著性水平下)
        if p_value < significance:
            trend: bool | None = bool(z > 0)
        else:
            trend = None

        return {
            "trend": trend,
            "p_value": float(p_value),
            "z_score": float(z),
            "tau": float(tau),
        }

    def anomaly(
        self,
        values: np.ndarray,
        climatology: np.ndarray | None = None,
        method: str = "standardized",
    ) -> np.ndarray:
        """计算异常值

        - method="standardized": (x - mean) / std
        - method="difference": x - mean
        - method="percent": (x - mean) / mean * 100
        - 如果未提供 climatology，使用均值作为气候态
        """
        values = np.asarray(values, dtype=np.float64)
        valid_mask = np.isfinite(values)

        # 确定气候态 (均值参考)
        if climatology is None:
            mean_val = (
                float(np.mean(values[valid_mask]))
                if valid_mask.sum() > 0
                else float("nan")
            )
            mean_array = np.full(values.shape, mean_val, dtype=np.float64)
        else:
            climatology = np.asarray(climatology, dtype=np.float64)
            if climatology.shape != values.shape:
                raise ValueError("climatology 形状必须与 values 一致")
            mean_array = climatology

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            if method == "standardized":
                std_val = (
                    float(np.std(values[valid_mask], ddof=0))
                    if valid_mask.sum() > 0
                    else float("nan")
                )
                if not np.isfinite(std_val) or std_val == 0:
                    return np.full(values.shape, np.nan, dtype=np.float64)
                return (values - mean_array) / std_val
            elif method == "difference":
                return values - mean_array
            elif method == "percent":
                # 避免除零: 将 0 均值替换为 NaN
                safe_mean = np.where(mean_array == 0, np.nan, mean_array)
                return (values - mean_array) / safe_mean * 100.0
            else:
                raise ValueError(
                    f"不支持的 method: {method}, 可选 standardized/difference/percent"
                )


class CorrelationAnalysis:
    """相关性分析"""

    def pixelwise_correlation(
        self,
        data1: np.ndarray,
        data2: np.ndarray,
        method: str = "pearson",
    ) -> np.ndarray:
        """逐像素时间序列相关性

        - 输入: 两个 3D 数组 (time, lat, lon)
        - 输出: 2D 相关性数组 (lat, lon)
        - 自动处理 NaN
        """
        data1 = np.asarray(data1, dtype=np.float64)
        data2 = np.asarray(data2, dtype=np.float64)
        if data1.ndim != 3 or data2.ndim != 3:
            raise ValueError("输入必须是 3D 数组 (time, lat, lon)")
        if data1.shape != data2.shape:
            raise ValueError("两个输入数组形状必须一致")

        n_time, n_lat, n_lon = data1.shape
        n_pixels = n_lat * n_lon
        d1 = data1.reshape(n_time, n_pixels)
        d2 = data2.reshape(n_time, n_pixels)
        result = np.full(n_pixels, np.nan, dtype=np.float64)

        for i in range(n_pixels):
            x = d1[:, i]
            y = d2[:, i]
            valid = np.isfinite(x) & np.isfinite(y)
            # 至少需要 3 个有效样本才能计算相关
            if valid.sum() < 3:
                continue
            try:
                if method == "pearson":
                    r, _ = stats.pearsonr(x[valid], y[valid])
                elif method == "spearman":
                    r, _ = stats.spearmanr(x[valid], y[valid])
                else:
                    raise ValueError(
                        f"不支持的 method: {method}, 可选 pearson/spearman"
                    )
                result[i] = float(r)
            except Exception:
                # 常数序列等情况会导致计算失败, 置为 NaN
                result[i] = np.nan

        return result.reshape(n_lat, n_lon)

    def timeseries_correlation(
        self,
        ts1: np.ndarray,
        ts2: np.ndarray,
        method: str = "pearson",
        lag: int = 0,
    ) -> dict[str, float]:
        """时间序列相关性 (含滞后)

        - 支持 Pearson 和 Spearman 相关
        - 支持时间滞后
        - 返回 {r, p_value, n}
        """
        ts1 = np.asarray(ts1, dtype=np.float64)
        ts2 = np.asarray(ts2, dtype=np.float64)
        if ts1.ndim != 1 or ts2.ndim != 1:
            raise ValueError("输入必须为一维时间序列")

        # 应用滞后: lag>0 表示 ts1 滞后于 ts2 (ts1[lag:] 对齐 ts2[:-lag])
        if lag > 0:
            x = ts1[lag:]
            y = ts2[: ts2.size - lag]
        elif lag < 0:
            lag_abs = abs(lag)
            x = ts1[: ts1.size - lag_abs]
            y = ts2[lag_abs:]
        else:
            x = ts1
            y = ts2

        # 对齐长度
        n_min = min(x.size, y.size)
        x = x[:n_min]
        y = y[:n_min]

        valid = np.isfinite(x) & np.isfinite(y)
        n = int(valid.sum())
        if n < 3:
            return {"r": float("nan"), "p_value": float("nan"), "n": float(n)}

        try:
            if method == "pearson":
                r, p = stats.pearsonr(x[valid], y[valid])
            elif method == "spearman":
                r, p = stats.spearmanr(x[valid], y[valid])
            else:
                raise ValueError(f"不支持的 method: {method}, 可选 pearson/spearman")
        except Exception:
            return {"r": float("nan"), "p_value": float("nan"), "n": float(n)}

        return {"r": float(r), "p_value": float(p), "n": float(n)}
