from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ─── 物理常量 ────────────────────────────────────────────────────────────────
# 真空介电常数 (F/m)
_VACUUM_PERMITTIVITY = 8.854e-12
# 高频极限下水介电常数（无量纲）
_WATER_HIGH_FREQ_DIELECTRIC = 4.9

# ─── Mironov 2017 介电模型系数（无量纲） ─────────────────────────────────────
# 基础介电系数
_MIRONOV_COEFF_A0 = 1.634
_MIRONOV_COEFF_A1 = -0.539
_MIRONOV_COEFF_A2 = 0.2748
_MIRONOV_COEFF_B0 = 0.03952
_MIRONOV_COEFF_B1 = -0.04038
_MIRONOV_COEFF_XMVT0 = 0.02863
_MIRONOV_COEFF_XMVT1 = 0.30673

# 束缚水介电模型系数
_MIRONOV_BOUND_WATER_EPS_INF_A0 = 79.8
_MIRONOV_BOUND_WATER_EPS_INF_A1 = -85.4
_MIRONOV_BOUND_WATER_EPS_INF_A2 = 32.7
_MIRONOV_BOUND_WATER_TAU_A0 = 1.062e-11
_MIRONOV_BOUND_WATER_TAU_A1 = 3.450e-12
_MIRONOV_BOUND_WATER_SIGMA_A0 = 0.3112
_MIRONOV_BOUND_WATER_SIGMA_A1 = 0.467

# 自由水介电模型系数
_MIRONOV_FREE_WATER_EPS_INF = 100.0
_MIRONOV_FREE_WATER_TAU = 8.5e-12
_MIRONOV_FREE_WATER_SIGMA_A0 = 0.3631
_MIRONOV_FREE_WATER_SIGMA_A1 = 1.217

# ─── NDVI-VWC 经验公式系数（Jackson 1999） ──────────────────────────────────
_VWC_NDVI_COEFF_A = 1.9134
_VWC_NDVI_COEFF_B = -0.3215

# ─── 物理量阈值 ──────────────────────────────────────────────────────────────
# VWC 最大有效值 (m³/m³)
_VWC_MAX_VALID = 30.0
# tau 最大有效值（无量纲）
_TAU_MAX_VALID = 5.0
# NDVI 有效范围（无量纲）
_NDVI_VALID_MIN = 0.0
_NDVI_VALID_MAX = 1.0
# 土地覆盖类型代码
_LANDCOVER_WATER = 0
_LANDCOVER_CROP = 10
_LANDCOVER_GRASS = 12
# 频率有效范围 (GHz)
_FREQ_GHZ_MIN = 0.1
_FREQ_GHZ_MAX = 40.0
# 黏粒含量有效范围（无量纲，0-1）
_CLAY_FRACTION_MIN = 0.0
_CLAY_FRACTION_MAX = 1.0


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
    """Fresnel 反射率 Python 内核实现。

    量纲: 输入 epsilon_real/epsilon_imag 无量纲（复介电常数实部/虚部），
    cos_theta 为入射角余弦（无量纲），sin_theta_sq 为 sin(theta)^2（无量纲）。
    输出 rh/rv 为水平/垂直极化反射率（无量纲，0-1）。
    """
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
    """Mironov 介电模型 Python 内核实现。

    量纲: 输入 soil_moisture 单位 m³/m³，zxmvt 为过渡点土壤湿度 (m³/m³)，
    znd/zkd 为干土介电参数（无量纲），znb/zkb 为束缚水介电参数（无量纲），
    znu/zku 为自由水介电参数（无量纲）。
    输出 epsilon_real/epsilon_imag 为复介电常数的实部/虚部（无量纲）。
    """
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
    """将输入数组广播到目标形状。

    量纲: 输入/输出保持原量纲。支持标量→任意形状、1D→2D (按行/列)、2D→2D 广播。
    """
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
    """Fresnel 反射率（从入射角和复介电常数计算）。

    量纲: 输入 theta_deg 单位度 (°)，epsilon 无量纲（复介电常数）。
    输出 rh/rv 为水平/垂直极化反射率（无量纲，0-1）。
    """
    return fresnel_reflectance_from_context(epsilon, build_fresnel_context(theta_deg))


