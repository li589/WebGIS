from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from algorithms.physics import (
    _fresnel_reflectance_kernel,
    _mironov_dielectric_kernel,
    FresnelContext,
    MironovContext,
    build_fresnel_context,
    build_mironov_context,
    fresnel_reflectance,
    fresnel_reflectance_from_context,
    mironov_dielectric,
    mironov_dielectric_from_context,
    tau_from_ndvi,
)
from ingest.mat_bundle import get_first_available, normalize_aliases_param


@dataclass(frozen=True, slots=True)
class OmegaConfig:
    freq_ghz: float = 1.4
    temp_scheme: str = "ORIG_TS"
    exp_mode: str = "Exp0"
    tau_rel_frac: float = 0.05
    kmin: int = 2
    alpha0: float = 0.1771
    lambda_alpha: float = 1.0
    bounds_h: tuple[float, float] = (0.0, 3.0)
    bounds_alpha: tuple[float, float] = (0.05, 0.35)
    omega0: float = 0.12
    bounds_omega: tuple[float, float] = (0.0, 1.0)
    lambda_smooth: float = 1.0
    lambda_tau: float = 20.0
    lambda_list: tuple[float, ...] = (1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0, 1000000.0)
    block_days: int = 8
    pixel_chunk_size: int = 256
    use_fixed_omega_for_halpha: bool = False
    use_fixed_omega_in_blocks: bool = False
    fixed_omega_fallback: float | None = None
    save_exp2_omega_by_lambda: bool = False
    qc_domega: float = 1e-3
    qc_dtau: float = 1e-2
    qc_dh: float = 1e-2


@dataclass(frozen=True, slots=True)
class OmegaFieldConfig:
    tbv_mat_aliases: tuple[str, ...] = ("TBv_mat", "TBv")
    tbh_mat_aliases: tuple[str, ...] = ("TBh_mat",)
    ia_mat_aliases: tuple[str, ...] = ("IA_mat",)
    ts_mat_aliases: tuple[str, ...] = ("Ts_mat",)
    tc_mat_aliases: tuple[str, ...] = ("TC_mat",)
    tg_mat_aliases: tuple[str, ...] = ("TG_mat",)
    smref_mat_aliases: tuple[str, ...] = ("SMref_mat",)
    ndvi_mat_aliases: tuple[str, ...] = ("NDVI_mat",)
    sf_mat_aliases: tuple[str, ...] = ("SF_mat",)
    albedo_aliases: tuple[str, ...] = ("Albedo", "ALBEDO")
    b_aliases: tuple[str, ...] = ("B", "b")
    clay_fraction_aliases: tuple[str, ...] = ("CF",)
    bulk_density_aliases: tuple[str, ...] = ("BD",)
    h_static_aliases: tuple[str, ...] = ("H", "h")
    landcover_aliases: tuple[str, ...] = ("LC", "IGBP_9km_12")
    ndvi_v_max_aliases: tuple[str, ...] = ("NDVI_v_max",)
    ndvi_v_min_aliases: tuple[str, ...] = ("NDVI_v_min",)
    omega_fixed_aliases: tuple[str, ...] = (
        "omega_fixed_vec",
        "omega_fixed",
        "omega_pix_map",
        "omega_pixel",
        "omega_fixed_map",
    )
    omega_pft_aliases: tuple[str, ...] = ("omega_pft", "omega_pft_vec")
    exp0_h_aliases: tuple[str, ...] = ("h_exp0_vec", "h_star_exp0_vec", "h_star_vec_exp0", "h_star_vec", "h_star_map")
    exp0_alpha_aliases: tuple[str, ...] = (
        "alpha_exp0_vec",
        "alpha_star_exp0_vec",
        "alpha_star_vec_exp0",
        "alpha_star_vec",
        "alpha_star_map",
    )


def build_omega_config(params: dict[str, Any]) -> OmegaConfig:
    return OmegaConfig(
        freq_ghz=float(params.get("freq_ghz", 1.4)),
        temp_scheme=str(params.get("temp_scheme", "ORIG_TS")),
        exp_mode=str(params.get("exp_mode", "Exp0")),
        tau_rel_frac=float(params.get("tau_rel_frac", 0.05)),
        kmin=int(params.get("kmin", 2)),
        alpha0=float(params.get("alpha0", 0.1771)),
        lambda_alpha=float(params.get("lambda_alpha", 1.0)),
        bounds_h=tuple(params.get("bounds_h", [0.0, 3.0])),
        bounds_alpha=tuple(params.get("bounds_alpha", [0.05, 0.35])),
        omega0=float(params.get("omega0", 0.12)),
        bounds_omega=tuple(params.get("bounds_omega", [0.0, 1.0])),
        lambda_smooth=float(params.get("lambda_smooth", 1.0)),
        lambda_tau=float(params.get("lambda_tau", 20.0)),
        lambda_list=parse_lambda_list(params.get("lambda_list")),
        block_days=int(params.get("block_days", 8)),
        pixel_chunk_size=int(params.get("pixel_chunk_size", 256)),
        use_fixed_omega_for_halpha=bool(params.get("use_fixed_omega_for_halpha", False)),
        use_fixed_omega_in_blocks=bool(params.get("use_fixed_omega_in_blocks", False)),
        fixed_omega_fallback=params.get("fixed_omega_fallback"),
        save_exp2_omega_by_lambda=bool(params.get("save_exp2_omega_by_lambda", False)),
        qc_domega=float(params.get("qc_domega", 1e-3)),
        qc_dtau=float(params.get("qc_dtau", 1e-2)),
        qc_dh=float(params.get("qc_dh", 1e-2)),
    )


def build_omega_field_config(params: dict[str, Any]) -> OmegaFieldConfig:
    return OmegaFieldConfig(
        tbv_mat_aliases=normalize_aliases_param(params.get("tbv_mat_aliases"), ("TBv_mat",)),
        tbh_mat_aliases=normalize_aliases_param(params.get("tbh_mat_aliases"), ("TBh_mat",)),
        ia_mat_aliases=normalize_aliases_param(params.get("ia_mat_aliases"), ("IA_mat",)),
        ts_mat_aliases=normalize_aliases_param(params.get("ts_mat_aliases"), ("Ts_mat",)),
        tc_mat_aliases=normalize_aliases_param(params.get("tc_mat_aliases"), ("TC_mat",)),
        tg_mat_aliases=normalize_aliases_param(params.get("tg_mat_aliases"), ("TG_mat",)),
        smref_mat_aliases=normalize_aliases_param(params.get("smref_mat_aliases"), ("SMref_mat",)),
        ndvi_mat_aliases=normalize_aliases_param(params.get("ndvi_mat_aliases"), ("NDVI_mat",)),
        sf_mat_aliases=normalize_aliases_param(params.get("sf_mat_aliases"), ("SF_mat",)),
        albedo_aliases=normalize_aliases_param(params.get("albedo_aliases"), ("Albedo", "ALBEDO")),
        b_aliases=normalize_aliases_param(params.get("b_aliases"), ("B", "b")),
        clay_fraction_aliases=normalize_aliases_param(params.get("clay_fraction_aliases"), ("CF",)),
        bulk_density_aliases=normalize_aliases_param(params.get("bulk_density_aliases"), ("BD",)),
        h_static_aliases=normalize_aliases_param(params.get("h_static_aliases"), ("H", "h")),
        landcover_aliases=normalize_aliases_param(params.get("landcover_aliases"), ("LC", "IGBP_9km_12")),
        ndvi_v_max_aliases=normalize_aliases_param(params.get("ndvi_v_max_aliases"), ("NDVI_v_max",)),
        ndvi_v_min_aliases=normalize_aliases_param(params.get("ndvi_v_min_aliases"), ("NDVI_v_min",)),
        omega_fixed_aliases=normalize_aliases_param(
            params.get("omega_fixed_aliases"),
            ("omega_fixed_vec", "omega_fixed", "omega_pix_map", "omega_pixel", "omega_fixed_map"),
        ),
        omega_pft_aliases=normalize_aliases_param(params.get("omega_pft_aliases"), ("omega_pft", "omega_pft_vec")),
        exp0_h_aliases=normalize_aliases_param(
            params.get("exp0_h_aliases"),
            ("h_exp0_vec", "h_star_exp0_vec", "h_star_vec_exp0", "h_star_vec", "h_star_map"),
        ),
        exp0_alpha_aliases=normalize_aliases_param(
            params.get("exp0_alpha_aliases"),
            ("alpha_exp0_vec", "alpha_star_exp0_vec", "alpha_star_vec_exp0", "alpha_star_vec", "alpha_star_map"),
        ),
    )


@dataclass(frozen=True, slots=True)
class OmegaTbForwardContext:
    dielectric: MironovContext
    fresnel: FresnelContext


def _build_tb_forward_contexts(theta_values: Any, freq_ghz: float, clay_fraction: float) -> tuple[OmegaTbForwardContext, ...]:
    return tuple(_build_tb_forward_context(freq_ghz, clay_fraction, float(theta_value)) for theta_value in theta_values)


def _select_tb_forward_contexts(
    all_model_contexts: tuple[OmegaTbForwardContext, ...],
    indices: Any,
) -> tuple[OmegaTbForwardContext, ...]:
    import numpy as np

    return tuple(all_model_contexts[int(idx)] for idx in np.asarray(indices, dtype=np.int64).reshape(-1))


def parse_lambda_list(value: object) -> tuple[float, ...]:
    if value is None:
        return (1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0, 1000000.0)
    if isinstance(value, str):
        parts = [item.strip() for item in value.split(",") if item.strip()]
        return tuple(float(item) for item in parts)
    if isinstance(value, (list, tuple)):
        return tuple(float(item) for item in value)
    return (float(value),)


def _rough_reflectance(theta_deg: float, h_value: float, alpha_value: float, rh: float, rv: float) -> tuple[float, float]:
    import math

    q_value = alpha_value * h_value
    if q_value < 0.0:
        q_value = 0.0
    cos_theta = math.cos(math.radians(theta_deg))
    attenuation = math.exp(-h_value * cos_theta * cos_theta)
    delta_r = rv - rh
    rh_r = attenuation * (rh + q_value * delta_r)
    rv_r = attenuation * (rv - q_value * delta_r)
    return rh_r, rv_r


def _rough_reflectance_from_context(
    context: OmegaTbForwardContext,
    h_value: float,
    alpha_value: float,
    rh: float,
    rv: float,
) -> tuple[float, float]:
    import math

    q_value = alpha_value * h_value
    if q_value < 0.0:
        q_value = 0.0
    attenuation = math.exp(-h_value * context.fresnel.cos_theta_sq)
    delta_r = rv - rh
    rh_r = attenuation * (rh + q_value * delta_r)
    rv_r = attenuation * (rv - q_value * delta_r)
    return rh_r, rv_r


def _build_tb_forward_context(freq_ghz: float, clay_fraction: float, theta_deg: float) -> OmegaTbForwardContext:
    return OmegaTbForwardContext(
        dielectric=build_mironov_context(freq_ghz, clay_fraction),
        fresnel=build_fresnel_context(theta_deg),
    )


def _finite_difference_jacobian(
    x: Any,
    residual_func: Any,
    lower_bounds: tuple[float, ...],
    upper_bounds: tuple[float, ...],
) -> Any:
    import numpy as np

    x = np.asarray(x, dtype=np.float64)
    base = np.asarray(residual_func(x), dtype=np.float64).reshape(-1)
    return _finite_difference_jacobian_from_base(x, base, residual_func, lower_bounds, upper_bounds)


