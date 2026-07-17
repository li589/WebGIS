from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from algorithms.physics import (
    FresnelContext,
    MironovContext,
    build_fresnel_context,
    build_mironov_context,
    fresnel_reflectance,
    fresnel_reflectance_from_context,
    mironov_dielectric,
    mironov_dielectric_from_context,
)

# Choudhury polarization mixing factor Q
_POLARIZATION_MIXING_Q = 0.1771

# tau 正则化系数（L2 惩罚强度），用于约束 tau_value 接近 tau_ini
_TAU_REGULARIZATION_LAMBDA = 20.0


def _is_nan(value: float) -> bool:
    return math.isnan(value)


@dataclass(frozen=True, slots=True)
class TbModelContext:
    dielectric: MironovContext
    fresnel: FresnelContext


def _rough_reflectance_impl(
    theta_cos_sq: float,
    h_value: float,
    rh: float,
    rv: float,
) -> tuple[float, float]:
    """粗糙表面反射率公共实现。

    量纲: 输入/输出均为无量纲反射率 (0-1)。
    theta_cos_sq 为 cos(theta)^2，h_value 为粗糙度参数，rh/rv 为水平/垂直极化 Fresnel 反射率。
    """
    q_value = _POLARIZATION_MIXING_Q * h_value
    exp_term = math.exp(-h_value * theta_cos_sq)
    rh_r = ((1 - q_value) * rh + q_value * rv) * exp_term
    rv_r = ((1 - q_value) * rv + q_value * rh) * exp_term
    return rh_r, rv_r


def rough_reflectance(theta_deg: float, h_value: float, rh: float, rv: float) -> tuple[float, float]:
    """粗糙表面反射率（从入射角角度计算）。

    量纲: 输入 theta_deg 单位为度 (°)，h_value/rh/rv 无量纲；输出 rh_r/rv_r 无量纲 (0-1)。
    """
    return _rough_reflectance_impl(math.cos(math.radians(theta_deg)) ** 2, h_value, rh, rv)


def rough_reflectance_from_context(
    context: TbModelContext,
    h_value: float,
    rh: float,
    rv: float,
) -> tuple[float, float]:
    """粗糙表面反射率（从预计算 context 计算）。

    量纲: 输入 h_value/rh/rv 无量纲；输出 rh_r/rv_r 无量纲 (0-1)。
    """
    return _rough_reflectance_impl(context.fresnel.cos_theta_sq, h_value, rh, rv)


def build_tb_model_context(freq_ghz: float, clay_fraction: float, theta_deg: float) -> TbModelContext:
    """构建 tau-omega 模型预计算上下文。

    量纲: freq_ghz 单位 GHz，theta_deg 单位度 (°)，clay_fraction 无量纲 (0-1)。
    """
    return TbModelContext(
        dielectric=build_mironov_context(freq_ghz, clay_fraction),
        fresnel=build_fresnel_context(theta_deg),
    )


def tb_model(
    ts: float,
    tau_value: float,
    h_value: float,
    clay_fraction: float,
    albedo: float,
    freq_ghz: float,
    theta_deg: float,
    soil_moisture: float,
    model_context: TbModelContext | None = None,
) -> tuple[float, float]:
    """tau-omega 微波辐射传输模型，计算 V/H 极化亮温。

    量纲: 输入 ts/tau_value/h_value/albedo/soil_moisture/clay_fraction 无量纲或 m³/m³；
    freq_ghz 单位 GHz，theta_deg 单位度 (°)。输出 tbv_model/tbh_model 单位 K (开尔文)。

    物理约束: soil_moisture ∈ [0, 0.6]，tau_value >= 0，h_value >= 0。
    超出约束范围返回 (inf, inf) 以让优化器自然排除无效解。
    """
    import math

    # 物理约束检查：超出范围返回 inf，让优化器排除无效解
    if not (0.0 <= soil_moisture <= 0.6):
        return float('inf'), float('inf')
    if tau_value < 0.0 or h_value < 0.0:
        return float('inf'), float('inf')

    if model_context is None:
        epsilon = mironov_dielectric(freq_ghz, soil_moisture, clay_fraction)
        rh, rv = fresnel_reflectance(theta_deg, epsilon)
        rh_r, rv_r = rough_reflectance(theta_deg, h_value, rh, rv)
    else:
        epsilon = mironov_dielectric_from_context(soil_moisture, model_context.dielectric)
        rh, rv = fresnel_reflectance_from_context(epsilon, model_context.fresnel)
        rh_r, rv_r = rough_reflectance_from_context(model_context, h_value, rh, rv)
    gamma = math.exp(-tau_value)
    tbv_model = ts * ((1 - rv_r) * gamma + (1 - albedo) * (1 - gamma) * (1 + rv_r * gamma))
    tbh_model = ts * ((1 - rh_r) * gamma + (1 - albedo) * (1 - gamma) * (1 + rh_r * gamma))
    return tbv_model, tbh_model


