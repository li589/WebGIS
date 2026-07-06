from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MironovContext:
    znd: float
    zkd: float
    zxmvt: float
    znb: float
    zkb: float
    znu: float
    zku: float


@dataclass(frozen=True, slots=True)
class FresnelContext:
    sin_theta_sq: float
    cos_theta: float
    cos_theta_sq: float


def _fresnel_reflectance_kernel_py(
    epsilon_real: float,
    epsilon_imag: float,
    cos_theta: float,
    sin_theta_sq: float,
) -> tuple[float, float]:
    import cmath

    epsilon = complex(epsilon_real, epsilon_imag)
    root_term = cmath.sqrt(epsilon - sin_theta_sq)

    num_h = cos_theta - root_term
    den_h = cos_theta + root_term
    num_h_abs2 = num_h.real * num_h.real + num_h.imag * num_h.imag
    den_h_abs2 = den_h.real * den_h.real + den_h.imag * den_h.imag
    rh = num_h_abs2 / den_h_abs2

    epsilon_cos = epsilon * cos_theta
    num_v = epsilon_cos - root_term
    den_v = epsilon_cos + root_term
    num_v_abs2 = num_v.real * num_v.real + num_v.imag * num_v.imag
    den_v_abs2 = den_v.real * den_v.real + den_v.imag * den_v.imag
    rv = num_v_abs2 / den_v_abs2
    return float(rh), float(rv)


def _mironov_dielectric_kernel_py(
    soil_moisture: float,
    zxmvt: float,
    znd: float,
    zkd: float,
    znb: float,
    zkb: float,
    znu: float,
    zku: float,
) -> tuple[float, float]:
    if soil_moisture >= zxmvt:
        delta_moisture = soil_moisture - zxmvt
        znm = znd + (znb - 1.0) * zxmvt + (znu - 1.0) * delta_moisture
        zkm = zkd + zkb * zxmvt + zku * delta_moisture
    else:
        znm = znd + (znb - 1.0) * soil_moisture
        zkm = zkd + zkb * soil_moisture

    epsilon_real = znm * znm - zkm * zkm
    epsilon_imag = 2 * znm * zkm
    return epsilon_real, epsilon_imag


def _load_scalar_kernel_impls(
    *,
    force_python: bool = False,
) -> tuple[Any, Any, bool]:
    if force_python:
        return _mironov_dielectric_kernel_py, _fresnel_reflectance_kernel_py, False

    try:
        import numpy as np
        from numba import njit

        @njit(cache=True)
        def _mironov_dielectric_kernel_numba(
            soil_moisture: float,
            zxmvt: float,
            znd: float,
            zkd: float,
            znb: float,
            zkb: float,
            znu: float,
            zku: float,
        ) -> tuple[float, float]:
            if soil_moisture >= zxmvt:
                delta_moisture = soil_moisture - zxmvt
                znm = znd + (znb - 1.0) * zxmvt + (znu - 1.0) * delta_moisture
                zkm = zkd + zkb * zxmvt + zku * delta_moisture
            else:
                znm = znd + (znb - 1.0) * soil_moisture
                zkm = zkd + zkb * soil_moisture

            epsilon_real = znm * znm - zkm * zkm
            epsilon_imag = 2 * znm * zkm
            return epsilon_real, epsilon_imag

        @njit(cache=True)
        def _fresnel_reflectance_kernel_numba(
            epsilon_real: float,
            epsilon_imag: float,
            cos_theta: float,
            sin_theta_sq: float,
        ) -> tuple[float, float]:
            epsilon = complex(epsilon_real, epsilon_imag)
            root_term = np.sqrt(epsilon - sin_theta_sq)

            num_h = cos_theta - root_term
            den_h = cos_theta + root_term
            num_h_abs2 = num_h.real * num_h.real + num_h.imag * num_h.imag
            den_h_abs2 = den_h.real * den_h.real + den_h.imag * den_h.imag
            rh = num_h_abs2 / den_h_abs2

            epsilon_cos = epsilon * cos_theta
            num_v = epsilon_cos - root_term
            den_v = epsilon_cos + root_term
            num_v_abs2 = num_v.real * num_v.real + num_v.imag * num_v.imag
            den_v_abs2 = den_v.real * den_v.real + den_v.imag * den_v.imag
            rv = num_v_abs2 / den_v_abs2
            return rh, rv

        # Compile eagerly so unsupported complex operations fall back immediately.
        _mironov_dielectric_kernel_numba(0.12, 0.08, 1.4, 0.03, 4.0, 0.8, 6.0, 1.2)
        _fresnel_reflectance_kernel_numba(12.0, 1.2, 0.7, 0.5)
        return _mironov_dielectric_kernel_numba, _fresnel_reflectance_kernel_numba, True
    except Exception:
        return _mironov_dielectric_kernel_py, _fresnel_reflectance_kernel_py, False