def _finite_difference_jacobian_from_base(
    x: Any,
    base: Any,
    residual_func: Any,
    lower_bounds: tuple[float, ...],
    upper_bounds: tuple[float, ...],
) -> Any:
    import numpy as np

    x = np.asarray(x, dtype=np.float64)
    base = np.asarray(base, dtype=np.float64).reshape(-1)
    jac = np.empty((base.size, x.size), dtype=np.float64)
    eps = np.sqrt(np.finfo(np.float64).eps)
    x_forward = x.copy()
    x_backward = x.copy()

    for idx in range(x.size):
        x_value = float(x[idx])
        step = max(1e-8, eps * max(1.0, abs(x_value)))
        lower = float(lower_bounds[idx])
        upper = float(upper_bounds[idx])
        forward = min(upper, x_value + step)
        backward = max(lower, x_value - step)

        if forward > x_value and backward < x_value:
            x_forward[idx] = forward
            x_backward[idx] = backward
            f_forward = np.asarray(residual_func(x_forward), dtype=np.float64).reshape(-1)
            f_backward = np.asarray(residual_func(x_backward), dtype=np.float64).reshape(-1)
            jac[:, idx] = (f_forward - f_backward) / (forward - backward)
            x_forward[idx] = x_value
            x_backward[idx] = x_value
        elif forward > x_value:
            x_forward[idx] = forward
            f_forward = np.asarray(residual_func(x_forward), dtype=np.float64).reshape(-1)
            jac[:, idx] = (f_forward - base) / (forward - x_value)
            x_forward[idx] = x_value
        elif backward < x_value:
            x_backward[idx] = backward
            f_backward = np.asarray(residual_func(x_backward), dtype=np.float64).reshape(-1)
            jac[:, idx] = (base - f_backward) / (x_value - backward)
            x_backward[idx] = x_value
        else:
            jac[:, idx] = 0.0

    return jac


def _finite_difference_scalar_jacobian(x_value: float, residual_func: Any, lower_bound: float, upper_bound: float) -> Any:
    import numpy as np

    base = np.asarray(residual_func(x_value), dtype=np.float64).reshape(-1)
    eps = np.sqrt(np.finfo(np.float64).eps)
    step = max(1e-8, eps * max(1.0, abs(float(x_value))))
    forward = min(float(upper_bound), float(x_value) + step)
    backward = max(float(lower_bound), float(x_value) - step)

    if forward > x_value and backward < x_value:
        f_forward = np.asarray(residual_func(forward), dtype=np.float64).reshape(-1)
        f_backward = np.asarray(residual_func(backward), dtype=np.float64).reshape(-1)
        column = (f_forward - f_backward) / (forward - backward)
    elif forward > x_value:
        f_forward = np.asarray(residual_func(forward), dtype=np.float64).reshape(-1)
        column = (f_forward - base) / (forward - float(x_value))
    elif backward < x_value:
        f_backward = np.asarray(residual_func(backward), dtype=np.float64).reshape(-1)
        column = (base - f_backward) / (float(x_value) - backward)
    else:
        column = np.zeros_like(base)
    return column.reshape(-1, 1)


def tb_forward_single_temp(
    soil_moisture: float,
    tau_value: float,
    h_value: float,
    alpha_value: float,
    omega_value: float,
    ts_value: float,
    theta_deg: float,
    clay_fraction: float,
    freq_ghz: float,
    scale: float = 1.0,
    model_context: OmegaTbForwardContext | None = None,
) -> tuple[float, float]:
    import math

    if model_context is None:
        epsilon = mironov_dielectric(freq_ghz, soil_moisture, clay_fraction)
        rh, rv = fresnel_reflectance(theta_deg, epsilon)
        q_value = alpha_value * h_value
        if q_value < 0.0:
            q_value = 0.0
        cos_theta = math.cos(math.radians(theta_deg))
        attenuation = math.exp(-h_value * cos_theta * cos_theta)
    else:
        epsilon = mironov_dielectric_from_context(soil_moisture, model_context.dielectric)
        rh, rv = fresnel_reflectance_from_context(epsilon, model_context.fresnel)
        q_value = alpha_value * h_value
        if q_value < 0.0:
            q_value = 0.0
        attenuation = math.exp(-h_value * model_context.fresnel.cos_theta_sq)
    delta_r = rv - rh
    rh_r = attenuation * (rh + q_value * delta_r)
    rv_r = attenuation * (rv - q_value * delta_r)
    gamma = math.exp(-tau_value)
    one_minus_gamma = 1.0 - gamma
    canopy_factor = (1.0 - omega_value) * one_minus_gamma
    rv_gamma = rv_r * gamma
    rh_gamma = rh_r * gamma
    scale_ts = scale * ts_value
    tbv_m = scale_ts * ((1.0 - rv_r) * gamma + canopy_factor * (1.0 + rv_gamma))
    tbh_m = scale_ts * ((1.0 - rh_r) * gamma + canopy_factor * (1.0 + rh_gamma))
    return tbv_m, tbh_m


def tb_forward_dual_temp(
    soil_moisture: float,
    tau_value: float,
    h_value: float,
    alpha_value: float,
    omega_value: float,
    tc_value: float,
    tg_value: float,
    theta_deg: float,
    clay_fraction: float,
    freq_ghz: float,
    scale: float = 1.0,
    model_context: OmegaTbForwardContext | None = None,
) -> tuple[float, float]:
    import math

    if model_context is None:
        epsilon = mironov_dielectric(freq_ghz, soil_moisture, clay_fraction)
        rh, rv = fresnel_reflectance(theta_deg, epsilon)
        q_value = alpha_value * h_value
        if q_value < 0.0:
            q_value = 0.0
        cos_theta = math.cos(math.radians(theta_deg))
        attenuation = math.exp(-h_value * cos_theta * cos_theta)
    else:
        epsilon = mironov_dielectric_from_context(soil_moisture, model_context.dielectric)
        rh, rv = fresnel_reflectance_from_context(epsilon, model_context.fresnel)
        q_value = alpha_value * h_value
        if q_value < 0.0:
            q_value = 0.0
        attenuation = math.exp(-h_value * model_context.fresnel.cos_theta_sq)
    delta_r = rv - rh
    rh_r = attenuation * (rh + q_value * delta_r)
    rv_r = attenuation * (rv - q_value * delta_r)
    gamma = math.exp(-tau_value)
    one_minus_gamma = 1.0 - gamma
    canopy_factor = (1.0 - omega_value) * one_minus_gamma
    rv_gamma = rv_r * gamma
    rh_gamma = rh_r * gamma
    scale_tg = scale * tg_value
    scale_tc = scale * tc_value
    tbv_m = scale_tg * ((1.0 - rv_r) * gamma) + scale_tc * (canopy_factor * (1.0 + rv_gamma))
    tbh_m = scale_tg * ((1.0 - rh_r) * gamma) + scale_tc * (canopy_factor * (1.0 + rh_gamma))
    return tbv_m, tbh_m


def _tb_forward_single_temp_with_context(
    soil_moisture: float,
    tau_value: float,
    h_value: float,
    alpha_value: float,
    omega_value: float,
    ts_value: float,
    scale: float,
    model_context: OmegaTbForwardContext,
) -> tuple[float, float]:
    dielectric = model_context.dielectric
    fresnel = model_context.fresnel
    return _tb_forward_single_temp_kernel(
        soil_moisture,
        tau_value,
        h_value,
        alpha_value,
        omega_value,
        ts_value,
        scale,
        dielectric.zxmvt,
        dielectric.znd,
        dielectric.zkd,
        dielectric.znb,
        dielectric.zkb,
        dielectric.znu,
        dielectric.zku,
        fresnel.cos_theta,
        fresnel.sin_theta_sq,
        fresnel.cos_theta_sq,
    )


def _tb_forward_single_temp_kernel(
    soil_moisture: float,
    tau_value: float,
    h_value: float,
    alpha_value: float,
    omega_value: float,
    ts_value: float,
    scale: float,
    zxmvt: float,
    znd: float,
    zkd: float,
    znb: float,
    zkb: float,
    znu: float,
    zku: float,
    cos_theta: float,
    sin_theta_sq: float,
    cos_theta_sq: float,
) -> tuple[float, float]:
    import math

    epsilon_real, epsilon_imag = _mironov_dielectric_kernel(
        soil_moisture,
        zxmvt,
        znd,
        zkd,
        znb,
        zkb,
        znu,
        zku,
    )
    rh, rv = _fresnel_reflectance_kernel(
        epsilon_real,
        epsilon_imag,
        cos_theta,
        sin_theta_sq,
    )
    q_value = alpha_value * h_value
    if q_value < 0.0:
        q_value = 0.0
    attenuation = math.exp(-h_value * cos_theta_sq)
    delta_r = rv - rh
    rh_r = attenuation * (rh + q_value * delta_r)
    rv_r = attenuation * (rv - q_value * delta_r)
    gamma = math.exp(-tau_value)
    one_minus_gamma = 1.0 - gamma
    canopy_factor = (1.0 - omega_value) * one_minus_gamma
    rv_gamma = rv_r * gamma
    rh_gamma = rh_r * gamma
    scale_ts = scale * ts_value
    tbv_m = scale_ts * ((1.0 - rv_r) * gamma + canopy_factor * (1.0 + rv_gamma))
    tbh_m = scale_ts * ((1.0 - rh_r) * gamma + canopy_factor * (1.0 + rh_gamma))
    return tbv_m, tbh_m


def _tb_forward_dual_temp_with_context(
    soil_moisture: float,
    tau_value: float,
    h_value: float,
    alpha_value: float,
    omega_value: float,
    tc_value: float,
    tg_value: float,
    scale: float,
    model_context: OmegaTbForwardContext,
) -> tuple[float, float]:
    dielectric = model_context.dielectric
    fresnel = model_context.fresnel
    return _tb_forward_dual_temp_kernel(
        soil_moisture,
        tau_value,
        h_value,
        alpha_value,
        omega_value,
        tc_value,
        tg_value,
        scale,
        dielectric.zxmvt,
        dielectric.znd,
        dielectric.zkd,
        dielectric.znb,
        dielectric.zkb,
        dielectric.znu,
        dielectric.zku,
        fresnel.cos_theta,
        fresnel.sin_theta_sq,
        fresnel.cos_theta_sq,
    )


def _tb_forward_dual_temp_kernel(
    soil_moisture: float,
    tau_value: float,
    h_value: float,
    alpha_value: float,
    omega_value: float,
    tc_value: float,
    tg_value: float,
    scale: float,
    zxmvt: float,
    znd: float,
    zkd: float,
    znb: float,
    zkb: float,
    znu: float,
    zku: float,
    cos_theta: float,
    sin_theta_sq: float,
    cos_theta_sq: float,
) -> tuple[float, float]:
    import math

    epsilon_real, epsilon_imag = _mironov_dielectric_kernel(
        soil_moisture,
        zxmvt,
        znd,
        zkd,
        znb,
        zkb,
        znu,
        zku,
    )
    rh, rv = _fresnel_reflectance_kernel(
        epsilon_real,
        epsilon_imag,
        cos_theta,
        sin_theta_sq,
    )
    q_value = alpha_value * h_value
    if q_value < 0.0:
        q_value = 0.0
    attenuation = math.exp(-h_value * cos_theta_sq)
    delta_r = rv - rh
    rh_r = attenuation * (rh + q_value * delta_r)
    rv_r = attenuation * (rv - q_value * delta_r)
    gamma = math.exp(-tau_value)
    one_minus_gamma = 1.0 - gamma
    canopy_factor = (1.0 - omega_value) * one_minus_gamma
    rv_gamma = rv_r * gamma
    rh_gamma = rh_r * gamma
    scale_tg = scale * tg_value
    scale_tc = scale * tc_value
    tbv_m = scale_tg * ((1.0 - rv_r) * gamma) + scale_tc * (canopy_factor * (1.0 + rv_gamma))
    tbh_m = scale_tg * ((1.0 - rh_r) * gamma) + scale_tc * (canopy_factor * (1.0 + rh_gamma))
    return tbv_m, tbh_m