def f_sm_cost(
    x: Any,
    tbv: float,
    tbh: float,
    ts: float,
    tau_ini: float,
    h_value: float,
    clay_fraction: float,
    albedo: float,
    freq_ghz: float,
    theta_deg: float,
    model_context: TbModelContext | None = None,
) -> list[float]:
    """土壤湿度反演残差函数（用于 least_squares 优化）。

    量纲: 返回残差向量，前两项单位 K (亮温差)，第三项无量纲 (tau 正则化项)。
    freq_ghz 应在 0.1-40 GHz 范围内，超出返回 inf 残差。
    """
    if not (0.1 <= freq_ghz <= 40.0):
        return [float('inf'), float('inf'), float('inf')]

    soil_moisture = float(x[0])
    tau_value = float(x[1])
    tbv_model, tbh_model = tb_model(
        ts,
        tau_value,
        h_value,
        clay_fraction,
        albedo,
        freq_ghz,
        theta_deg,
        soil_moisture,
        model_context,
    )
    return [
        tbv_model - tbv,
        tbh_model - tbh,
        _TAU_REGULARIZATION_LAMBDA * (tau_value - tau_ini),
    ]


def f_h_cost(
    x: Any,
    tbv: float,
    tbh: float,
    ts: float,
    tau_ini: float,
    clay_fraction: float,
    albedo: float,
    freq_ghz: float,
    theta_deg: float,
    model_context: TbModelContext | None = None,
) -> list[float]:
    """粗糙度 h 反演残差函数（用于 least_squares 优化）。

    量纲: 返回残差向量，两项均单位 K (亮温差)。
    """
    soil_moisture = float(x[0])
    h_value = float(x[1])
    tbv_model, tbh_model = tb_model(
        ts,
        tau_ini,
        h_value,
        clay_fraction,
        albedo,
        freq_ghz,
        theta_deg,
        soil_moisture,
        model_context,
    )
    return [tbv_model - tbv, tbh_model - tbh]


def _finite_difference_jacobian(
    x: Any,
    residual_func: Any,
    lower_bounds: tuple[float, ...],
    upper_bounds: tuple[float, ...],
) -> Any:
    import numpy as np

    x = np.asarray(x, dtype=np.float64)
    base = np.asarray(residual_func(x), dtype=np.float64).reshape(-1)
    jac = np.empty((base.size, x.size), dtype=np.float64)
    eps = np.sqrt(np.finfo(np.float64).eps)

    for idx in range(x.size):
        step = max(1e-8, eps * max(1.0, abs(float(x[idx]))))
        lower = float(lower_bounds[idx])
        upper = float(upper_bounds[idx])

        forward = min(upper, float(x[idx]) + step)
        backward = max(lower, float(x[idx]) - step)

        if forward > x[idx] and backward < x[idx]:
            x_forward = x.copy()
            x_backward = x.copy()
            x_forward[idx] = forward
            x_backward[idx] = backward
            f_forward = np.asarray(residual_func(x_forward), dtype=np.float64).reshape(-1)
            f_backward = np.asarray(residual_func(x_backward), dtype=np.float64).reshape(-1)
            jac[:, idx] = (f_forward - f_backward) / (forward - backward)
        elif forward > x[idx]:
            x_forward = x.copy()
            x_forward[idx] = forward
            f_forward = np.asarray(residual_func(x_forward), dtype=np.float64).reshape(-1)
            jac[:, idx] = (f_forward - base) / (forward - float(x[idx]))
        elif backward < x[idx]:
            x_backward = x.copy()
            x_backward[idx] = backward
            f_backward = np.asarray(residual_func(x_backward), dtype=np.float64).reshape(-1)
            jac[:, idx] = (base - f_backward) / (float(x[idx]) - backward)
        else:
            jac[:, idx] = 0.0

    return jac