_MIRONOV_DIELECTRIC_KERNEL_IMPL, _FRESNEL_REFLECTANCE_KERNEL_IMPL, _SCALAR_KERNELS_USE_NUMBA = (
    _load_scalar_kernel_impls()
)


def _broadcast_to_shape(value: Any, target_shape: tuple[int, ...], *, name: str, dtype: Any | None = None) -> Any:
    import numpy as np

    array = np.asarray(value, dtype=dtype)
    if array.shape == target_shape:
        return array
    if array.ndim == 0:
        return np.full(target_shape, array.item(), dtype=array.dtype)
    if len(target_shape) == 1:
        flat = array.reshape(-1)
        if flat.size == target_shape[0]:
            return flat.reshape(target_shape)
    if len(target_shape) == 2:
        nt, npix = target_shape
        if array.ndim == 1:
            if array.size == npix:
                return np.broadcast_to(array.reshape(1, npix), target_shape)
            if array.size == nt:
                return np.broadcast_to(array.reshape(nt, 1), target_shape)
            if array.size == nt * npix:
                return array.reshape(target_shape)
        if array.ndim == 2:
            try:
                return np.broadcast_to(array, target_shape)
            except ValueError:
                pass
    try:
        return np.broadcast_to(array, target_shape)
    except ValueError as exc:
        raise ValueError(f"Cannot broadcast {name} from shape {array.shape} to {target_shape}") from exc


def fresnel_reflectance(theta_deg: float, epsilon: complex) -> tuple[float, float]:
    return fresnel_reflectance_from_context(epsilon, build_fresnel_context(theta_deg))


def build_fresnel_context(theta_deg: float) -> FresnelContext:
    import math

    sin_theta = math.sin(math.radians(theta_deg))
    cos_theta = math.cos(math.radians(theta_deg))
    return FresnelContext(
        sin_theta_sq=sin_theta * sin_theta,
        cos_theta=cos_theta,
        cos_theta_sq=cos_theta * cos_theta,
    )


def _fresnel_reflectance_kernel(
    epsilon_real: float,
    epsilon_imag: float,
    cos_theta: float,
    sin_theta_sq: float,
) -> tuple[float, float]:
    return _FRESNEL_REFLECTANCE_KERNEL_IMPL(
        epsilon_real,
        epsilon_imag,
        cos_theta,
        sin_theta_sq,
    )


def fresnel_reflectance_from_context(epsilon: complex, context: FresnelContext) -> tuple[float, float]:
    return _fresnel_reflectance_kernel(
        float(epsilon.real),
        float(epsilon.imag),
        context.cos_theta,
        context.sin_theta_sq,
    )


def mironov_dielectric(freq_ghz: float, soil_moisture: float, clay_fraction: float) -> complex:
    return mironov_dielectric_from_context(soil_moisture, build_mironov_context(freq_ghz, clay_fraction))


def build_mironov_context(freq_ghz: float, clay_fraction: float) -> MironovContext:
    import math

    if not (0.0 <= clay_fraction <= 1.0):
        raise ValueError(f"clay_fraction must be in [0.0, 1.0], got {clay_fraction}")

    eps_0 = 8.854e-12
    eps_winf = 4.9
    freq_hz = freq_ghz * 1e9

    znd = 1.634 - 0.539 * clay_fraction + 0.2748 * clay_fraction**2
    zkd = 0.03952 - 0.04038 * clay_fraction
    zxmvt = 0.02863 + 0.30673 * clay_fraction

    zep0b = 79.8 - 85.4 * clay_fraction + 32.7 * clay_fraction**2
    ztaub = 1.062e-11 + 3.450e-12 * clay_fraction
    zsigmab = 0.3112 + 0.467 * clay_fraction

    zep0u = 100.0
    ztauu = 8.5e-12
    zsigmau = 0.3631 + 1.217 * clay_fraction

    cxb = (zep0b - eps_winf) / (1 + (2 * math.pi * freq_hz * ztaub) ** 2)
    epwbx = eps_winf + cxb
    epwby = cxb * (2 * math.pi * freq_hz * ztaub) + zsigmab / (2 * math.pi * eps_0 * freq_hz)

    cxu = (zep0u - eps_winf) / (1 + (2 * math.pi * freq_hz * ztauu) ** 2)
    epwux = eps_winf + cxu
    epwuy = cxu * (2 * math.pi * freq_hz * ztauu) + zsigmau / (2 * math.pi * eps_0 * freq_hz)

    znb = math.sqrt((math.sqrt(epwbx**2 + epwby**2) + epwbx) / 2)
    zkb = math.sqrt((math.sqrt(epwbx**2 + epwby**2) - epwbx) / 2)
    znu = math.sqrt((math.sqrt(epwux**2 + epwuy**2) + epwux) / 2)
    zku = math.sqrt((math.sqrt(epwux**2 + epwuy**2) - epwux) / 2)

    return MironovContext(
        znd=znd,
        zkd=zkd,
        zxmvt=zxmvt,
        znb=znb,
        zkb=zkb,
        znu=znu,
        zku=zku,
    )