def _resid_halpha_single_temp_prepared(
    h_value: float,
    alpha_value: float,
    tbv: Any,
    tbh: Any,
    ts: Any,
    tau: Any,
    sm_ref: Any,
    theta: Any,
    clay_fraction: float,
    freq_ghz: float,
    omega_low: float,
    alpha0: float,
    sqrt_lambda_alpha: float,
    sv: float,
    sh: float,
    model_contexts: tuple[OmegaTbForwardContext, ...] | None = None,
) -> Any:
    import numpy as np

    count = len(tbv)
    residual = np.empty(2 * count + 1, dtype=np.float64)
    if model_contexts is None:
        for k in range(count):
            tbv_m, tbh_m = tb_forward_single_temp(
                float(sm_ref[k]),
                float(tau[k]),
                h_value,
                alpha_value,
                omega_low,
                float(ts[k]),
                float(theta[k]),
                clay_fraction,
                freq_ghz,
                1.0,
                None,
            )
            base = 2 * k
            residual[base] = sv * (tbv_m - float(tbv[k]))
            residual[base + 1] = sh * (tbh_m - float(tbh[k]))
    else:
        for k, model_context in enumerate(model_contexts):
            tbv_m, tbh_m = _tb_forward_single_temp_with_context(
                float(sm_ref[k]),
                float(tau[k]),
                h_value,
                alpha_value,
                omega_low,
                float(ts[k]),
                1.0,
                model_context,
            )
            base = 2 * k
            residual[base] = sv * (tbv_m - float(tbv[k]))
            residual[base + 1] = sh * (tbh_m - float(tbh[k]))
    residual[-1] = sqrt_lambda_alpha * (alpha_value - alpha0)
    return residual


def _resid_halpha_dual_temp_prepared(
    h_value: float,
    alpha_value: float,
    tbv: Any,
    tbh: Any,
    tc: Any,
    tg: Any,
    tau: Any,
    sm_ref: Any,
    theta: Any,
    clay_fraction: float,
    freq_ghz: float,
    omega_low: float,
    alpha0: float,
    sqrt_lambda_alpha: float,
    sv: float,
    sh: float,
    model_contexts: tuple[OmegaTbForwardContext, ...] | None = None,
) -> Any:
    import numpy as np

    count = len(tbv)
    residual = np.empty(2 * count + 1, dtype=np.float64)
    if model_contexts is None:
        for k in range(count):
            tbv_m, tbh_m = tb_forward_dual_temp(
                float(sm_ref[k]),
                float(tau[k]),
                h_value,
                alpha_value,
                omega_low,
                float(tc[k]),
                float(tg[k]),
                float(theta[k]),
                clay_fraction,
                freq_ghz,
                1.0,
                None,
            )
            base = 2 * k
            residual[base] = sv * (tbv_m - float(tbv[k]))
            residual[base + 1] = sh * (tbh_m - float(tbh[k]))
    else:
        for k, model_context in enumerate(model_contexts):
            tbv_m, tbh_m = _tb_forward_dual_temp_with_context(
                float(sm_ref[k]),
                float(tau[k]),
                h_value,
                alpha_value,
                omega_low,
                float(tc[k]),
                float(tg[k]),
                1.0,
                model_context,
            )
            base = 2 * k
            residual[base] = sv * (tbv_m - float(tbv[k]))
            residual[base + 1] = sh * (tbh_m - float(tbh[k]))
    residual[-1] = sqrt_lambda_alpha * (alpha_value - alpha0)
    return residual


def _resid_omega_block_single_temp_prepared(
    omega_value: float,
    tbv: Any,
    tbh: Any,
    ts: Any,
    tau: Any,
    sm_ref: Any,
    theta: Any,
    clay_fraction: float,
    freq_ghz: float,
    h_series: Any,
    alpha_series: Any,
    smooth_weight: float,
    omega_prev: float,
    sv: float,
    sh: float,
    model_contexts: tuple[OmegaTbForwardContext, ...] | None = None,
) -> Any:
    import numpy as np

    count = len(tbv)
    include_smooth = bool(np.isfinite(omega_prev) and smooth_weight > 0.0)
    residual = np.empty(2 * count + (1 if include_smooth else 0), dtype=np.float64)
    if model_contexts is None:
        for k in range(count):
            tbv_m, tbh_m = tb_forward_single_temp(
                float(sm_ref[k]),
                float(tau[k]),
                float(h_series[k]),
                float(alpha_series[k]),
                omega_value,
                float(ts[k]),
                theta[k],
                clay_fraction,
                freq_ghz,
                1.0,
                None,
            )
            base = 2 * k
            residual[base] = sv * (tbv_m - float(tbv[k]))
            residual[base + 1] = sh * (tbh_m - float(tbh[k]))
    else:
        for k, model_context in enumerate(model_contexts):
            tbv_m, tbh_m = _tb_forward_single_temp_with_context(
                float(sm_ref[k]),
                float(tau[k]),
                float(h_series[k]),
                float(alpha_series[k]),
                omega_value,
                float(ts[k]),
                1.0,
                model_context,
            )
            base = 2 * k
            residual[base] = sv * (tbv_m - float(tbv[k]))
            residual[base + 1] = sh * (tbh_m - float(tbh[k]))
    if include_smooth:
        residual[-1] = smooth_weight * (omega_value - omega_prev)
    return residual


def _resid_omega_block_dual_temp_prepared(
    omega_value: float,
    tbv: Any,
    tbh: Any,
    tc: Any,
    tg: Any,
    tau: Any,
    sm_ref: Any,
    theta: Any,
    clay_fraction: float,
    freq_ghz: float,
    h_series: Any,
    alpha_series: Any,
    smooth_weight: float,
    omega_prev: float,
    sv: float,
    sh: float,
    model_contexts: tuple[OmegaTbForwardContext, ...] | None = None,
) -> Any:
    import numpy as np

    count = len(tbv)
    include_smooth = bool(np.isfinite(omega_prev) and smooth_weight > 0.0)
    residual = np.empty(2 * count + (1 if include_smooth else 0), dtype=np.float64)
    if model_contexts is None:
        for k in range(count):
            tbv_m, tbh_m = tb_forward_dual_temp(
                float(sm_ref[k]),
                float(tau[k]),
                float(h_series[k]),
                float(alpha_series[k]),
                omega_value,
                float(tc[k]),
                float(tg[k]),
                theta[k],
                clay_fraction,
                freq_ghz,
                1.0,
                None,
            )
            base = 2 * k
            residual[base] = sv * (tbv_m - float(tbv[k]))
            residual[base + 1] = sh * (tbh_m - float(tbh[k]))
    else:
        for k, model_context in enumerate(model_contexts):
            tbv_m, tbh_m = _tb_forward_dual_temp_with_context(
                float(sm_ref[k]),
                float(tau[k]),
                float(h_series[k]),
                float(alpha_series[k]),
                omega_value,
                float(tc[k]),
                float(tg[k]),
                1.0,
                model_context,
            )
            base = 2 * k
            residual[base] = sv * (tbv_m - float(tbv[k]))
            residual[base + 1] = sh * (tbh_m - float(tbh[k]))
    if include_smooth:
        residual[-1] = smooth_weight * (omega_value - omega_prev)
    return residual


def resid_halpha_single_temp(
    x: Any,
    tbv: Any,
    tbh: Any,
    ts: Any,
    tau: Any,
    sm_ref: Any,
    theta: Any,
    clay_fraction: float,
    freq_ghz: float,
    omega_low: float,
    alpha0: float,
    lambda_alpha: float,
    wv: float,
    wh: float,
    model_contexts: tuple[OmegaTbForwardContext, ...] | None = None,
) -> Any:
    import numpy as np

    h_value = float(x[0])
    alpha_value = float(x[1])
    tbv = np.asarray(tbv, dtype=np.float64)
    tbh = np.asarray(tbh, dtype=np.float64)
    ts = np.asarray(ts, dtype=np.float64)
    tau = np.asarray(tau, dtype=np.float64)
    sm_ref = np.asarray(sm_ref, dtype=np.float64)
    theta = np.asarray(theta, dtype=np.float64)
    return _resid_halpha_single_temp_prepared(
        h_value,
        alpha_value,
        tbv,
        tbh,
        ts,
        tau,
        sm_ref,
        theta,
        clay_fraction,
        freq_ghz,
        omega_low,
        alpha0,
        float(np.sqrt(lambda_alpha)),
        float(np.sqrt(wv)),
        float(np.sqrt(wh)),
        model_contexts,
    )


def resid_halpha_dual_temp(
    x: Any,
    tbv: Any,
    tbh: Any,
    tc: Any,
    tg: Any,
    tau: Any,
    sm_ref: Any,
    theta: Any,
    clay_fraction: float,
    freq_ghz: float,
    omega_low: float,
    alpha0: float,
    lambda_alpha: float,
    wv: float,
    wh: float,
    model_contexts: tuple[OmegaTbForwardContext, ...] | None = None,
) -> Any:
    import numpy as np

    h_value = float(x[0])
    alpha_value = float(x[1])
    tbv = np.asarray(tbv, dtype=np.float64)
    tbh = np.asarray(tbh, dtype=np.float64)
    tc = np.asarray(tc, dtype=np.float64)
    tg = np.asarray(tg, dtype=np.float64)
    tau = np.asarray(tau, dtype=np.float64)
    sm_ref = np.asarray(sm_ref, dtype=np.float64)
    theta = np.asarray(theta, dtype=np.float64)
    return _resid_halpha_dual_temp_prepared(
        h_value,
        alpha_value,
        tbv,
        tbh,
        tc,
        tg,
        tau,
        sm_ref,
        theta,
        clay_fraction,
        freq_ghz,
        omega_low,
        alpha0,
        float(np.sqrt(lambda_alpha)),
        float(np.sqrt(wv)),
        float(np.sqrt(wh)),
        model_contexts,
    )


def resid_omega_block_single_temp(
    omega_value: float,
    tbv: Any,
    tbh: Any,
    ts: Any,
    tau: Any,
    sm_ref: Any,
    theta: Any,
    clay_fraction: float,
    freq_ghz: float,
    h_series: Any,
    alpha_series: Any,
    lambda_smooth: float,
    omega_prev: float,
    wv: float,
    wh: float,
    model_contexts: tuple[OmegaTbForwardContext, ...] | None = None,
) -> Any:
    import numpy as np

    tbv = np.asarray(tbv, dtype=np.float64)
    tbh = np.asarray(tbh, dtype=np.float64)
    ts = np.asarray(ts, dtype=np.float64)
    tau = np.asarray(tau, dtype=np.float64)
    sm_ref = np.asarray(sm_ref, dtype=np.float64)
    theta = np.asarray(theta, dtype=np.float64)
    h_series = np.asarray(h_series, dtype=np.float64)
    alpha_series = np.asarray(alpha_series, dtype=np.float64)
    return _resid_omega_block_single_temp_prepared(
        float(omega_value),
        tbv,
        tbh,
        ts,
        tau,
        sm_ref,
        theta,
        clay_fraction,
        freq_ghz,
        h_series,
        alpha_series,
        float(np.sqrt(lambda_smooth)) if lambda_smooth > 0 else 0.0,
        float(omega_prev),
        float(np.sqrt(wv)),
        float(np.sqrt(wh)),
        model_contexts,
    )


def resid_omega_block_dual_temp(
    omega_value: float,
    tbv: Any,
    tbh: Any,
    tc: Any,
    tg: Any,
    tau: Any,
    sm_ref: Any,
    theta: Any,
    clay_fraction: float,
    freq_ghz: float,
    h_series: Any,
    alpha_series: Any,
    lambda_smooth: float,
    omega_prev: float,
    wv: float,
    wh: float,
    model_contexts: tuple[OmegaTbForwardContext, ...] | None = None,
) -> Any:
    import numpy as np

    tbv = np.asarray(tbv, dtype=np.float64)
    tbh = np.asarray(tbh, dtype=np.float64)
    tc = np.asarray(tc, dtype=np.float64)
    tg = np.asarray(tg, dtype=np.float64)
    tau = np.asarray(tau, dtype=np.float64)
    sm_ref = np.asarray(sm_ref, dtype=np.float64)
    theta = np.asarray(theta, dtype=np.float64)
    h_series = np.asarray(h_series, dtype=np.float64)
    alpha_series = np.asarray(alpha_series, dtype=np.float64)
    return _resid_omega_block_dual_temp_prepared(
        float(omega_value),
        tbv,
        tbh,
        tc,
        tg,
        tau,
        sm_ref,
        theta,
        clay_fraction,
        freq_ghz,
        h_series,
        alpha_series,
        float(np.sqrt(lambda_smooth)) if lambda_smooth > 0 else 0.0,
        float(omega_prev),
        float(np.sqrt(wv)),
        float(np.sqrt(wh)),
        model_contexts,
    )