def build_fresnel_context(theta_deg: float) -> FresnelContext:
    """构建 Fresnel 反射率预计算上下文。

    量纲: 输入 theta_deg 单位度 (°)。返回 FresnelContext 含 sin²/cos/cos²(θ)，均无量纲。
    """
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
    """Fresnel 反射率内核分发器（自动选择 Python 或 Numba 实现）。"""
    return _FRESNEL_REFLECTANCE_KERNEL_IMPL(
        epsilon_real,
        epsilon_imag,
        cos_theta,
        sin_theta_sq,
    )


def fresnel_reflectance_from_context(epsilon: complex, context: FresnelContext) -> tuple[float, float]:
    """Fresnel 反射率（从预计算 context 计算）。

    量纲: 输入 epsilon 无量纲，context 含入射角三角函数（无量纲）。
    输出 rh/rv 无量纲 (0-1)。
    """
    return _fresnel_reflectance_kernel(
        float(epsilon.real),
        float(epsilon.imag),
        context.cos_theta,
        context.sin_theta_sq,
    )


def mironov_dielectric(freq_ghz: float, soil_moisture: float, clay_fraction: float) -> complex:
    """Mironov 介电模型（直接计算）。

    量纲: 输入 freq_ghz 单位 GHz，soil_moisture 单位 m³/m³，clay_fraction 无量纲 (0-1)。
    返回复介电常数（无量纲）。
    """
    return mironov_dielectric_from_context(soil_moisture, build_mironov_context(freq_ghz, clay_fraction))


