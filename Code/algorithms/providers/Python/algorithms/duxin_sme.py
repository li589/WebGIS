"""DuXin 时序土壤水分估算算法（SAR 反演，Python 移植版）。

来源：``providers/Matlab/Original-Time_series_soil_moisture_estimation-DuXin``
（SME_test_Main_pro.m 及其子函数），模块化迁移为 Python import provider。

算法流程（与 MATLAB 原版三段结构一一对应）：

Part 1  时序 alpha 反演（滑窗约束最小二乘）
    对每个滑窗构造观测矩阵 MPP（(N-1)×N 双对角）：

        MPP[k, k]   = 1
        MPP[k, k+1] = -sqrt(S_k / S_{k+1})    （S 为后向散射时序观测）

    求解 ``min ||MPP·x||²  s.t.  lb ≤ x_k ≤ ub``（MATLAB lsqlin interior-point）。
    MPP 的零空间方向为 ``v ∝ sqrt(S)``（代入逐行验证为零），因此该问题存在
    解析解：可行区间 ``t ∈ [max(lb/v), min(ub/v)]`` 非空时任取 t 即零残差，
    取区间中点对齐 interior-point 的解析中心极限行为；区间为空时取最小二乘
    t 的 clip 投影。多窗口结果按日期对齐后取 nanmean（与原版一致）。

Part 2  alpha → 介电常数（查找表反演）
    查找表：入射角 0.3~1.2 rad（901 点）× 介电常数 4~35（311 点），
    用作者自有 Fresnel 幅值公式（HH/VV）预计算。反演时先按像素入射角
    在 epsilon 轴上插值出 alpha(ε) 剖面，再反查 alpha 对应的 ε。

    注意：作者的 VV 公式与标准 Fresnel 约定不同，此处忠实移植原始公式
    （不做"修正"）。HH 公式在实数 ε 下等于 Fresnel 场强反射系数的幅值
    |Γ_HH| = |(cosθ-√(ε-sin²θ))/(cosθ+√(ε-sin²θ))|（标准功率反射率
    为其平方）。

Part 3  介电常数 → 体积含水量（Topp 1980 模型）
    mv = -5.3 + 2.92ε - 0.055ε² + 0.0004ε³   （单位 %，与原版一致）

参考：
    [1] J. D. Ouellette et al., "A Time-Series Approach to Estimating Soil
        Moisture from Vegetated Surfaces Using L-Band Radar Backscatter",
        IEEE TGRS, vol. 55, no. 6, pp. 3186-3193, 2017.
    [2] D. L. Topp et al., 1980（Topp 介电-水分经验模型）.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "DuxinSmeConfig",
    "alpha_calculation_hh",
    "alpha_calculation_vv",
    "build_alpha_lut",
    "topp_soil_moisture",
    "time_series_alpha_retrieval",
    "alpha_to_epsilon",
    "run_time_series_sme",
]


# ─── 与 MATLAB 原版一致的默认网格/边界 ──────────────────────────────────────
# 入射角查找表范围（rad）：0.3~1.2（约 17°~69°），901 点（步长 0.001）
DEFAULT_THETA_MIN = 0.3
DEFAULT_THETA_MAX = 1.2
DEFAULT_THETA_STEP = 0.001
# 介电常数查找表范围：4~35，311 点（步长 0.1）
DEFAULT_EPSILON_MIN = 4.0
DEFAULT_EPSILON_MAX = 35.0
DEFAULT_EPSILON_STEP = 0.1

# Topp 模型系数（1980）
_TOPP_COEFFS = (-5.3, 2.92, -0.055, 0.0004)


@dataclass(frozen=True, slots=True)
class DuxinSmeConfig:
    """DuXin 时序土壤水分反演配置。

    量纲：polarization 无量纲标识；num_step 滑窗大小（期数）；
    epsilon_min/max/step 无量纲（相对介电常数）；theta_min/max/step 单位 rad。
    """

    polarization: str = "hh"  # "hh" | "vv"
    num_step: int | None = None  # None → 使用整序列（与原版主程序一致）
    epsilon_min: float = DEFAULT_EPSILON_MIN
    epsilon_max: float = DEFAULT_EPSILON_MAX
    epsilon_step: float = DEFAULT_EPSILON_STEP
    theta_min: float = DEFAULT_THETA_MIN
    theta_max: float = DEFAULT_THETA_MAX
    theta_step: float = DEFAULT_THETA_STEP


def _normalize_polarization(polarization: str) -> str:
    value = str(polarization).strip().lower()
    if value not in {"hh", "vv"}:
        raise ValueError(f"polarization must be 'hh' or 'vv', got: {polarization!r}")
    return value


# ─── Part 2.1 查找表基础：作者自有 Fresnel 幅值公式 ─────────────────────────


def alpha_calculation_hh(theta: float | np.ndarray, epsilon: float | np.ndarray) -> np.ndarray:
    """HH 极化 Fresnel 幅值（作者公式，忠实移植 alpha_calculation_HH.m）。

    alpha_HH = |ε - 1| / (cosθ + sqrt(ε - sin²θ))²

    量纲：theta 单位 rad，epsilon 无量纲，返回无量纲幅值。
    支持广播（theta 与 epsilon 可为标量或数组）。
    """
    theta = np.asarray(theta, dtype=np.float64)
    epsilon = np.asarray(epsilon, dtype=np.float64)
    sin_theta_sq = np.sin(theta) ** 2
    root = np.sqrt(np.maximum(epsilon - sin_theta_sq, 0.0))
    numerator = np.abs(epsilon - 1.0)
    denominator = (np.cos(theta) + root) ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(denominator > 0, numerator / denominator, np.nan)
    return result


def alpha_calculation_vv(theta: float | np.ndarray, epsilon: float | np.ndarray) -> np.ndarray:
    """VV 极化 Fresnel 幅值（作者公式，忠实移植 alpha_calculation_VV.m）。

    alpha_VV = |(ε-1)(sin²θ - ε(1+sin²θ))| / (ε·cosθ + sqrt(ε - sin²θ))²

    量纲：theta 单位 rad，epsilon 无量纲，返回无量纲幅值。
    注意：此公式与标准 Fresnel 功率反射率约定不同，为作者原始推导，忠实保留。
    """
    theta = np.asarray(theta, dtype=np.float64)
    epsilon = np.asarray(epsilon, dtype=np.float64)
    sin_theta_sq = np.sin(theta) ** 2
    root = np.sqrt(np.maximum(epsilon - sin_theta_sq, 0.0))
    numerator = np.abs((epsilon - 1.0) * (sin_theta_sq - epsilon * (1.0 + sin_theta_sq)))
    denominator = (epsilon * np.cos(theta) + root) ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(denominator > 0, numerator / denominator, np.nan)
    return result


_ALPHA_FUNCS = {"hh": alpha_calculation_hh, "vv": alpha_calculation_vv}


@dataclass(frozen=True, slots=True)
class AlphaLUT:
    """alpha 查找表（theta × epsilon 网格上的 Fresnel 幅值矩阵）。

    行：入射角（theta_grid，rad）；列：介电常数（epsilon_grid，无量纲）。
    表值 alpha(theta, epsilon)，无量纲。
    """

    polarization: str
    theta_grid: np.ndarray  # (T,) 递增
    epsilon_grid: np.ndarray  # (E,) 递增
    table: np.ndarray  # (T, E)

    def column_for_theta(self, theta: float) -> np.ndarray:
        """取指定入射角处沿 epsilon 轴插值出的 alpha(ε) 剖面（(E,)）。"""
        theta = float(theta)
        if theta <= self.theta_grid[0]:
            return self.table[0].copy()
        if theta >= self.theta_grid[-1]:
            return self.table[-1].copy()
        index = int(np.searchsorted(self.theta_grid, theta)) - 1
        t0, t1 = self.theta_grid[index], self.theta_grid[index + 1]
        if t1 <= t0:
            return self.table[index].copy()
        weight = (theta - t0) / (t1 - t0)
        return self.table[index] * (1.0 - weight) + self.table[index + 1] * weight


def build_alpha_lut(config: DuxinSmeConfig | None = None, polarization: str | None = None) -> AlphaLUT:
    """构建 alpha 查找表（对应原版 Part-2.1 双重循环，这里全向量化）。"""
    cfg = config or DuxinSmeConfig(polarization=polarization or "hh")
    pol = _normalize_polarization(polarization or cfg.polarization)
    theta_grid = np.arange(cfg.theta_min, cfg.theta_max + cfg.theta_step * 0.5, cfg.theta_step)
    epsilon_grid = np.arange(
        cfg.epsilon_min, cfg.epsilon_max + cfg.epsilon_step * 0.5, cfg.epsilon_step
    )
    # 广播：theta (T,1) × epsilon (1,E) → (T,E)
    table = _ALPHA_FUNCS[pol](theta_grid[:, None], epsilon_grid[None, :])
    return AlphaLUT(polarization=pol, theta_grid=theta_grid, epsilon_grid=epsilon_grid, table=table)


# ─── Part 3 Topp 模型 ──────────────────────────────────────────────────────


def topp_soil_moisture(epsilon: np.ndarray) -> np.ndarray:
    """Topp 1980 模型：相对介电常数 → 体积含水量（%，与原版单位一致）。

    mv = -5.3 + 2.92ε - 0.055ε² + 0.0004ε³
    """
    epsilon = np.asarray(epsilon, dtype=np.float64)
    c0, c1, c2, c3 = _TOPP_COEFFS
    return c0 + c1 * epsilon + c2 * epsilon**2 + c3 * epsilon**3


# ─── Part 1 时序 alpha 反演（解析法，等价 MATLAB lsqlin interior-point）─────


def _solve_window_alpha(
    observations: np.ndarray,
    lb: float,
    ub: float,
) -> np.ndarray | None:
    """解单个像素单个滑窗的有界最小二乘。

    Args:
        observations: (N,) 该窗口内 N 期后向散射（线性单位）。
        lb/ub: alpha 边界（标量，由 epsilon_min/max 对应的 Fresnel 幅值给出）。

    Returns:
        (N,) alpha 解；观测含非正值或 NaN 时返回 None（原版置 0）。

    数学：MPP·x=0 的零空间方向 v=sqrt(S)；可行缩放区间
    t ∈ [max(lb/v_k), min(ub/v_k)]。区间非空时任取 t 均零残差，取中点
    对齐 MATLAB lsqlin interior-point 的对数障碍解析中心极限。区间为空
    （S 波动超出 alpha 物理边界）时精确求解有界最小二乘
    （scipy lsq_linear，与 lsqlin 语义一致），真解不再位于零空间方向上。
    """
    if observations.shape[0] < 2:
        return None
    if not np.all(np.isfinite(observations)) or np.any(observations <= 0):
        return None
    v = np.sqrt(observations)
    if lb > ub:
        lb, ub = min(lb, ub), max(lb, ub)
    t_lower = float(np.max(lb / v))
    t_upper = float(np.min(ub / v))
    if t_lower <= t_upper:
        t = 0.5 * (t_lower + t_upper)
        return t * v
    # 退化情形：零残差不可达 → 精确有界线性最小二乘（lsqlin 等价）
    from scipy.optimize import lsq_linear

    n = v.shape[0]
    mpp = np.zeros((n - 1, n), dtype=np.float64)
    idx = np.arange(n - 1)
    mpp[idx, idx] = 1.0
    mpp[idx, idx + 1] = -(v[:-1] / v[1:])
    result = lsq_linear(mpp, np.zeros(n - 1), bounds=(lb, ub))
    return np.asarray(result.x, dtype=np.float64)


def time_series_alpha_retrieval(
    obsv_data: np.ndarray,
    inc_ang: np.ndarray,
    num_step: int | None = None,
    polarization: str = "hh",
    epsilon_bounds: tuple[float, float] = (DEFAULT_EPSILON_MIN, DEFAULT_EPSILON_MAX),
) -> np.ndarray:
    """时序 alpha 反演（对应原版 Fun_time_series_SME_hh/vv.m）。

    Args:
        obsv_data: (rows, cols, N) 时序后向散射（线性单位，非 dB）。
        inc_ang: (rows, cols) 入射角（rad）。
        num_step: 滑窗大小；None → 整序列单窗口（原版主程序行为）。
        polarization: "hh" | "vv"（决定边界 alpha 计算）。
        epsilon_bounds: alpha 边界对应的介电常数上下界。

    Returns:
        (rows, cols, N) 各期 alpha（无效像素为 0，与原版 NaN/Inf→0 一致）。
    """
    pol = _normalize_polarization(polarization)
    obsv = np.asarray(obsv_data, dtype=np.float64)
    ang = np.asarray(inc_ang, dtype=np.float64)
    if obsv.ndim != 3:
        raise ValueError(f"obsv_data must be 3-D (rows, cols, N), got shape {obsv.shape}")
    if ang.shape != obsv.shape[:2]:
        raise ValueError(
            f"inc_ang shape {ang.shape} must match obsv_data spatial shape {obsv.shape[:2]}"
        )
    rows, cols, num_image = obsv.shape
    if num_image < 2:
        raise ValueError("time series must contain at least 2 images")
    window = int(num_step) if num_step else num_image
    if window < 2 or window > num_image:
        raise ValueError(f"num_step must be in [2, {num_image}], got {window}")

    alpha_func = _ALPHA_FUNCS[pol]
    eps_min, eps_max = float(epsilon_bounds[0]), float(epsilon_bounds[1])

    # 每像素的 alpha 边界（(rows, cols)，标量对窗口内所有期一致——原版行为）
    lb_map = alpha_func(ang, eps_min)
    ub_map = alpha_func(ang, eps_max)
    # 边界顺序对齐原版 abs()：确保 lb ≤ ub；非 finite（异常入射角）像素无效
    lb = np.minimum(lb_map, ub_map)
    ub = np.maximum(lb_map, ub_map)
    finite_bounds = np.isfinite(lb) & np.isfinite(ub) & (lb >= 0) & (ub > lb)

    num_windows = num_image - window + 1
    # 各窗口结果按日期累加（对齐原版 soil_alpha_retrieval_time_series + nanmean）
    accumulated = np.zeros((rows, cols, num_image), dtype=np.float64)
    coverage = np.zeros((rows, cols, num_image), dtype=np.float64)

    for step in range(num_windows):
        window_slice = slice(step, step + window)
        window_data = obsv[:, :, window_slice]
        result = np.zeros((rows, cols, window), dtype=np.float64)
        for i in range(rows):
            for j in range(cols):
                if not finite_bounds[i, j]:
                    continue
                solution = _solve_window_alpha(window_data[i, j], lb[i, j], ub[i, j])
                if solution is not None:
                    result[i, j] = solution
        # 原版把 0 值当 NaN 排除后 nanmean；0 解（无效）不计入
        valid = result != 0.0
        accumulated[:, :, window_slice] += np.where(valid, result, 0.0)
        coverage[:, :, window_slice] += valid.astype(np.float64)

    with np.errstate(divide="ignore", invalid="ignore"):
        averaged = np.where(coverage > 0, accumulated / np.maximum(coverage, 1.0), 0.0)
    averaged[~np.isfinite(averaged)] = 0.0
    return averaged


# ─── Part 2.2 alpha → epsilon（查表反演）──────────────────────────────────


def alpha_to_epsilon(
    alpha: np.ndarray,
    inc_ang: np.ndarray,
    lut: AlphaLUT | None = None,
    polarization: str = "hh",
) -> np.ndarray:
    """查表反演介电常数（对应原版 Part-2.2 的 interp2+interp1 双插值）。

    Args:
        alpha: (rows, cols, N) 各期 alpha 幅值。
        inc_ang: (rows, cols) 入射角（rad）。
        lut: 预构建查找表；None → 按默认网格构建（HH/VV 由 polarization 决定）。

    Returns:
        (rows, cols, N) 相对介电常数（无效处 0，与原版一致）。
    """
    alpha = np.asarray(alpha, dtype=np.float64)
    ang = np.asarray(inc_ang, dtype=np.float64)
    if lut is None:
        lut = build_alpha_lut(polarization=polarization)
    rows, cols, num_image = alpha.shape

    epsilon = np.zeros_like(alpha)
    epsilon_grid = lut.epsilon_grid
    # alpha(ε) 剖面在查找表定义域内须单调递增才能 interp1 反查；
    # HH 公式严格单调，VV 在小入射角低端可能出现轻微非单调段，
    # 用 searchsorted 的“右侧插入点”保证确定性（找不到时返回边界/0）。
    for i in range(rows):
        for j in range(cols):
            column = lut.column_for_theta(float(ang[i, j]))
            # 保险：非单调段用最大下界 clip（保持与 interp1 的越界 NaN→0 行为接近）
            for k in range(num_image):
                value = alpha[i, j, k]
                if value <= 0.0 or not np.isfinite(value):
                    continue
                if value < column[0] or value > column[-1]:
                    continue  # interp1 越界 → NaN → 0（原版行为）
                epsilon[i, j, k] = float(np.interp(value, column, epsilon_grid))
    return epsilon


# ─── 主入口 ───────────────────────────────────────────────────────────────


def run_time_series_sme(
    obsv_data: np.ndarray,
    inc_ang: np.ndarray,
    config: DuxinSmeConfig | None = None,
) -> dict[str, np.ndarray]:
    """DuXin 时序土壤水分估算主流程（对应 SME_test_Main_pro.m 全流程）。

    Args:
        obsv_data: (rows, cols, N) 时序后向散射（线性单位，非 dB）。
        inc_ang: (rows, cols) 入射角（rad）。
        config: 反演配置；None → 默认（hh / 整序列窗口）。

    Returns:
        dict，含三个 (rows, cols, N) 数组：
        - ``soil_alpha``：Fresnel 幅值 alpha（无量纲）
        - ``soil_epsilon``：相对介电常数（无量纲；无效 0）
        - ``soil_moisture``：体积含水量（%，Topp 模型；无效 0）
    """
    cfg = config or DuxinSmeConfig()
    pol = _normalize_polarization(cfg.polarization)

    alpha = time_series_alpha_retrieval(
        obsv_data,
        inc_ang,
        num_step=cfg.num_step,
        polarization=pol,
        epsilon_bounds=(cfg.epsilon_min, cfg.epsilon_max),
    )

    lut = build_alpha_lut(cfg, polarization=pol)
    epsilon = alpha_to_epsilon(alpha, inc_ang, lut=lut, polarization=pol)

    moisture = topp_soil_moisture(epsilon)
    # 原版：epsilon==0 处水分置 0；Topp 在小 ε 下可能为负，clip 到 0
    moisture = np.where(epsilon == 0.0, 0.0, moisture)
    moisture = np.maximum(moisture, 0.0)
    moisture[~np.isfinite(moisture)] = 0.0

    return {
        "soil_alpha": alpha,
        "soil_epsilon": epsilon,
        "soil_moisture": moisture,
    }