def ddca_single_temp(
    tbv: float,
    tbh: float,
    ts: float,
    tau_ini: float,
    h_value: float,
    clay_fraction: float,
    omega_value: float,
    porosity: float,
    freq_ghz: float,
    theta_deg: float,
    alpha_value: float,
    lambda_tau: float,
    model_context: OmegaTbForwardContext | None = None,
) -> tuple[float, float]:
    from scipy.optimize import least_squares

    if model_context is None:
        model_context = _build_tb_forward_context(freq_ghz, clay_fraction, theta_deg)

    def cost_func(x: Any) -> Any:
        import numpy as np

        soil_moisture = float(x[0])
        tau_value = float(x[1])
        tbv_m, tbh_m = _tb_forward_single_temp_with_context(
            soil_moisture,
            tau_value,
            h_value,
            alpha_value,
            omega_value,
            ts,
            1.0,
            model_context,
        )
        return np.array([tbv_m - tbv, tbh_m - tbh, lambda_tau * (tau_value - tau_ini)], dtype=np.float64)

    lower_bounds = (0.02, 0.0)
    upper_bounds = (porosity, 5.0)
    result = least_squares(
        cost_func,
        x0=[0.20, tau_ini],
        bounds=(lower_bounds, upper_bounds),
        jac=lambda x: _finite_difference_jacobian(x, cost_func, lower_bounds, upper_bounds),
    )
    return float(result.x[0]), float(result.x[1])


def ddca_dual_temp(
    tbv: float,
    tbh: float,
    tc: float,
    tg: float,
    tau_ini: float,
    h_value: float,
    clay_fraction: float,
    omega_value: float,
    porosity: float,
    freq_ghz: float,
    theta_deg: float,
    alpha_value: float,
    lambda_tau: float,
    model_context: OmegaTbForwardContext | None = None,
) -> tuple[float, float]:
    from scipy.optimize import least_squares

    if model_context is None:
        model_context = _build_tb_forward_context(freq_ghz, clay_fraction, theta_deg)

    def cost_func(x: Any) -> Any:
        import numpy as np

        soil_moisture = float(x[0])
        tau_value = float(x[1])
        tbv_m, tbh_m = _tb_forward_dual_temp_with_context(
            soil_moisture,
            tau_value,
            h_value,
            alpha_value,
            omega_value,
            tc,
            tg,
            1.0,
            model_context,
        )
        return np.array([tbv_m - tbv, tbh_m - tbh, lambda_tau * (tau_value - tau_ini)], dtype=np.float64)

    lower_bounds = (0.02, 0.0)
    upper_bounds = (porosity, 5.0)
    result = least_squares(
        cost_func,
        x0=[0.20, tau_ini],
        bounds=(lower_bounds, upper_bounds),
        jac=lambda x: _finite_difference_jacobian(x, cost_func, lower_bounds, upper_bounds),
    )
    return float(result.x[0]), float(result.x[1])