def retrieve_dynamic_h_pixel(
    tbv: float,
    tbh: float,
    ts: float,
    tau_ini: float,
    clay_fraction: float,
    albedo: float,
    porosity: float,
    freq_ghz: float,
    theta_deg: float,
) -> float:
    """单像素动态 h 粗糙度反演。

    量纲: 输入 tbv/tbh/ts 单位 K，freq_ghz 单位 GHz，theta_deg 单位度 (°)，
    其余无量纲。返回 h_value 无量纲（粗糙度参数）。
    """
    from scipy.optimize import least_squares

    if any(
        _is_nan(value)
        for value in [tbv, tbh, ts, tau_ini, clay_fraction, albedo, porosity, theta_deg]
    ):
        return float("nan")

    model_context = build_tb_model_context(freq_ghz, clay_fraction, theta_deg)
    residual = lambda x: f_h_cost(x, tbv, tbh, ts, tau_ini, clay_fraction, albedo, freq_ghz, theta_deg, model_context)
    lower_bounds = (0.02, 0.0)
    upper_bounds = (porosity, 3.0)
    if porosity <= 0.02:
        return float("nan")
    result = least_squares(
        residual,
        x0=[0.2, 0.5],
        bounds=(lower_bounds, upper_bounds),
        jac=lambda x: _finite_difference_jacobian(x, residual, lower_bounds, upper_bounds),
    )
    return float(result.x[1])


def ddca_retrieve_pixel(
    tbv: float,
    tbh: float,
    ts: float,
    tau_ini: float,
    h_value: float,
    clay_fraction: float,
    albedo: float,
    porosity: float,
    freq_ghz: float,
    theta_deg: float,
) -> tuple[float, float]:
    from scipy.optimize import least_squares

    if any(
        _is_nan(value)
        for value in [tbv, tbh, ts, tau_ini, h_value, clay_fraction, albedo, porosity, theta_deg]
    ):
        return float("nan"), float("nan")

    model_context = build_tb_model_context(freq_ghz, clay_fraction, theta_deg)
    residual = lambda x: f_sm_cost(
        x, tbv, tbh, ts, tau_ini, h_value, clay_fraction, albedo, freq_ghz, theta_deg, model_context
    )
    lower_bounds = (0.02, 0.0)
    upper_bounds = (porosity, 5.0)
    result = least_squares(
        residual,
        x0=[0.2, 0.5],
        bounds=(lower_bounds, upper_bounds),
        jac=lambda x: _finite_difference_jacobian(x, residual, lower_bounds, upper_bounds),
    )
    return float(result.x[0]), float(result.x[1])


def retrieve_dynamic_h_grid(
    tbv: Any,
    tbh: Any,
    ts: Any,
    tau_ini: Any,
    clay_fraction: Any,
    albedo: Any,
    porosity: Any,
    freq_ghz: float,
    theta_deg: Any,
) -> Any:
    import numpy as np

    tbv = np.asarray(tbv, dtype=np.float64)
    tbh = np.asarray(tbh, dtype=np.float64)
    ts = np.asarray(ts, dtype=np.float64)
    tau_ini = np.asarray(tau_ini, dtype=np.float64)
    clay_fraction = np.asarray(clay_fraction, dtype=np.float64)
    albedo = np.asarray(albedo, dtype=np.float64)
    porosity = np.asarray(porosity, dtype=np.float64)
    theta_deg = np.asarray(theta_deg, dtype=np.float64)
    output = np.full(tbv.shape, np.nan, dtype=np.float64)
    tbv_flat = tbv.reshape(-1)
    tbh_flat = tbh.reshape(-1)
    ts_flat = ts.reshape(-1)
    tau_flat = tau_ini.reshape(-1)
    clay_flat = clay_fraction.reshape(-1)
    albedo_flat = albedo.reshape(-1)
    porosity_flat = porosity.reshape(-1)
    theta_flat = theta_deg.reshape(-1)
    output_flat = output.reshape(-1)

    valid_mask = ~(
        np.isnan(tbv) | np.isnan(tbh) | np.isnan(ts) | np.isnan(tau_ini)
        | np.isnan(clay_fraction) | np.isnan(albedo) | np.isnan(porosity)
        | np.isnan(theta_deg) | (porosity <= 0.02)
    )
    if not np.any(valid_mask):
        return output

    valid_indices = np.where(valid_mask.ravel())[0]
    tbv_flat = tbv.ravel()
    tbh_flat = tbh.ravel()
    ts_flat = ts.ravel()
    tau_flat = tau_ini.ravel()
    clay_flat = clay_fraction.ravel()
    albedo_flat = albedo.ravel()
    porosity_flat = porosity.ravel()
    theta_flat = theta_deg.ravel()
    output_flat = output.reshape(-1)

    unique_keys = set(
        (float(clay_flat[i]), float(theta_flat[i])) for i in valid_indices
    )
    context_cache = {
        key: build_tb_model_context(freq_ghz, key[0], key[1]) for key in unique_keys
    }

    for index in valid_indices:
        key = (float(clay_flat[index]), float(theta_flat[index]))
        output_flat[index] = retrieve_dynamic_h_pixel(
            float(tbv_flat[index]),
            float(tbh_flat[index]),
            float(ts_flat[index]),
            float(tau_flat[index]),
            key[0],
            float(albedo_flat[index]),
            float(porosity_flat[index]),
            freq_ghz,
            key[1],
            model_context=context_cache[key],
        )
    return output