def build_mironov_context(freq_ghz: float, clay_fraction: float) -> MironovContext:
    """构建 Mironov 介电模型预计算上下文。

    量纲: freq_ghz 单位 GHz，clay_fraction 无量纲 (0-1)。
    返回 MironovContext，所有字段均为无量纲介电参数。

    物理约束: clay_fraction ∈ [0, 1]，freq_ghz ∈ [0.1, 40] GHz。
    超出范围抛出 ValueError。
    """
    import math

    if not (_CLAY_FRACTION_MIN <= clay_fraction <= _CLAY_FRACTION_MAX):
        raise ValueError(
            f"clay_fraction must be in [{_CLAY_FRACTION_MIN}, {_CLAY_FRACTION_MAX}], got {clay_fraction}"
        )
    if not (_FREQ_GHZ_MIN <= freq_ghz <= _FREQ_GHZ_MAX):
        raise ValueError(
            f"freq_ghz must be in [{_FREQ_GHZ_MIN}, {_FREQ_GHZ_MAX}], got {freq_ghz}"
        )

    freq_hz = freq_ghz * 1e9

    znd = _MIRONOV_COEFF_A0 + _MIRONOV_COEFF_A1 * clay_fraction + _MIRONOV_COEFF_A2 * clay_fraction**2
    zkd = _MIRONOV_COEFF_B0 + _MIRONOV_COEFF_B1 * clay_fraction
    zxmvt = _MIRONOV_COEFF_XMVT0 + _MIRONOV_COEFF_XMVT1 * clay_fraction

    zep0b = (
        _MIRONOV_BOUND_WATER_EPS_INF_A0
        + _MIRONOV_BOUND_WATER_EPS_INF_A1 * clay_fraction
        + _MIRONOV_BOUND_WATER_EPS_INF_A2 * clay_fraction**2
    )
    ztaub = _MIRONOV_BOUND_WATER_TAU_A0 + _MIRONOV_BOUND_WATER_TAU_A1 * clay_fraction
    zsigmab = _MIRONOV_BOUND_WATER_SIGMA_A0 + _MIRONOV_BOUND_WATER_SIGMA_A1 * clay_fraction

    zep0u = _MIRONOV_FREE_WATER_EPS_INF
    ztauu = _MIRONOV_FREE_WATER_TAU
    zsigmau = _MIRONOV_FREE_WATER_SIGMA_A0 + _MIRONOV_FREE_WATER_SIGMA_A1 * clay_fraction

    cxb = (zep0b - _WATER_HIGH_FREQ_DIELECTRIC) / (1 + (2 * math.pi * freq_hz * ztaub) ** 2)
    epwbx = _WATER_HIGH_FREQ_DIELECTRIC + cxb
    epwby = cxb * (2 * math.pi * freq_hz * ztaub) + zsigmab / (2 * math.pi * _VACUUM_PERMITTIVITY * freq_hz)

    cxu = (zep0u - _WATER_HIGH_FREQ_DIELECTRIC) / (1 + (2 * math.pi * freq_hz * ztauu) ** 2)
    epwux = _WATER_HIGH_FREQ_DIELECTRIC + cxu
    epwuy = cxu * (2 * math.pi * freq_hz * ztauu) + zsigmau / (2 * math.pi * _VACUUM_PERMITTIVITY * freq_hz)

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
    """Mironov 介电模型内核实现。

    量纲: 输入 soil_moisture 单位 m³/m³（体积含水量），zxmvt/znd/zkd/znb/zkb/znu/zku
    为 MironovContext 预计算的无量纲介电系数。输出 (epsilon_real, epsilon_imag) 为
    复介电常数的实部和虚部（无量纲）。
    """
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
    """基于预计算上下文计算 Mironov 复介电常数。

    量纲: 输入 soil_moisture 单位 m³/m³（体积含水量），context 为 build_mironov_context
    返回的 MironovContext（无量纲系数）。返回复介电常数（无量纲）。
    """
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
    """基于 NDVI 计算植被水分含量 (VWC)。

    量纲: 输入 ndvi/ndvi_max/ndvi_min 无量纲 (0-1)，landcover 为 IGBP 类型代码（整数），
    stem_factor 单位 kg/m²。返回 vwc 单位 kg/m²。

    算法: Jackson 1999 经验公式，分为作物/草地和其他两类。
    """
    import numpy as np

    ndvi = np.array(ndvi, dtype=np.float64, copy=True)
    target_shape = ndvi.shape
    ndvi_max = _broadcast_to_shape(ndvi_max, target_shape, name="ndvi_max", dtype=np.float64)
    ndvi_min = _broadcast_to_shape(ndvi_min, target_shape, name="ndvi_min", dtype=np.float64)
    landcover = _broadcast_to_shape(landcover, target_shape, name="landcover")
    stem_factor = _broadcast_to_shape(stem_factor, target_shape, name="stem_factor", dtype=np.float64)

    ndvi[(ndvi < _NDVI_VALID_MIN) | (ndvi > _NDVI_VALID_MAX)] = np.nan
    vwc1 = _VWC_NDVI_COEFF_A * (ndvi**2) + _VWC_NDVI_COEFF_B * ndvi
    vwc2 = np.zeros_like(ndvi, dtype=np.float64)

    mask_crop_grass = (landcover == _LANDCOVER_CROP) | (landcover == _LANDCOVER_GRASS)
    mask_water = landcover == _LANDCOVER_WATER
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
    vwc[(vwc > _VWC_MAX_VALID) | np.isinf(vwc)] = np.nan
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
    """基于 NDVI 计算植被光学厚度 (tau)。

    量纲: 输入 ndvi/ndvi_max/ndvi_min 无量纲 (0-1)，landcover 为 IGBP 类型代码，
    b_param 无量纲（经验系数），stem_factor 单位 kg/m²，theta_deg 单位度 (°)。
    返回 tau 无量纲（光学厚度）。
    """
    import numpy as np

    vwc = vwc_from_ndvi(ndvi, ndvi_max, ndvi_min, landcover, stem_factor)
    target_shape = np.asarray(vwc).shape
    theta_deg = _broadcast_to_shape(theta_deg, target_shape, name="theta_deg", dtype=np.float64)
    b_param = _broadcast_to_shape(b_param, target_shape, name="b_param", dtype=np.float64)
    tau = b_param * vwc / np.cos(np.radians(theta_deg))
    tau[(tau < 0) | (tau > _TAU_MAX_VALID)] = np.nan
    return tau