def make_date_blocks(date_keys: list[str], block_days: int) -> tuple[list[list[int]], list[datetime]]:
    if not date_keys:
        return [], []
    dates = [datetime.strptime(key, "%Y%m%d") for key in date_keys]
    grouped: dict[datetime, list[int]] = {}
    block_starts: list[datetime] = []
    for idx, day in enumerate(dates):
        doy = day.timetuple().tm_yday
        block_start = datetime(day.year, 1, 1) + timedelta(days=int(block_days) * ((doy - 1) // int(block_days)))
        if block_start not in grouped:
            grouped[block_start] = []
            block_starts.append(block_start)
        grouped[block_start].append(idx)
    return [grouped[block_start] for block_start in block_starts], block_starts


def pick_lcurve_corner(lambda_list: Any, misfit: Any, roughness: Any) -> float:
    import numpy as np

    lambda_arr = np.asarray(lambda_list, dtype=np.float64).reshape(-1)
    misfit_arr = np.asarray(misfit, dtype=np.float64).reshape(-1)
    rough_arr = np.asarray(roughness, dtype=np.float64).reshape(-1)
    ok = np.isfinite(lambda_arr) & np.isfinite(misfit_arr) & np.isfinite(rough_arr) & (misfit_arr > 0) & (rough_arr > 0)
    if np.count_nonzero(ok) < 3:
        return float("nan")

    x = np.log10(misfit_arr[ok])
    y = np.log10(rough_arr[ok])
    lam = lambda_arr[ok]
    kappa = np.full(x.shape, np.nan, dtype=np.float64)
    for idx in range(1, x.size - 1):
        dx1 = x[idx] - x[idx - 1]
        dy1 = y[idx] - y[idx - 1]
        dx2 = x[idx + 1] - x[idx]
        dy2 = y[idx + 1] - y[idx]
        numerator = abs(dx1 * dy2 - dy1 * dx2)
        denominator = max(np.finfo(np.float64).eps, (dx1 * dx1 + dy1 * dy1) ** 1.5)
        kappa[idx] = numerator / denominator

    if not np.any(np.isfinite(kappa)):
        return float("nan")
    return float(lam[int(np.nanargmax(kappa))])


def qc_block_jacobian_cond(
    omega0: float,
    block_payload: dict[str, Any],
    h_series: Any,
    alpha_series: Any,
    clay_fraction: float,
    freq_ghz: float,
    temp_scheme: str,
    domega: float,
    dtau: float,
    dh: float,
    bounds_omega: tuple[float, float],
    wv: float,
    wh: float,
    omega_jacobian: Any | None = None,
) -> tuple[float, float, float]:
    import numpy as np

    use = np.asarray(block_payload["use"], dtype=np.int64).reshape(-1)
    if use.size == 0:
        return float("inf"), 0.0, 0.0

    is_dual = str(temp_scheme).upper() != "ORIG_TS"
    sv = float(np.sqrt(wv))
    sh = float(np.sqrt(wh))
    jac = np.zeros((2 * use.size, 3), dtype=np.float64)
    tau_values = np.asarray(block_payload["tau_star"], dtype=np.float64).reshape(-1)
    sm_values = np.asarray(block_payload["sm_ref"], dtype=np.float64).reshape(-1)
    ia_values = np.asarray(block_payload["ia"], dtype=np.float64).reshape(-1)
    model_contexts = block_payload.get("model_contexts")
    ts_values = None if is_dual else np.asarray(block_payload["ts"], dtype=np.float64).reshape(-1)
    tc_values = np.asarray(block_payload["tc"], dtype=np.float64).reshape(-1) if is_dual else None
    tg_values = np.asarray(block_payload["tg"], dtype=np.float64).reshape(-1) if is_dual else None
    eps = float(np.finfo(np.float64).eps)

    omega_column = None
    if omega_jacobian is not None:
        omega_column = np.asarray(omega_jacobian, dtype=np.float64).reshape(-1)
        if omega_column.size != 2 * use.size:
            omega_column = None

    op = min(max(float(omega0) + float(domega), bounds_omega[0]), bounds_omega[1])
    om = min(max(float(omega0) - float(domega), bounds_omega[0]), bounds_omega[1])
    if op == om:
        op = min(max(float(omega0) + 2.0 * float(domega), bounds_omega[0]), bounds_omega[1])
        om = min(max(float(omega0) - 2.0 * float(domega), bounds_omega[0]), bounds_omega[1])
    omega_denominator = max(eps, op - om)

    for row_index, k in enumerate(use):
        smk = float(sm_values[row_index])
        thk = float(ia_values[row_index])
        tauk = float(tau_values[row_index])
        hk = float(h_series[k])
        ak = float(alpha_series[k])

        tp = max(0.0, tauk + float(dtau))
        tm = max(0.0, tauk - float(dtau))
        if tp == tm:
            tp = max(0.0, tauk + 2.0 * float(dtau))
            tm = max(0.0, tauk - 2.0 * float(dtau))

        hp = max(np.finfo(np.float64).eps, hk + float(dh))
        hm = max(np.finfo(np.float64).eps, hk - float(dh))
        if hp == hm:
            hp = max(np.finfo(np.float64).eps, hk + 2.0 * float(dh))
            hm = max(np.finfo(np.float64).eps, hk - 2.0 * float(dh))

        if is_dual:
            tc_k = float(tc_values[row_index])
            tg_k = float(tg_values[row_index])
            model_context = None if model_contexts is None else model_contexts[row_index]
            if omega_column is None:
                if model_context is None:
                    tbv_p, tbh_p = tb_forward_dual_temp(
                        smk, tauk, hk, ak, op, tc_k, tg_k, thk, clay_fraction, freq_ghz, 1.0, None
                    )
                    tbv_m, tbh_m = tb_forward_dual_temp(
                        smk, tauk, hk, ak, om, tc_k, tg_k, thk, clay_fraction, freq_ghz, 1.0, None
                    )
                else:
                    tbv_p, tbh_p = _tb_forward_dual_temp_with_context(smk, tauk, hk, ak, op, tc_k, tg_k, 1.0, model_context)
                    tbv_m, tbh_m = _tb_forward_dual_temp_with_context(smk, tauk, hk, ak, om, tc_k, tg_k, 1.0, model_context)
                d_tb_domega_v = (tbv_p - tbv_m) / omega_denominator
                d_tb_domega_h = (tbh_p - tbh_m) / omega_denominator
            else:
                base_row = 2 * row_index
                d_tb_domega_v = float(omega_column[base_row]) / sv
                d_tb_domega_h = float(omega_column[base_row + 1]) / sh

            if model_context is None:
                tbv_p, tbh_p = tb_forward_dual_temp(smk, tp, hk, ak, omega0, tc_k, tg_k, thk, clay_fraction, freq_ghz, 1.0, None)
                tbv_m, tbh_m = tb_forward_dual_temp(smk, tm, hk, ak, omega0, tc_k, tg_k, thk, clay_fraction, freq_ghz, 1.0, None)
            else:
                tbv_p, tbh_p = _tb_forward_dual_temp_with_context(smk, tp, hk, ak, omega0, tc_k, tg_k, 1.0, model_context)
                tbv_m, tbh_m = _tb_forward_dual_temp_with_context(smk, tm, hk, ak, omega0, tc_k, tg_k, 1.0, model_context)
            d_tb_dtau_v = (tbv_p - tbv_m) / max(eps, tp - tm)
            d_tb_dtau_h = (tbh_p - tbh_m) / max(eps, tp - tm)

            if model_context is None:
                tbv_p, tbh_p = tb_forward_dual_temp(smk, tauk, hp, ak, omega0, tc_k, tg_k, thk, clay_fraction, freq_ghz, 1.0, None)
                tbv_m, tbh_m = tb_forward_dual_temp(smk, tauk, hm, ak, omega0, tc_k, tg_k, thk, clay_fraction, freq_ghz, 1.0, None)
            else:
                tbv_p, tbh_p = _tb_forward_dual_temp_with_context(smk, tauk, hp, ak, omega0, tc_k, tg_k, 1.0, model_context)
                tbv_m, tbh_m = _tb_forward_dual_temp_with_context(smk, tauk, hm, ak, omega0, tc_k, tg_k, 1.0, model_context)
            d_tb_dh_v = (tbv_p - tbv_m) / max(eps, hp - hm)
            d_tb_dh_h = (tbh_p - tbh_m) / max(eps, hp - hm)
        else:
            ts_k = float(ts_values[row_index])
            model_context = None if model_contexts is None else model_contexts[row_index]
            if omega_column is None:
                if model_context is None:
                    tbv_p, tbh_p = tb_forward_single_temp(smk, tauk, hk, ak, op, ts_k, thk, clay_fraction, freq_ghz, 1.0, None)
                    tbv_m, tbh_m = tb_forward_single_temp(smk, tauk, hk, ak, om, ts_k, thk, clay_fraction, freq_ghz, 1.0, None)
                else:
                    tbv_p, tbh_p = _tb_forward_single_temp_with_context(smk, tauk, hk, ak, op, ts_k, 1.0, model_context)
                    tbv_m, tbh_m = _tb_forward_single_temp_with_context(smk, tauk, hk, ak, om, ts_k, 1.0, model_context)
                d_tb_domega_v = (tbv_p - tbv_m) / omega_denominator
                d_tb_domega_h = (tbh_p - tbh_m) / omega_denominator
            else:
                base_row = 2 * row_index
                d_tb_domega_v = float(omega_column[base_row]) / sv
                d_tb_domega_h = float(omega_column[base_row + 1]) / sh

            if model_context is None:
                tbv_p, tbh_p = tb_forward_single_temp(smk, tp, hk, ak, omega0, ts_k, thk, clay_fraction, freq_ghz, 1.0, None)
                tbv_m, tbh_m = tb_forward_single_temp(smk, tm, hk, ak, omega0, ts_k, thk, clay_fraction, freq_ghz, 1.0, None)
            else:
                tbv_p, tbh_p = _tb_forward_single_temp_with_context(smk, tp, hk, ak, omega0, ts_k, 1.0, model_context)
                tbv_m, tbh_m = _tb_forward_single_temp_with_context(smk, tm, hk, ak, omega0, ts_k, 1.0, model_context)
            d_tb_dtau_v = (tbv_p - tbv_m) / max(eps, tp - tm)
            d_tb_dtau_h = (tbh_p - tbh_m) / max(eps, tp - tm)

            if model_context is None:
                tbv_p, tbh_p = tb_forward_single_temp(smk, tauk, hp, ak, omega0, ts_k, thk, clay_fraction, freq_ghz, 1.0, None)
                tbv_m, tbh_m = tb_forward_single_temp(smk, tauk, hm, ak, omega0, ts_k, thk, clay_fraction, freq_ghz, 1.0, None)
            else:
                tbv_p, tbh_p = _tb_forward_single_temp_with_context(smk, tauk, hp, ak, omega0, ts_k, 1.0, model_context)
                tbv_m, tbh_m = _tb_forward_single_temp_with_context(smk, tauk, hm, ak, omega0, ts_k, 1.0, model_context)
            d_tb_dh_v = (tbv_p - tbv_m) / max(eps, hp - hm)
            d_tb_dh_h = (tbh_p - tbh_m) / max(eps, hp - hm)

        base_row = 2 * row_index
        jac[base_row, 0] = sv * d_tb_domega_v
        jac[base_row, 1] = sv * d_tb_dtau_v
        jac[base_row, 2] = sv * d_tb_dh_v
        jac[base_row + 1, 0] = sh * d_tb_domega_h
        jac[base_row + 1, 1] = sh * d_tb_dtau_h
        jac[base_row + 1, 2] = sh * d_tb_dh_h

    col_scale = np.nanmax(np.abs(jac), axis=0)
    col_scale[(col_scale <= 0) | ~np.isfinite(col_scale)] = 1.0
    jac_scaled = jac / col_scale
    singular_values = np.linalg.svd(jac_scaled, compute_uv=False)
    if singular_values.size == 0:
        return float("inf"), 0.0, 0.0
    s1 = float(singular_values[0])
    smin = float(singular_values[-1])
    condk = float("inf") if smin <= 0 else float(s1 / smin)
    sratio = float(smin / max(np.finfo(np.float64).eps, s1))
    return condk, smin, sratio


def _resolve_payload_vector(payload: dict[str, Any], aliases: list[str], pixel_count: int) -> Any:
    import numpy as np

    for alias in aliases:
        if alias not in payload:
            continue
        values = np.asarray(payload[alias], dtype=np.float64).reshape(-1)
        if values.size == pixel_count:
            return values
        if values.size == 1:
            return np.full(pixel_count, float(values[0]), dtype=np.float64)
        return values
    return np.full(pixel_count, np.nan, dtype=np.float64)


def _resolve_fixed_omega_vector(payload: dict[str, Any], landcover: Any, field_config: OmegaFieldConfig) -> Any:
    import numpy as np

    landcover = np.asarray(landcover, dtype=np.float64).reshape(-1)
    pixel_count = landcover.size
    direct = _resolve_payload_vector(
        payload,
        list(field_config.omega_fixed_aliases),
        pixel_count,
    )
    if np.asarray(direct).reshape(-1).size == pixel_count and np.any(np.isfinite(direct)):
        return np.asarray(direct, dtype=np.float64).reshape(-1)

    pft_values = _resolve_payload_vector(payload, list(field_config.omega_pft_aliases), pixel_count)
    pft_values = np.asarray(pft_values, dtype=np.float64).reshape(-1)
    if pft_values.size == pixel_count:
        return pft_values

    fixed = np.full(pixel_count, np.nan, dtype=np.float64)
    if pft_values.size > 1:
        for pixel_index, class_value in enumerate(landcover):
            if not np.isfinite(class_value):
                continue
            class_index = int(round(float(class_value)))
            if 0 <= class_index < pft_values.size:
                fixed[pixel_index] = pft_values[class_index]
            elif 1 <= class_index <= pft_values.size:
                fixed[pixel_index] = pft_values[class_index - 1]

    if np.any(np.isfinite(direct)) and np.asarray(direct).reshape(-1).size == 1:
        scalar_value = float(np.asarray(direct).reshape(-1)[0])
        fixed[~np.isfinite(fixed)] = scalar_value
    return fixed


def _resolve_exp0_calib_vectors(
    payload: dict[str, Any],
    pixel_count: int,
    field_config: OmegaFieldConfig,
) -> tuple[Any, Any]:
    h_vec = _resolve_payload_vector(
        payload,
        list(field_config.exp0_h_aliases),
        pixel_count,
    )
    alpha_vec = _resolve_payload_vector(
        payload,
        list(field_config.exp0_alpha_aliases),
        pixel_count,
    )
    return h_vec, alpha_vec


def _build_empty_exp2_info(config: OmegaConfig) -> dict[str, Any]:
    import numpy as np

    lambda_list = np.asarray(config.lambda_list, dtype=np.float64).reshape(-1)
    return {
        "lambda_list": lambda_list,
        "misfit": np.full(lambda_list.shape, np.nan, dtype=np.float64),
        "roughness": np.full(lambda_list.shape, np.nan, dtype=np.float64),
        "rmse": np.full(lambda_list.shape, np.nan, dtype=np.float64),
        "lambda_star": float("nan"),
        "omega_by_lambda_block": np.full((0, lambda_list.size), np.nan, dtype=np.float64),
    }


def retrieve_omega_pixel_timeseries(
    date_keys: list[str],
    tbv: Any,
    tbh: Any,
    ts: Any,
    tc: Any,
    tg: Any,
    ia: Any,
    sm_ref: Any,
    ndvi: Any,
    sf_col: Any,
    ndvi_max_value: float,
    ndvi_min_value: float,
    albedo_value: float,
    b_value: float,
    landcover_value: float,
    clay_fraction_value: float,
    bulk_density_value: float,
    h_static_value: float,
    fixed_omega_value: float,
    exp0_h_value: float,
    exp0_alpha_value: float,
    config: OmegaConfig,
    *,
    precomputed_blocks: tuple[list[list[int]], list[datetime], list[Any]] | None = None,
    precomputed_modes: tuple[str, bool] | None = None,
) -> dict[str, Any]:
    import numpy as np
    from scipy.optimize import least_squares, minimize_scalar

    if precomputed_modes is None:
        exp_mode = str(config.exp_mode).upper()
        is_dual = str(config.temp_scheme).upper() == "DUAL"
    else:
        exp_mode, is_dual = precomputed_modes
    tbv = np.asarray(tbv, dtype=np.float64).reshape(-1)
    tbh = np.asarray(tbh, dtype=np.float64).reshape(-1)
    ts = np.asarray(ts, dtype=np.float64).reshape(-1)
    tc = np.asarray(tc, dtype=np.float64).reshape(-1) if tc is not None else np.full_like(ts, np.nan)
    tg = np.asarray(tg, dtype=np.float64).reshape(-1) if tg is not None else np.full_like(ts, np.nan)
    ia = np.asarray(ia, dtype=np.float64).reshape(-1)
    sm_ref = np.asarray(sm_ref, dtype=np.float64).reshape(-1)
    ndvi = np.asarray(ndvi, dtype=np.float64).reshape(-1)
    sf_col = np.asarray(sf_col, dtype=np.float64).reshape(-1)
    nt = tbv.size
    omega_fixed = float(fixed_omega_value) if np.isfinite(fixed_omega_value) else (
        float(config.fixed_omega_fallback) if config.fixed_omega_fallback is not None else float("nan")
    )
    if precomputed_blocks is None:
        blocks, block_start_dates = make_date_blocks(date_keys, config.block_days)
        block_index_arrays = [np.asarray(block, dtype=np.int64) for block in blocks]
    else:
        blocks, block_start_dates, block_index_arrays = precomputed_blocks
    kb = len(blocks)

    tau_star = tau_from_ndvi(
        ndvi=ndvi,
        ndvi_max=ndvi_max_value,
        ndvi_min=ndvi_min_value,
        landcover=landcover_value,
        b_param=b_value,
        stem_factor=sf_col,
        theta_deg=ia,
    )
    tau_star = np.asarray(tau_star, dtype=np.float64).reshape(-1)

    valid_tau = (
        np.isfinite(tbv)
        & np.isfinite(tbh)
        & np.isfinite(sm_ref)
        & np.isfinite(ndvi)
        & np.isfinite(ia)
        & np.isfinite(tau_star)
    )
    if is_dual:
        valid_tau = valid_tau & np.isfinite(tc) & np.isfinite(tg)
    else:
        valid_tau = valid_tau & np.isfinite(ts)
    if not np.any(valid_tau):
        return {
            "Tau_star": tau_star,
            "OMEGA": np.full(nt, np.nan, dtype=np.float64),
            "SM_RET": np.full(nt, np.nan, dtype=np.float64),
            "VOD_RET": np.full(nt, np.nan, dtype=np.float64),
            "h_star": float("nan"),
            "alpha_star": float("nan"),
            "h_series": np.full(nt, np.nan, dtype=np.float64),
            "alpha_series": np.full(nt, np.nan, dtype=np.float64),
            "valid_tau": valid_tau,
            "low_tau": np.zeros(nt, dtype=bool),
            "diag": {
                "n_use": np.zeros(kb, dtype=np.uint16),
                "algorithm": np.full(kb, "", dtype=object),
                "exitflag": np.full(kb, np.nan, dtype=np.float64),
                "iter": np.zeros(kb, dtype=np.uint16),
                "damping": np.full(kb, np.nan, dtype=np.float64),
                "final_cost": np.full(kb, np.nan, dtype=np.float64),
                "firstorderopt": np.full(kb, np.nan, dtype=np.float64),
                "Tb_RMSE_V": np.full(kb, np.nan, dtype=np.float64),
                "Tb_RMSE_H": np.full(kb, np.nan, dtype=np.float64),
                "Tb_RMSE_HV": np.full(kb, np.nan, dtype=np.float64),
                "Jopt_norm2": np.full(kb, np.nan, dtype=np.float64),
                "Jtb_norm2": np.full(kb, np.nan, dtype=np.float64),
                "Jtb_rms": np.full(kb, np.nan, dtype=np.float64),
                "Jtb_maxabs": np.full(kb, np.nan, dtype=np.float64),
                "Jtb_minabs": np.full(kb, np.nan, dtype=np.float64),
            },
            "qc": {
                "flag": np.full(kb, 1, dtype=np.uint8),
                "condK": np.full(kb, np.nan, dtype=np.float64),
                "sratio": np.full(kb, np.nan, dtype=np.float64),
            },
            "TBv_mod": np.full(nt, np.nan, dtype=np.float64),
            "TBh_mod": np.full(nt, np.nan, dtype=np.float64),
            "rV": np.full(nt, np.nan, dtype=np.float64),
            "rH": np.full(nt, np.nan, dtype=np.float64),
            "exp2": _build_empty_exp2_info(config),
            "omega_fixed_used": omega_fixed,
            "n_low_tau": 0,
            "n_use": int(np.count_nonzero(valid_tau)),
        }

    tau_min = float(np.nanmin(tau_star[valid_tau]))
    tau_max = float(np.nanmax(tau_star[valid_tau]))
    tau_thr = tau_min + config.tau_rel_frac * (tau_max - tau_min)
    low_tau = valid_tau & (tau_star <= tau_thr)
    n_low_tau = int(np.count_nonzero(low_tau))
    n_use = int(np.count_nonzero(valid_tau))
    all_model_contexts = _build_tb_forward_contexts(ia, config.freq_ghz, clay_fraction_value)
    block_valid_indices = [block_index_array[valid_tau[block_index_array]] for block_index_array in block_index_arrays]
    block_payloads: list[dict[str, Any]] = []
    for use in block_valid_indices:
        payload_entry: dict[str, Any] = {
            "use": use,
            "tbv": tbv[use],
            "tbh": tbh[use],
            "tau_star": tau_star[use],
            "sm_ref": sm_ref[use],
            "ia": ia[use],
            "model_contexts": _select_tb_forward_contexts(all_model_contexts, use),
        }
        if is_dual:
            payload_entry["tc"] = tc[use]
            payload_entry["tg"] = tg[use]
        else:
            payload_entry["ts"] = ts[use]
        block_payloads.append(payload_entry)

    h_series = np.full(nt, np.nan, dtype=np.float64)
    alpha_series = np.full(nt, np.nan, dtype=np.float64)
    h_star = float("nan")
    alpha_star = float("nan")

    def block_residual_function(
        block_payload: dict[str, Any],
        lam_smooth: float,
        omega_prev: float,
    ):
        use = block_payload["use"]
        model_contexts = block_payload["model_contexts"]
        tbv_block = block_payload["tbv"]
        tbh_block = block_payload["tbh"]
        tau_block = block_payload["tau_star"]
        sm_block = block_payload["sm_ref"]
        ia_block = block_payload["ia"]
        h_values = h_series[use]
        alpha_values = alpha_series[use]
        smooth_weight = float(np.sqrt(lam_smooth)) if lam_smooth > 0 else 0.0
        if is_dual:
            tc_block = block_payload["tc"]
            tg_block = block_payload["tg"]

            def residual_fun(omega_value: float) -> Any:
                return _resid_omega_block_dual_temp_prepared(
                    omega_value,
                    tbv_block,
                    tbh_block,
                    tc_block,
                    tg_block,
                    tau_block,
                    sm_block,
                    ia_block,
                    clay_fraction_value,
                    config.freq_ghz,
                    h_values,
                    alpha_values,
                    smooth_weight,
                    omega_prev,
                    1.0,
                    1.0,
                    model_contexts,
                )

            return residual_fun
        ts_block = block_payload["ts"]

        def residual_fun(omega_value: float) -> Any:
            return _resid_omega_block_single_temp_prepared(
                omega_value,
                tbv_block,
                tbh_block,
                ts_block,
                tau_block,
                sm_block,
                ia_block,
                clay_fraction_value,
                config.freq_ghz,
                h_values,
                alpha_values,
                smooth_weight,
                omega_prev,
                1.0,
                1.0,
                model_contexts,
            )

        return residual_fun

    def evaluate_block_fit(
        block_payload: dict[str, Any],
        omega_value: float,
    ) -> tuple[float, float, float]:
        use = block_payload["use"]
        model_contexts = block_payload["model_contexts"]
        if use.size == 0:
            return float("nan"), float("nan"), float("nan")
        res_v = np.full(use.size, np.nan, dtype=np.float64)
        res_h = np.full(use.size, np.nan, dtype=np.float64)
        for ii, kk in enumerate(use):
            if is_dual:
                tbv_mod_k, tbh_mod_k = _tb_forward_dual_temp_with_context(
                    block_payload["sm_ref"][ii],
                    block_payload["tau_star"][ii],
                    h_series[kk],
                    alpha_series[kk],
                    omega_value,
                    block_payload["tc"][ii],
                    block_payload["tg"][ii],
                    1.0,
                    model_contexts[ii],
                )
            else:
                tbv_mod_k, tbh_mod_k = _tb_forward_single_temp_with_context(
                    block_payload["sm_ref"][ii],
                    block_payload["tau_star"][ii],
                    h_series[kk],
                    alpha_series[kk],
                    omega_value,
                    block_payload["ts"][ii],
                    1.0,
                    model_contexts[ii],
                )
            res_v[ii] = block_payload["tbv"][ii] - tbv_mod_k
            res_h[ii] = block_payload["tbh"][ii] - tbh_mod_k
        rmse_v = float(np.sqrt(np.nanmean(res_v**2))) if np.any(np.isfinite(res_v)) else float("nan")
        rmse_h = float(np.sqrt(np.nanmean(res_h**2))) if np.any(np.isfinite(res_h)) else float("nan")
        rmse_hv = float(np.sqrt(np.nanmean(np.concatenate([res_v, res_h]) ** 2))) if np.any(np.isfinite(res_v) | np.isfinite(res_h)) else float("nan")
        return rmse_v, rmse_h, rmse_hv

    def solve_block_omega(
        block_payload: dict[str, Any],
        lam_smooth: float,
        omega_prev: float,
        *,
        fixed_mode: bool,
        initial_guess: float | None = None,
    ) -> dict[str, Any]:
        lower_omega = float(config.bounds_omega[0])
        upper_omega = float(config.bounds_omega[1])
        residual_fun = block_residual_function(block_payload, lam_smooth, omega_prev)
        if fixed_mode and np.isfinite(omega_fixed):
            residual = residual_fun(omega_fixed)
            return {
                "omega": float(omega_fixed),
                "residual": residual,
                "jac": np.empty((0, 0), dtype=np.float64),
                "exitflag": 9.0,
                "iterations": 0,
                "algorithm": "FIXED",
                "damping": float("nan"),
                "firstorderopt": float("nan"),
                "final_cost": float(np.sum(residual**2)),
            }

        if initial_guess is not None and np.isfinite(initial_guess):
            omega_seed = float(initial_guess)
        elif np.isfinite(omega_prev):
            omega_seed = float(omega_prev)
        else:
            omega_seed = float(config.omega0)
        omega_seed = min(max(float(omega_seed), lower_omega), upper_omega)

        def objective(omega_value: float) -> float:
            residual_value = residual_fun(omega_value)
            return float(np.dot(residual_value, residual_value))

        result = minimize_scalar(
            objective,
            bounds=(lower_omega, upper_omega),
            method="bounded",
            options={"xatol": 1e-4},
        )
        omega_hat = float(result.x if np.isfinite(result.x) else omega_seed)
        residual = residual_fun(omega_hat)
        jac = _finite_difference_scalar_jacobian(omega_hat, residual_fun, lower_omega, upper_omega)
        gradient = float(2.0 * np.dot(jac.reshape(-1), residual))
        exitflag = 1.0 if bool(result.success) else 0.0
        return {
            "omega": omega_hat,
            "residual": residual,
            "jac": jac,
            "exitflag": exitflag,
            "iterations": int(getattr(result, "nfev", 0)),
            "algorithm": "SCALAR_BOUNDED",
            "damping": float(lam_smooth),
            "firstorderopt": abs(gradient),
            "final_cost": float(np.dot(residual, residual)),
        }

    def scan_exp2_lambda() -> dict[str, Any]:
        import numpy as np

        exp2_info = _build_empty_exp2_info(config)
        if kb == 0 or np.asarray(exp2_info["lambda_list"]).size == 0:
            return exp2_info

        lambda_list = np.asarray(exp2_info["lambda_list"], dtype=np.float64)
        misfit = np.full(lambda_list.shape, np.nan, dtype=np.float64)
        roughness = np.full(lambda_list.shape, np.nan, dtype=np.float64)
        rmse = np.full(lambda_list.shape, np.nan, dtype=np.float64)
        omega_by_lambda = np.full((kb, lambda_list.size), np.nan, dtype=np.float64)
        previous_lambda_series = np.full(kb, np.nan, dtype=np.float64)

        for lam_index, lam_value in enumerate(lambda_list):
            trial_prev = float("nan")
            prev_trial_start: datetime | None = None
            trial_series = np.full(kb, np.nan, dtype=np.float64)
            residual_stack: list[np.ndarray] = []
            for block_index, block_start in enumerate(block_start_dates):
                block_payload = block_payloads[block_index]
                use = block_payload["use"]
                if use.size == 0:
                    continue
                if prev_trial_start is not None and (block_start - prev_trial_start).days > config.block_days + 2:
                    trial_prev = float("nan")
                lambda_seed = previous_lambda_series[block_index]
                block_result = solve_block_omega(
                    block_payload,
                    float(lam_value),
                    trial_prev,
                    fixed_mode=False,
                    initial_guess=lambda_seed if np.isfinite(lambda_seed) else None,
                )
                trial_series[block_index] = block_result["omega"]
                trial_prev = block_result["omega"]
                prev_trial_start = block_start
                residual_no_smooth = np.asarray(
                    block_residual_function(block_payload, 0.0, float("nan"))(trial_prev),
                    dtype=np.float64,
                ).reshape(-1)
                residual_stack.append(residual_no_smooth)
            if residual_stack:
                merged = np.concatenate(residual_stack)
                misfit[lam_index] = float(np.linalg.norm(merged))
                rmse[lam_index] = float(np.sqrt(np.nanmean(merged**2)))
            finite_trial = trial_series[np.isfinite(trial_series)]
            if finite_trial.size >= 2:
                roughness[lam_index] = float(np.linalg.norm(np.diff(finite_trial)))
            omega_by_lambda[:, lam_index] = trial_series
            previous_lambda_series = trial_series

        exp2_info["misfit"] = misfit
        exp2_info["roughness"] = roughness
        exp2_info["rmse"] = rmse
        exp2_info["lambda_star"] = pick_lcurve_corner(lambda_list, misfit, roughness)
        if not np.isfinite(exp2_info["lambda_star"]):
            exp2_info["lambda_star"] = float(config.lambda_smooth)
        exp2_info["omega_by_lambda_block"] = omega_by_lambda
        return exp2_info

    if n_low_tau >= config.kmin:
        idx = np.where(low_tau)[0]
        halpha_contexts = _select_tb_forward_contexts(all_model_contexts, idx)
        halpha_tbv = tbv[idx]
        halpha_tbh = tbh[idx]
        halpha_tau = tau_star[idx]
        halpha_sm_ref = sm_ref[idx]
        halpha_ia = ia[idx]
        halpha_sv = 1.0
        halpha_sh = 1.0
        halpha_sqrt_lambda_alpha = float(np.sqrt(config.lambda_alpha))
        h0 = min(max(h_static_value, config.bounds_h[0]), config.bounds_h[1])
        if exp_mode == "EXP1A":
            if not (np.isfinite(exp0_h_value) and np.isfinite(exp0_alpha_value)):
                raise ValueError("Exp1a requires finite Exp0 calibration values for each processed pixel")
            h_star = float(exp0_h_value)
            alpha_star = float(exp0_alpha_value)
        else:
            use_fixed_halpha = bool(config.use_fixed_omega_for_halpha) or exp_mode == "EXP1B"
            omega_low = omega_fixed if use_fixed_halpha and np.isfinite(omega_fixed) else albedo_value
            if is_dual:
                halpha_tc = tc[idx]
                halpha_tg = tg[idx]

                def halpha_fun(x: Any) -> Any:
                    return _resid_halpha_dual_temp_prepared(
                        x[0],
                        x[1],
                        halpha_tbv,
                        halpha_tbh,
                        halpha_tc,
                        halpha_tg,
                        halpha_tau,
                        halpha_sm_ref,
                        halpha_ia,
                        clay_fraction_value,
                        config.freq_ghz,
                        omega_low,
                        config.alpha0,
                        halpha_sqrt_lambda_alpha,
                        halpha_sv,
                        halpha_sh,
                        halpha_contexts,
                    )
            else:
                halpha_ts = ts[idx]

                def halpha_fun(x: Any) -> Any:
                    return _resid_halpha_single_temp_prepared(
                        x[0],
                        x[1],
                        halpha_tbv,
                        halpha_tbh,
                        halpha_ts,
                        halpha_tau,
                        halpha_sm_ref,
                        halpha_ia,
                        clay_fraction_value,
                        config.freq_ghz,
                        omega_low,
                        config.alpha0,
                        halpha_sqrt_lambda_alpha,
                        halpha_sv,
                        halpha_sh,
                        halpha_contexts,
                    )
            halpha_lower_bounds = (float(config.bounds_h[0]), float(config.bounds_alpha[0]))
            halpha_upper_bounds = (float(config.bounds_h[1]), float(config.bounds_alpha[1]))

            def halpha_jac(x: Any) -> Any:
                return _finite_difference_jacobian(x, halpha_fun, halpha_lower_bounds, halpha_upper_bounds)

            xhat = least_squares(
                halpha_fun,
                x0=[h0, config.alpha0],
                bounds=(halpha_lower_bounds, halpha_upper_bounds),
                jac=halpha_jac,
            )
            h_star = float(xhat.x[0])
            alpha_star = float(xhat.x[1])
        h_series[valid_tau] = h_star
        alpha_series[valid_tau] = alpha_star

    omega = np.full(nt, np.nan, dtype=np.float64)
    sm_ret = np.full(nt, np.nan, dtype=np.float64)
    vod_ret = np.full(nt, np.nan, dtype=np.float64)
    tbv_mod = np.full(nt, np.nan, dtype=np.float64)
    tbh_mod = np.full(nt, np.nan, dtype=np.float64)
    r_v = np.full(nt, np.nan, dtype=np.float64)
    r_h = np.full(nt, np.nan, dtype=np.float64)
    diag = {
        "n_use": np.zeros(kb, dtype=np.uint16),
        "algorithm": np.full(kb, "", dtype=object),
        "exitflag": np.full(kb, np.nan, dtype=np.float64),
        "iter": np.zeros(kb, dtype=np.uint16),
        "damping": np.full(kb, np.nan, dtype=np.float64),
        "final_cost": np.full(kb, np.nan, dtype=np.float64),
        "firstorderopt": np.full(kb, np.nan, dtype=np.float64),
        "Tb_RMSE_V": np.full(kb, np.nan, dtype=np.float64),
        "Tb_RMSE_H": np.full(kb, np.nan, dtype=np.float64),
        "Tb_RMSE_HV": np.full(kb, np.nan, dtype=np.float64),
        "Jopt_norm2": np.full(kb, np.nan, dtype=np.float64),
        "Jtb_norm2": np.full(kb, np.nan, dtype=np.float64),
        "Jtb_rms": np.full(kb, np.nan, dtype=np.float64),
        "Jtb_maxabs": np.full(kb, np.nan, dtype=np.float64),
        "Jtb_minabs": np.full(kb, np.nan, dtype=np.float64),
    }
    qc = {
        "flag": np.full(kb, 1, dtype=np.uint8),
        "condK": np.full(kb, np.nan, dtype=np.float64),
        "sratio": np.full(kb, np.nan, dtype=np.float64),
    }
    exp2_info = _build_empty_exp2_info(config)
    if np.isfinite(h_star) and np.isfinite(alpha_star):
        if exp_mode == "EXP2":
            exp2_info = scan_exp2_lambda()
        omega_prev = float("nan")
        prev_block_start: datetime | None = None
        use_fixed_blocks = bool(config.use_fixed_omega_in_blocks) or exp_mode in {"EXP1A", "EXP1B"}
        lambda_star = float(exp2_info["lambda_star"]) if np.isfinite(exp2_info["lambda_star"]) else float(config.lambda_smooth)
        for block_index, block_start in enumerate(block_start_dates):
            if prev_block_start is not None and (block_start - prev_block_start).days > config.block_days + 2:
                omega_prev = float("nan")
            block_payload = block_payloads[block_index]
            use = block_payload["use"]
            diag["n_use"][block_index] = np.uint16(use.size)
            if use.size == 0:
                prev_block_start = block_start
                continue
            lam_smooth = lambda_star if exp_mode == "EXP2" else float(config.lambda_smooth)
            block_result = solve_block_omega(
                block_payload,
                lam_smooth,
                omega_prev,
                fixed_mode=use_fixed_blocks,
            )
            om_hat = block_result["omega"]
            omega[use] = om_hat
            omega_prev = om_hat
            prev_block_start = block_start
            diag["exitflag"][block_index] = block_result["exitflag"]
            diag["algorithm"][block_index] = block_result["algorithm"]
            diag["iter"][block_index] = np.uint16(max(0, int(block_result["iterations"])))
            diag["damping"][block_index] = block_result["damping"]
            diag["final_cost"][block_index] = block_result["final_cost"]
            diag["firstorderopt"][block_index] = block_result["firstorderopt"]
            rmse_v, rmse_h, rmse_hv = evaluate_block_fit(block_payload, om_hat)
            diag["Tb_RMSE_V"][block_index] = rmse_v
            diag["Tb_RMSE_H"][block_index] = rmse_h
            diag["Tb_RMSE_HV"][block_index] = rmse_hv
            jac = np.asarray(block_result["jac"], dtype=np.float64)
            if jac.ndim == 2 and jac.size > 0:
                diag["Jopt_norm2"][block_index] = float(np.linalg.norm(jac, 2))
                m_tb = min(jac.shape[0], 2 * use.size)
                jac_tb = jac[:m_tb, :]
                diag["Jtb_norm2"][block_index] = float(np.linalg.norm(jac_tb, 2))
                diag["Jtb_rms"][block_index] = float(np.sqrt(np.nanmean(jac_tb**2)))
                diag["Jtb_maxabs"][block_index] = float(np.nanmax(np.abs(jac_tb)))
                diag["Jtb_minabs"][block_index] = float(np.nanmin(np.abs(jac_tb)))
            qc["condK"][block_index], _, qc["sratio"][block_index] = qc_block_jacobian_cond(
                om_hat,
                block_payload,
                h_series,
                alpha_series,
                clay_fraction_value,
                config.freq_ghz,
                config.temp_scheme,
                config.qc_domega,
                config.qc_dtau,
                config.qc_dh,
                config.bounds_omega,
                1.0,
                1.0,
                jac[: min(jac.shape[0], 2 * use.size), 0] if jac.ndim == 2 and jac.size > 0 else None,
            )
            qc["flag"][block_index] = np.uint8(
                not (
                    use.size >= max(1, config.kmin)
                    and np.isfinite(diag["Tb_RMSE_HV"][block_index])
                )
            )

        porosity = 1.0 - float(bulk_density_value) / 2.65
        retrieved_indices = np.flatnonzero(valid_tau & np.isfinite(omega))
        for k in retrieved_indices:
            model_context = all_model_contexts[int(k)]
            if is_dual:
                sm_ret[k], vod_ret[k] = ddca_dual_temp(
                    tbv[k],
                    tbh[k],
                    tc[k],
                    tg[k],
                    tau_star[k],
                    h_series[k],
                    clay_fraction_value,
                    omega[k],
                    porosity,
                    config.freq_ghz,
                    ia[k],
                    alpha_series[k],
                    config.lambda_tau,
                    model_context,
                )
                tbv_mod[k], tbh_mod[k] = _tb_forward_dual_temp_with_context(
                    sm_ret[k],
                    vod_ret[k],
                    h_series[k],
                    alpha_series[k],
                    omega[k],
                    tc[k],
                    tg[k],
                    1.0,
                    model_context,
                )
            else:
                sm_ret[k], vod_ret[k] = ddca_single_temp(
                    tbv[k],
                    tbh[k],
                    ts[k],
                    tau_star[k],
                    h_series[k],
                    clay_fraction_value,
                    omega[k],
                    porosity,
                    config.freq_ghz,
                    ia[k],
                    alpha_series[k],
                    config.lambda_tau,
                    model_context,
                )
                tbv_mod[k], tbh_mod[k] = _tb_forward_single_temp_with_context(
                    sm_ret[k],
                    vod_ret[k],
                    h_series[k],
                    alpha_series[k],
                    omega[k],
                    ts[k],
                    1.0,
                    model_context,
                )
            r_v[k] = tbv[k] - tbv_mod[k]
            r_h[k] = tbh[k] - tbh_mod[k]

    return {
        "Tau_star": tau_star,
        "OMEGA": omega,
        "SM_RET": sm_ret,
        "VOD_RET": vod_ret,
        "h_star": h_star,
        "alpha_star": alpha_star,
        "h_series": h_series,
        "alpha_series": alpha_series,
        "valid_tau": valid_tau,
        "low_tau": low_tau,
        "diag": diag,
        "qc": qc,
        "TBv_mod": tbv_mod,
        "TBh_mod": tbh_mod,
        "rV": r_v,
        "rH": r_h,
        "exp2": exp2_info,
        "omega_fixed_used": omega_fixed,
        "n_low_tau": n_low_tau,
        "n_use": n_use,
    }


def execute_omega_retrieval(
    payload: dict[str, Any],
    *,
    config: OmegaConfig | None = None,
    field_config: OmegaFieldConfig | None = None,
) -> dict[str, Any]:
    import numpy as np

    config = config or OmegaConfig()
    field_config = field_config or OmegaFieldConfig()
    date_keys = [str(value) for value in np.asarray(payload.get("date_keys", [])).reshape(-1).tolist()]

    tbv_mat = _coerce_timeseries_matrix(get_first_available(payload, list(field_config.tbv_mat_aliases)), "TBv_mat")
    tbh_mat = _coerce_timeseries_matrix(get_first_available(payload, list(field_config.tbh_mat_aliases)), "TBh_mat")
    ia_mat = _coerce_timeseries_matrix(get_first_available(payload, list(field_config.ia_mat_aliases)), "IA_mat")
    ts_mat = _coerce_timeseries_matrix(get_first_available(payload, list(field_config.ts_mat_aliases)), "Ts_mat")
    tc_mat = (
        _coerce_timeseries_matrix(get_first_available(payload, list(field_config.tc_mat_aliases)), "TC_mat")
        if any(alias in payload for alias in field_config.tc_mat_aliases)
        else None
    )
    tg_mat = (
        _coerce_timeseries_matrix(get_first_available(payload, list(field_config.tg_mat_aliases)), "TG_mat")
        if any(alias in payload for alias in field_config.tg_mat_aliases)
        else None
    )
    smref_mat = _coerce_timeseries_matrix(get_first_available(payload, list(field_config.smref_mat_aliases)), "SMref_mat")
    ndvi_mat = _coerce_timeseries_matrix(get_first_available(payload, list(field_config.ndvi_mat_aliases)), "NDVI_mat")
    sf_mat = _coerce_timeseries_matrix(get_first_available(payload, list(field_config.sf_mat_aliases)), "SF_mat")

    albedo = np.asarray(get_first_available(payload, list(field_config.albedo_aliases)), dtype=np.float64).reshape(-1)
    b_param = np.asarray(get_first_available(payload, list(field_config.b_aliases)), dtype=np.float64).reshape(-1)
    clay_fraction = np.asarray(get_first_available(payload, list(field_config.clay_fraction_aliases)), dtype=np.float64).reshape(-1)
    bulk_density = np.asarray(get_first_available(payload, list(field_config.bulk_density_aliases)), dtype=np.float64).reshape(-1)
    h_static = np.asarray(get_first_available(payload, list(field_config.h_static_aliases)), dtype=np.float64).reshape(-1)
    landcover = np.asarray(get_first_available(payload, list(field_config.landcover_aliases)), dtype=np.float64).reshape(-1)
    ndvi_v_max = np.asarray(get_first_available(payload, list(field_config.ndvi_v_max_aliases)), dtype=np.float64).reshape(-1)
    ndvi_v_min = np.asarray(get_first_available(payload, list(field_config.ndvi_v_min_aliases)), dtype=np.float64).reshape(-1)

    nt, npix = tbv_mat.shape
    for field_name, field_value in (
        ("TBh_mat", tbh_mat),
        ("IA_mat", ia_mat),
        ("Ts_mat", ts_mat),
        ("SMref_mat", smref_mat),
        ("NDVI_mat", ndvi_mat),
        ("SF_mat", sf_mat),
    ):
        _require_timeseries_shape(field_value, (nt, npix), field_name)
    if tc_mat is not None:
        _require_timeseries_shape(tc_mat, (nt, npix), "TC_mat")
    if tg_mat is not None:
        _require_timeseries_shape(tg_mat, (nt, npix), "TG_mat")

    blocks, block_start_dates = make_date_blocks(date_keys, config.block_days)
    kb = len(blocks)
    block_index_arrays = [np.asarray(block, dtype=np.int64) for block in blocks]
    precomputed_blocks = (blocks, block_start_dates, block_index_arrays)
    precomputed_modes = (str(config.exp_mode).upper(), str(config.temp_scheme).upper() == "DUAL")
    omega_mat = np.full((nt, npix), np.nan, dtype=np.float64)
    tau_star_mat = np.full((nt, npix), np.nan, dtype=np.float64)
    sm_ret_mat = np.full((nt, npix), np.nan, dtype=np.float64)
    vod_ret_mat = np.full((nt, npix), np.nan, dtype=np.float64)
    h_series_mat = np.full((nt, npix), np.nan, dtype=np.float64)
    alpha_series_mat = np.full((nt, npix), np.nan, dtype=np.float64)
    h_star_vec = np.full(npix, np.nan, dtype=np.float64)
    alpha_star_vec = np.full(npix, np.nan, dtype=np.float64)
    tbv_mod_mat = np.full((nt, npix), np.nan, dtype=np.float64)
    tbh_mod_mat = np.full((nt, npix), np.nan, dtype=np.float64)
    rv_mat = np.full((nt, npix), np.nan, dtype=np.float64)
    rh_mat = np.full((nt, npix), np.nan, dtype=np.float64)
    n_low_tau_vec = np.full(npix, np.nan, dtype=np.float64)
    n_use_vec = np.full(npix, np.nan, dtype=np.float64)
    omega_fixed_used_vec = np.full(npix, np.nan, dtype=np.float64)
    diag_n_use_mat = np.zeros((kb, npix), dtype=np.uint16)
    diag_exitflag_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    diag_iter_mat = np.zeros((kb, npix), dtype=np.uint16)
    diag_damping_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    diag_final_cost_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    diag_firstorderopt_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    diag_tb_rmse_v_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    diag_tb_rmse_h_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    diag_tb_rmse_hv_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    diag_jopt_norm2_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    diag_jtb_norm2_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    diag_jtb_rms_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    diag_jtb_maxabs_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    diag_jtb_minabs_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    qc_flag_mat = np.full((kb, npix), 1, dtype=np.uint8)
    qc_condk_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    qc_sratio_mat = np.full((kb, npix), np.nan, dtype=np.float64)
    fixed_omega_vec = _resolve_fixed_omega_vector(payload, landcover, field_config)
    h_exp0_vec, alpha_exp0_vec = _resolve_exp0_calib_vectors(payload, npix, field_config)
    if str(config.exp_mode).upper() == "EXP1A":
        if not np.any(np.isfinite(h_exp0_vec)) or not np.any(np.isfinite(alpha_exp0_vec)):
            raise ValueError("Exp1a requires Exp0 calibration inputs, but no finite calibration vectors were found")
    lambda_star_vec = np.full(npix, np.nan, dtype=np.float64)
    lambda_list_arr = np.asarray(config.lambda_list, dtype=np.float64).reshape(-1)
    exp2_misfit_mat = np.full((lambda_list_arr.size, npix), np.nan, dtype=np.float64)
    exp2_roughness_mat = np.full((lambda_list_arr.size, npix), np.nan, dtype=np.float64)
    exp2_rmse_mat = np.full((lambda_list_arr.size, npix), np.nan, dtype=np.float64)
    exp2_omega_by_lambda_block = (
        np.full((kb, lambda_list_arr.size, npix), np.nan, dtype=np.float64)
        if config.save_exp2_omega_by_lambda
        else None
    )

    chunk = max(1, int(config.pixel_chunk_size))
    for start in range(0, npix, chunk):
        end = min(start + chunk, npix)
        for j in range(start, end):
            result = retrieve_omega_pixel_timeseries(
                date_keys=date_keys,
                tbv=tbv_mat[:, j],
                tbh=tbh_mat[:, j],
                ts=ts_mat[:, j],
                tc=None if tc_mat is None else tc_mat[:, j],
                tg=None if tg_mat is None else tg_mat[:, j],
                ia=ia_mat[:, j],
                sm_ref=smref_mat[:, j],
                ndvi=ndvi_mat[:, j],
                sf_col=sf_mat[:, j],
                ndvi_max_value=float(ndvi_v_max[j]),
                ndvi_min_value=float(ndvi_v_min[j]),
                albedo_value=float(albedo[j]),
                b_value=float(b_param[j]),
                landcover_value=float(landcover[j]),
                clay_fraction_value=float(clay_fraction[j]),
                bulk_density_value=float(bulk_density[j]),
                h_static_value=float(h_static[j]),
                fixed_omega_value=float(fixed_omega_vec[j]) if np.isfinite(fixed_omega_vec[j]) else float("nan"),
                exp0_h_value=float(h_exp0_vec[j]) if np.isfinite(h_exp0_vec[j]) else float("nan"),
                exp0_alpha_value=float(alpha_exp0_vec[j]) if np.isfinite(alpha_exp0_vec[j]) else float("nan"),
                config=config,
                precomputed_blocks=precomputed_blocks,
                precomputed_modes=precomputed_modes,
            )
            omega_mat[:, j] = result["OMEGA"]
            tau_star_mat[:, j] = result["Tau_star"]
            sm_ret_mat[:, j] = result["SM_RET"]
            vod_ret_mat[:, j] = result["VOD_RET"]
            h_series_mat[:, j] = result["h_series"]
            alpha_series_mat[:, j] = result["alpha_series"]
            h_star_vec[j] = result["h_star"]
            alpha_star_vec[j] = result["alpha_star"]
            tbv_mod_mat[:, j] = result["TBv_mod"]
            tbh_mod_mat[:, j] = result["TBh_mod"]
            rv_mat[:, j] = result["rV"]
            rh_mat[:, j] = result["rH"]
            n_low_tau_vec[j] = result["n_low_tau"]
            n_use_vec[j] = result["n_use"]
            omega_fixed_used_vec[j] = result["omega_fixed_used"]
            diag_n_use_mat[:, j] = result["diag"]["n_use"]
            diag_exitflag_mat[:, j] = result["diag"]["exitflag"]
            diag_iter_mat[:, j] = result["diag"]["iter"]
            diag_damping_mat[:, j] = result["diag"]["damping"]
            diag_final_cost_mat[:, j] = result["diag"]["final_cost"]
            diag_firstorderopt_mat[:, j] = result["diag"]["firstorderopt"]
            diag_tb_rmse_v_mat[:, j] = result["diag"]["Tb_RMSE_V"]
            diag_tb_rmse_h_mat[:, j] = result["diag"]["Tb_RMSE_H"]
            diag_tb_rmse_hv_mat[:, j] = result["diag"]["Tb_RMSE_HV"]
            diag_jopt_norm2_mat[:, j] = result["diag"]["Jopt_norm2"]
            diag_jtb_norm2_mat[:, j] = result["diag"]["Jtb_norm2"]
            diag_jtb_rms_mat[:, j] = result["diag"]["Jtb_rms"]
            diag_jtb_maxabs_mat[:, j] = result["diag"]["Jtb_maxabs"]
            diag_jtb_minabs_mat[:, j] = result["diag"]["Jtb_minabs"]
            qc_flag_mat[:, j] = result["qc"]["flag"]
            qc_condk_mat[:, j] = result["qc"]["condK"]
            qc_sratio_mat[:, j] = result["qc"]["sratio"]
            lambda_star_vec[j] = result["exp2"]["lambda_star"]
            if lambda_list_arr.size > 0:
                exp2_misfit_mat[:, j] = np.asarray(result["exp2"]["misfit"], dtype=np.float64).reshape(-1)
                exp2_roughness_mat[:, j] = np.asarray(result["exp2"]["roughness"], dtype=np.float64).reshape(-1)
                exp2_rmse_mat[:, j] = np.asarray(result["exp2"]["rmse"], dtype=np.float64).reshape(-1)
                if exp2_omega_by_lambda_block is not None and np.asarray(result["exp2"]["omega_by_lambda_block"]).size > 0:
                    exp2_omega_by_lambda_block[:, :, j] = np.asarray(result["exp2"]["omega_by_lambda_block"], dtype=np.float64)

    return {
        "date_keys": date_keys,
        "OMEGA_mat": omega_mat,
        "Tau_star_mat": tau_star_mat,
        "SM_RET_mat": sm_ret_mat,
        "VOD_RET_mat": vod_ret_mat,
        "h_star_vec": h_star_vec,
        "alpha_star_vec": alpha_star_vec,
        "h_series_mat": h_series_mat,
        "alpha_series_mat": alpha_series_mat,
        "TBv_mod_mat": tbv_mod_mat,
        "TBh_mod_mat": tbh_mod_mat,
        "rV_mat": rv_mat,
        "rH_mat": rh_mat,
        "n_low_tau_vec": n_low_tau_vec,
        "n_use_vec": n_use_vec,
        "omega_fixed_used_vec": omega_fixed_used_vec,
        "diag_n_use_mat": diag_n_use_mat,
        "diag_exitflag_mat": diag_exitflag_mat,
        "diag_iter_mat": diag_iter_mat,
        "diag_damping_mat": diag_damping_mat,
        "diag_final_cost_mat": diag_final_cost_mat,
        "diag_firstorderopt_mat": diag_firstorderopt_mat,
        "diag_tb_rmse_v_mat": diag_tb_rmse_v_mat,
        "diag_tb_rmse_h_mat": diag_tb_rmse_h_mat,
        "diag_tb_rmse_hv_mat": diag_tb_rmse_hv_mat,
        "diag_jopt_norm2_mat": diag_jopt_norm2_mat,
        "diag_jtb_norm2_mat": diag_jtb_norm2_mat,
        "diag_jtb_rms_mat": diag_jtb_rms_mat,
        "diag_jtb_maxabs_mat": diag_jtb_maxabs_mat,
        "diag_jtb_minabs_mat": diag_jtb_minabs_mat,
        "qc_flag_mat": qc_flag_mat,
        "qc_condk_mat": qc_condk_mat,
        "qc_sratio_mat": qc_sratio_mat,
        "block_start_keys": [date_keys[block[0]] for block in blocks],
        "block_end_keys": [date_keys[block[-1]] for block in blocks],
        "lambda_list": lambda_list_arr,
        "lambda_star_vec": lambda_star_vec,
        "exp2_misfit_mat": exp2_misfit_mat,
        "exp2_roughness_mat": exp2_roughness_mat,
        "exp2_rmse_mat": exp2_rmse_mat,
        "exp2_omega_by_lambda_block": exp2_omega_by_lambda_block,
    }


def _coerce_timeseries_matrix(value: Any, field_name: str):
    import numpy as np

    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim == 0:
        return matrix.reshape(1, 1)
    if matrix.ndim == 1:
        return matrix.reshape(1, -1)
    if matrix.ndim == 2:
        return matrix
    raise ValueError(f"{field_name} must be a 1D or 2D numeric array")


def _require_timeseries_shape(matrix, expected_shape: tuple[int, int], field_name: str) -> None:
    if matrix.shape != expected_shape:
        raise ValueError(f"{field_name} shape {matrix.shape} does not match expected timeseries shape {expected_shape}")