def _mironov_dielectric_kernel(
    soil_moisture: float,
    zxmvt: float,
    znd: float,
    zkd: float,
    znb: float,
    zkb: float,
    znu: float,
    zku: float,
) -> tuple[float, float]:
    return _MIRONOV_DIELECTRIC_KERNEL_IMPL(
        soil_moisture,
        zxmvt,
        znd,
        zkd,
        znb,
        zkb,
        znu,
        zku,
    )


def mironov_dielectric_from_context(soil_moisture: float, context: MironovContext) -> complex:
    epsilon_real, epsilon_imag = _mironov_dielectric_kernel(
        soil_moisture,
        context.zxmvt,
        context.znd,
        context.zkd,
        context.znb,
        context.zkb,
        context.znu,
        context.zku,
    )
    return complex(epsilon_real, epsilon_imag)


def vwc_from_ndvi(
    ndvi: Any,
    ndvi_max: Any,
    ndvi_min: Any,
    landcover: Any,
    stem_factor: Any,
) -> Any:
    import numpy as np

    ndvi = np.array(ndvi, dtype=np.float64, copy=True)
    target_shape = ndvi.shape
    ndvi_max = _broadcast_to_shape(ndvi_max, target_shape, name="ndvi_max", dtype=np.float64)
    ndvi_min = _broadcast_to_shape(ndvi_min, target_shape, name="ndvi_min", dtype=np.float64)
    landcover = _broadcast_to_shape(landcover, target_shape, name="landcover")
    stem_factor = _broadcast_to_shape(stem_factor, target_shape, name="stem_factor", dtype=np.float64)

    ndvi[(ndvi < 0) | (ndvi > 1)] = np.nan
    vwc1 = 1.9134 * (ndvi**2) - 0.3215 * ndvi
    vwc2 = np.zeros_like(ndvi, dtype=np.float64)

    mask_crop_grass = (landcover == 10) | (landcover == 12)
    mask_water = landcover == 0
    mask_other = ~mask_crop_grass & ~mask_water

    vwc2[mask_crop_grass] = (
        stem_factor[mask_crop_grass]
        / (1 - ndvi_min[mask_crop_grass])
        * (ndvi[mask_crop_grass] - ndvi_min[mask_crop_grass])
    )
    vwc2[mask_water] = np.nan
    vwc2[mask_other] = (
        stem_factor[mask_other]
        / (1 - ndvi_min[mask_other])
        * (ndvi_max[mask_other] - ndvi_min[mask_other])
    )

    vwc = vwc1 + vwc2
    vwc[(vwc > 30) | np.isinf(vwc)] = np.nan
    return vwc


def tau_from_ndvi(
    ndvi: Any,
    ndvi_max: Any,
    ndvi_min: Any,
    landcover: Any,
    b_param: Any,
    stem_factor: Any,
    theta_deg: Any,
) -> Any:
    import numpy as np

    vwc = vwc_from_ndvi(ndvi, ndvi_max, ndvi_min, landcover, stem_factor)
    target_shape = np.asarray(vwc).shape
    theta_deg = _broadcast_to_shape(theta_deg, target_shape, name="theta_deg", dtype=np.float64)
    b_param = _broadcast_to_shape(b_param, target_shape, name="b_param", dtype=np.float64)
    tau = b_param * vwc / np.cos(np.radians(theta_deg))
    tau[(tau < 0) | (tau > 5)] = np.nan
    return tau
