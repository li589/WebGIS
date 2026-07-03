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


def _is_nan(value: float) -> bool:
    return math.isnan(value)


@dataclass(frozen=True, slots=True)
class TbModelContext:
    dielectric: MironovContext
    fresnel: FresnelContext


def rough_reflectance(theta_deg: float, h_value: float, rh: float, rv: float) -> tuple[float, float]:
    import math

    q_value = 0.1771 * h_value
    exp_term = math.exp(-h_value * math.cos(math.radians(theta_deg)) ** 2)
    rh_r = ((1 - q_value) * rh + q_value * rv) * exp_term
    rv_r = ((1 - q_value) * rv + q_value * rh) * exp_term
    return rh_r, rv_r


def rough_reflectance_from_context(context: TbModelContext, h_value: float, rh: float, rv: float) -> tuple[float, float]:
    q_value = 0.1771 * h_value
    exp_term = math.exp(-h_value * context.fresnel.cos_theta_sq)
    rh_r = ((1 - q_value) * rh + q_value * rv) * exp_term
    rv_r = ((1 - q_value) * rv + q_value * rh) * exp_term
    return rh_r, rv_r


def build_tb_model_context(freq_ghz: float, clay_fraction: float, theta_deg: float) -> TbModelContext:
    return TbModelContext(
        dielectric=build_mironov_context(freq_ghz, clay_fraction),
        fresnel=build_fresnel_context(theta_deg),
    )


def tb_model(
    tbv_obs: float,
    tbh_obs: float,
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
    import math

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
    _ = (tbv_obs, tbh_obs)
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
    soil_moisture = float(x[0])
    tau_value = float(x[1])
    tbv_model, tbh_model = tb_model(
        tbv,
        tbh,
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
    lambda_value = 20.0
    return [
        tbv_model - tbv,
        tbh_model - tbh,
        lambda_value * (tau_value - tau_ini),
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
    soil_moisture = float(x[0])
    h_value = float(x[1])
    tbv_model, tbh_model = tb_model(
        tbv,
        tbh,
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
    for index in range(tbv_flat.size):
        output_flat[index] = retrieve_dynamic_h_pixel(
            tbv_flat[index],
            tbh_flat[index],
            ts_flat[index],
            tau_flat[index],
            clay_flat[index],
            albedo_flat[index],
            porosity_flat[index],
            freq_ghz,
            theta_flat[index],
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
    for index in range(tbv_flat.size):
        sm_flat[index], vod_flat[index] = ddca_retrieve_pixel(
            tbv_flat[index],
            tbh_flat[index],
            ts_flat[index],
            tau_flat[index],
            h_flat[index],
            clay_flat[index],
            albedo_flat[index],
            porosity_flat[index],
            freq_ghz,
            theta_flat[index],
        )
    return sm, vod