def ddca_retrieve_grid(
    tbv: Any,
    tbh: Any,
    ts: Any,
    tau_ini: Any,
    h_value: Any,
    clay_fraction: Any,
    albedo: Any,
    porosity: Any,
    freq_ghz: float,
    theta_deg: Any,
) -> tuple[Any, Any]:
    import numpy as np

    tbv = np.asarray(tbv, dtype=np.float64)
    tbh = np.asarray(tbh, dtype=np.float64)
    ts = np.asarray(ts, dtype=np.float64)
    tau_ini = np.asarray(tau_ini, dtype=np.float64)
    h_value = np.asarray(h_value, dtype=np.float64)
    clay_fraction = np.asarray(clay_fraction, dtype=np.float64)
    albedo = np.asarray(albedo, dtype=np.float64)
    porosity = np.asarray(porosity, dtype=np.float64)
    theta_deg = np.asarray(theta_deg, dtype=np.float64)
    sm = np.full(tbv.shape, np.nan, dtype=np.float64)
    vod = np.full(tbv.shape, np.nan, dtype=np.float64)
    tbv_flat = tbv.reshape(-1)
    tbh_flat = tbh.reshape(-1)
    ts_flat = ts.reshape(-1)
    tau_flat = tau_ini.reshape(-1)
    h_flat = h_value.reshape(-1)
    clay_flat = clay_fraction.reshape(-1)
    albedo_flat = albedo.reshape(-1)
    porosity_flat = porosity.reshape(-1)
    theta_flat = theta_deg.reshape(-1)
    sm_flat = sm.reshape(-1)
    vod_flat = vod.reshape(-1)

    valid_mask = ~(
        np.isnan(tbv) | np.isnan(tbh) | np.isnan(ts) | np.isnan(tau_ini)
        | np.isnan(h_value) | np.isnan(clay_fraction) | np.isnan(albedo)
        | np.isnan(porosity) | np.isnan(theta_deg)
    )
    if not np.any(valid_mask):
        return sm, vod

    valid_indices = np.where(valid_mask.ravel())[0]
    tbv_flat = tbv.ravel()
    tbh_flat = tbh.ravel()
    ts_flat = ts.ravel()
    tau_flat = tau_ini.ravel()
    h_flat = h_value.ravel()
    clay_flat = clay_fraction.ravel()
    albedo_flat = albedo.ravel()
    porosity_flat = porosity.ravel()
    theta_flat = theta_deg.ravel()
    sm_flat = sm.ravel()
    vod_flat = vod.ravel()

    unique_keys = set(
        (float(clay_flat[i]), float(theta_flat[i])) for i in valid_indices
    )
    context_cache = {
        key: build_tb_model_context(freq_ghz, key[0], key[1]) for key in unique_keys
    }

    for index in valid_indices:
        key = (float(clay_flat[index]), float(theta_flat[index]))
        sm_flat[index], vod_flat[index] = ddca_retrieve_pixel(
            float(tbv_flat[index]),
            float(tbh_flat[index]),
            float(ts_flat[index]),
            float(tau_flat[index]),
            float(h_flat[index]),
            key[0],
            float(albedo_flat[index]),
            float(porosity_flat[index]),
            freq_ghz,
            key[1],
            model_context=context_cache[key],
        )
    return sm, vod
