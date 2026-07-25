r"""SF 块反演算法核心逻辑（从 Matlab ``omega_sf_fenkuai.m`` 迁移）。

本模块实现 SF（茎干因子）块反演与 OMEGA 识别算法，复用已有
``physics`` / ``inversion`` / ``block_inversion`` / ``ndvi`` 模块。

算法流水线：
    1. 构建时间序列（TB / SMAP / NDVI / 辅助数据交集）
    2. 按 8 天划分时间块（``make_viirs8_blocks``）
    3. 逐日 SF 倒推（``build_sf_row_daily``）或加载静态 SF
    4. 逐块反演：低 τ 样本 → h/alpha 反演 → OMEGA 识别 → 逐日 SM/VOD
    5. 汇总输出：OMEGA_pft / OMEGA_pixel + 逐日 SM / VOD

关键复用：
    - ``physics.vwc_from_ndvi`` — VWC 计算
    - ``physics.tau_from_ndvi`` — tau 计算
    - ``inversion.build_tb_model_context`` — TB 模型上下文缓存

核心差异（与 inversion.py 的 DDCA/Retrieve_DH 区别）：
    - Q = max(alpha * h, 0)（alpha 为可优化变量），而非固定 Q = 0.1771 * h
    - h/alpha 联合优化（所有低 τ 样本同时拟合），而非逐样本反演 h
    - OMEGA 块识别使用逐样本 h/alpha + 时间平滑正则化
    - DDCA 初始猜测 [0.20, Tau_ini]，而非 [0.2, 0.5]

量纲约定：
    温度（Ts/TBv/TBh）单位 K；freq_ghz 单位 GHz；theta_deg 单位度 (°)；
    soil_moisture 单位 m³/m³；omega/h/alpha/tau/vod 无量纲。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from algorithms.inversion import (
    TbModelContext,
    _finite_difference_jacobian,
    build_tb_model_context,
)
from algorithms.physics import tau_from_ndvi

logger = logging.getLogger(__name__)

# ─── 常量 ────────────────────────────────────────────────────────────────────

# IGBP 土地覆盖类型代码
# 与 Matlab VWC.m/Tau.m 一致：10=Grasslands, 12=Croplands, 0=Water
# （本数据集 IGBP_9km_12.mat 使用 0 表示水体，非标准 IGBP 的 17）
_LANDCOVER_CROP = 12
_LANDCOVER_GRASS = 10
_LANDCOVER_WATER = 0

# VWC 叶片水分经验系数（Jackson 1999）
# 注意：B = -0.3215（负值），与 physics.py 和 Matlab VWC.m/Tau.m 一致
# 公式：vwc_leaf = A * ndvi² + B * ndvi = 1.9134*ndvi² - 0.3215*ndvi
_VWC_NDVI_COEFF_A = 1.9134
_VWC_NDVI_COEFF_B = -0.3215

# NDVI 有效范围
# 与 Matlab VWC.m L11 / Tau.m L12 一致：NDVI(NDVI<0 | NDVI>1) = nan
_NDVI_VALID_MIN = 0.0
_NDVI_VALID_MAX = 1.0

# 默认频率（GHz）
_FREQ_FY = 10.65
_FREQ_SMAP = 1.41


# ─── 配置 ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class OmegaSfConfig:
    """omega_sf_fenkuai 配置，镜像 Matlab CFG 结构。

    所有字段对应 Matlab ``omega_sf_fenkuai.m`` 中的 CFG 参数。
    """

    # ── 数据源开关 ──
    tb_source: str = "FY"  # "FY" | "SMAP"
    sm_source: str = "SMAP"  # "SMAP" | "ISMN" | "DDCA"
    fy_platform: str = "3D"  # "3D" | "3B"
    temp_scheme: str = "ORIG_TS"  # "ORIG_TS" | "DUAL"
    run_domain: str = "GLOBAL"  # "ISMN" | "GLOBAL"

    # ── SF 方案 ──
    sf_mode: str = "INVERTED_DAILY"  # "STATIC" | "INVERTED_DAILY"
    sf_invert_mode: str = "POINT1"  # "POINT1" | "NDVIMIN"

    # ── NDVI 方案 ──
    ndvi_mode: str = "DOY_CLIM"  # "DAILY_FILE" | "DOY_CLIM"
    tau_vwc2_mode: str = "POINT1"  # "NDVIMIN" | "POINT1"

    # ── FY3B→FY3D 匹配 ──
    match_enable: bool = True
    match_method: str = "bias"  # "none" | "bias" | "cdf"
    match_start_date: str = "20190101"
    match_end_date: str = "20191231"
    match_min_valid_n: int = 20

    # ── OMEGA 固定模式 ──
    omega_fixed_mode: str = "PFT"  # "PFT" | "PIXEL"

    # ── SMAP h/Q 模式 ──
    smap_hq_mode: str = "LOWTAU"  # "LOWTAU" | "YEARFILE_HQFIX"

    # ── 反演参数 ──
    block_days: int = 8
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

    # ── 频率 ──
    @property
    def freq_ghz(self) -> float:
        """根据 tb_source 自动选择频率。"""
        return _FREQ_FY if self.tb_source.upper() == "FY" else _FREQ_SMAP

    # ── 并行 ──
    enable_parallel: bool = True
    pixel_chunk_size: int = 200000

    # ── 日期范围 ──
    start_date: str = "20250101"
    end_date: str = "20251231"

    # ── QC ──
    qc_enable: bool = True
    qc_nmin: int = 3

    # ── 输出 ──
    out_root: str = ""
    out_mat: str = ""
    out_aux: str = ""
    out_block: str = ""

    # ── 打印节奏 ──
    print_every_days: int = 20

    @staticmethod
    def from_params(params: dict[str, Any]) -> OmegaSfConfig:
        """从 algorithm_params 字典构建配置。"""
        known_fields = {f.name for f in OmegaSfConfig.__dataclass_fields__.values()}
        filtered = {k: v for k, v in params.items() if k in known_fields}
        return OmegaSfConfig(**filtered)


# ─── SF 倒推 ─────────────────────────────────────────────────────────────────


def build_sf_row_daily(
    vwc_row: np.ndarray,
    ndvi_clim_row: np.ndarray,
    ndvi_clim_max_row: np.ndarray,
    ndvi_clim_min_row: np.ndarray,
    cls_row: np.ndarray,
    mode_sf: str = "POINT1",
) -> np.ndarray:
    """逐日 SF（茎干因子）倒推。

    从 SMAP 观测的 VWC 和 NDVI 气候态反推茎干因子 SF。

    对应 Matlab ``build_sf_row_daily`` (L3378-3436)。

    算法：
        vwc_leaf = 1.9134 * ndvi_clim^2 - 0.3215 * ndvi_clim
        vwc_wood = vwc - vwc_leaf
        SF = vwc_wood / den

    其中 den 取决于 mode_sf：
        POINT1:  crop/grass → (ndvi_clim - 0.1) / 0.9
                 other      → (ndvi_clim_max - 0.1) / 0.9
        NDVIMIN: crop/grass → (ndvi_clim - ndvi_clim_min) / (1 - ndvi_clim_min)
                 other      → (ndvi_clim_max - ndvi_clim_min) / (1 - ndvi_clim_min)

    Args:
        vwc_row: 当天 SMAP VWC（1D 数组，每像元一个值）
        ndvi_clim_row: 当天 DOY 的 NDVI 气候态
        ndvi_clim_max_row: NDVI 气候态年最大值
        ndvi_clim_min_row: NDVI 气候态年最小值
        cls_row: IGBP 土地覆盖类型
        mode_sf: SF 倒推模式（"POINT1" 或 "NDVIMIN"）

    Returns:
        SF 行（1D 数组，与输入同长度），无效像元为 NaN
    """
    vwc = np.asarray(vwc_row, dtype=np.float64).ravel()
    ndvi_clim = np.asarray(ndvi_clim_row, dtype=np.float64).ravel()
    ndvi_max = np.asarray(ndvi_clim_max_row, dtype=np.float64).ravel()
    ndvi_min = np.asarray(ndvi_clim_min_row, dtype=np.float64).ravel()
    cls = np.asarray(cls_row, dtype=np.float64).ravel()

    sf = np.full_like(vwc, np.nan)

    # 叶片项：始终用当天 NDVI_clim
    # 公式: vwc_leaf = A*ndvi² + B*ndvi，B=-0.3215（与 physics.py / Matlab VWC.m 一致）
    vwc_leaf = _VWC_NDVI_COEFF_A * (ndvi_clim**2) + _VWC_NDVI_COEFF_B * ndvi_clim
    vwc_wood = vwc - vwc_leaf

    is_crop_grass = (cls == _LANDCOVER_CROP) | (cls == _LANDCOVER_GRASS)
    is_other = ~is_crop_grass & (cls != 0)

    den = np.full_like(vwc, np.nan)
    mode = mode_sf.upper()

    if mode == "POINT1":
        den[is_crop_grass] = (ndvi_clim[is_crop_grass] - 0.1) / 0.9
        den[is_other] = (ndvi_max[is_other] - 0.1) / 0.9
    elif mode == "NDVIMIN":
        with np.errstate(divide="ignore", invalid="ignore"):
            den_cg = 1.0 - ndvi_min[is_crop_grass]
            den[is_crop_grass] = np.where(
                np.abs(den_cg) >= 1e-6,
                (ndvi_clim[is_crop_grass] - ndvi_min[is_crop_grass]) / den_cg,
                np.nan,
            )
            den_ot = 1.0 - ndvi_min[is_other]
            den[is_other] = np.where(
                np.abs(den_ot) >= 1e-6,
                (ndvi_max[is_other] - ndvi_min[is_other]) / den_ot,
                np.nan,
            )
    else:
        raise ValueError(f"未知 SF_INVERT_MODE={mode_sf}")

    sf = vwc_wood / den

    # QC：标记无效值
    bad = (
        ~np.isfinite(vwc)
        | ~np.isfinite(ndvi_clim)
        | ~np.isfinite(ndvi_max)
        | ~np.isfinite(ndvi_min)
        | ~np.isfinite(den)
        | (den <= 0)
        | ~np.isfinite(sf)
        | (sf < 0)
        | (cls == 0)
    )
    sf[bad] = np.nan

    return sf


# ─── 8 天块结构 ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BlockStructure:
    """8 天块结构。"""

    starts: list[datetime]  # 每块起始日期
    ends: list[datetime]  # 每块结束日期
    indices: list[np.ndarray]  # 每块在时间序列中的索引


def make_viirs8_blocks(tvec: Sequence[datetime]) -> BlockStructure:
    """按 8 天划分时间块。

    对应 Matlab ``make_viirs8_blocks`` (L2813-2831)。

    算法：以每年 1 月 1 日为起点，每 8 天一块，跨年重置。
    不足 8 天的末尾块也保留。

    Args:
        tvec: 日期序列（datetime 数组）

    Returns:
        BlockStructure 包含 starts/ends/indices
    """
    tvec = [
        t if isinstance(t, datetime) else datetime.combine(t, datetime.min.time())
        for t in tvec
    ]

    # 计算每个日期所属块的起始日
    doy = [t.timetuple().tm_yday for t in tvec]
    yy = [t.year for t in tvec]
    blk_starts_raw = [
        datetime(y, 1, 1) + timedelta(days=8 * ((d - 1) // 8)) for y, d in zip(yy, doy)
    ]

    # 去重保持顺序
    seen: dict[datetime, int] = {}
    starts: list[datetime] = []
    for i, bs in enumerate(blk_starts_raw):
        if bs not in seen:
            seen[bs] = len(starts)
            starts.append(bs)

    kb = len(starts)
    ends: list[datetime] = []
    indices: list[np.ndarray] = []

    for k in range(kb):
        ib = [i for i, bs in enumerate(blk_starts_raw) if bs == starts[k]]
        indices.append(np.array(ib, dtype=np.intp))
        ends.append(tvec[ib[-1]])

    return BlockStructure(starts=starts, ends=ends, indices=indices)


# ─── FY3B→FY3D 匹配 ─────────────────────────────────────────────────────────


@dataclass
class MatchInfo:
    """FY3B→FY3D 匹配结果。"""

    method: str
    bias_v: float = 0.0
    bias_h: float = 0.0
    n_valid: int = 0
    applied: bool = False


def match_fy3b_to_fy3d(
    fy3b_tbv: np.ndarray,
    fy3b_tbh: np.ndarray,
    fy3d_tbv: np.ndarray,
    fy3d_tbh: np.ndarray,
    method: str = "bias",
    min_valid_n: int = 20,
) -> MatchInfo:
    """FY3B→FY3D 亮温匹配校正。

    对应 Matlab L78-85 的匹配逻辑。

    Args:
        fy3b_tbv: FY3B 垂直极化亮温（1D）
        fy3b_tbh: FY3B 水平极化亮温（1D）
        fy3d_tbv: FY3D 垂直极化亮温（1D）
        fy3d_tbh: FY3D 水平极化亮温（1D）
        method: 匹配方法（"bias" 或 "cdf"）
        min_valid_n: 最小有效样本数

    Returns:
        MatchInfo 包含偏移量/映射参数
    """
    fy3b_v = np.asarray(fy3b_tbv, dtype=np.float64).ravel()
    fy3b_h = np.asarray(fy3b_tbh, dtype=np.float64).ravel()
    fy3d_v = np.asarray(fy3d_tbv, dtype=np.float64).ravel()
    fy3d_h = np.asarray(fy3d_tbh, dtype=np.float64).ravel()

    valid = (
        np.isfinite(fy3b_v)
        & np.isfinite(fy3b_h)
        & np.isfinite(fy3d_v)
        & np.isfinite(fy3d_h)
    )
    n_valid = int(np.sum(valid))

    if n_valid < min_valid_n:
        logger.warning(
            "FY3B→FY3D 匹配样本不足（%d < %d），跳过匹配", n_valid, min_valid_n
        )
        return MatchInfo(method=method, n_valid=n_valid, applied=False)

    method_upper = method.upper()

    if method_upper == "BIAS":
        bias_v = float(np.median(fy3d_v[valid] - fy3b_v[valid]))
        bias_h = float(np.median(fy3d_h[valid] - fy3b_h[valid]))
        logger.info(
            "FY3B→FY3D bias 匹配: V=%.3f K, H=%.3f K (n=%d)",
            bias_v,
            bias_h,
            n_valid,
        )
        return MatchInfo(
            method=method,
            bias_v=bias_v,
            bias_h=bias_h,
            n_valid=n_valid,
            applied=True,
        )

    if method_upper == "CDF":
        # CDF 匹配：将 FY3B 分布映射到 FY3D
        from scipy.interpolate import interp1d

        def _cdf_match(src: np.ndarray, ref: np.ndarray) -> np.ndarray:
            src_v = src[valid]
            ref_v = ref[valid]
            src_sorted = np.sort(src_v)
            ref_sorted = np.sort(ref_v)
            if len(src_sorted) < 2 or len(ref_sorted) < 2:
                return np.zeros_like(src)
            # 构建分位数映射
            quantiles = np.linspace(0, 1, len(src_sorted))
            interp_func = interp1d(
                quantiles,
                ref_sorted,
                kind="linear",
                bounds_error=False,
                fill_value=(ref_sorted[0], ref_sorted[-1]),
            )
            return interp_func(quantiles).ravel()

        bias_v = float(np.median(_cdf_match(fy3b_v, fy3d_v)))
        bias_h = float(np.median(_cdf_match(fy3b_h, fy3d_h)))
        logger.info(
            "FY3B→FY3D CDF 匹配: V_offset=%.3f K, H_offset=%.3f K (n=%d)",
            bias_v,
            bias_h,
            n_valid,
        )
        return MatchInfo(
            method=method,
            bias_v=bias_v,
            bias_h=bias_h,
            n_valid=n_valid,
            applied=True,
        )

    logger.warning("未知匹配方法 %s，跳过", method)
    return MatchInfo(method=method, n_valid=n_valid, applied=False)


def apply_match_correction(
    tbv: np.ndarray,
    tbh: np.ndarray,
    match_info: MatchInfo,
) -> tuple[np.ndarray, np.ndarray]:
    """应用 FY3B→FY3D 匹配校正。"""
    if not match_info.applied:
        return tbv, tbh
    return tbv + match_info.bias_v, tbh + match_info.bias_h


# ─── OMEGA PFT / Pixel 汇总 ─────────────────────────────────────────────────


@dataclass
class PixelResult:
    """单个像元的反演结果。"""

    iy: int
    ix: int
    class_id: int
    omega: np.ndarray  # (Nt,) OMEGA 时间序列
    sm: np.ndarray  # (Nt,) 土壤水分时间序列
    vod: np.ndarray  # (Nt,) 植被光学厚度时间序列
    h_star: float = float("nan")
    alpha_star: float = float("nan")


def build_omega_pft_from_results(
    results: list[PixelResult],
) -> np.ndarray:
    """从像元结果构建 PFT 级 OMEGA 均值图。

    对应 Matlab ``build_omega_pft_from_R`` (L1989-2004)。

    Args:
        results: 所有像元的反演结果

    Returns:
        omega_pft: (17,) 数组，PFT 0~16 的 OMEGA 中位数
    """
    omega_pft = np.full(17, np.nan)
    for pft in range(17):
        vals: list[float] = []
        for r in results:
            if r.class_id != pft:
                continue
            om = r.omega
            vals.extend(om[np.isfinite(om)].tolist())
        if vals:
            omega_pft[pft] = float(np.median(vals))
    return omega_pft


def build_omega_pixel_from_results(
    results: list[PixelResult],
    grid_shape: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """从像元结果构建逐像元 OMEGA 图。

    对应 Matlab ``build_omega_pixel_from_R`` (L2015-2055)。

    Args:
        results: 所有像元的反演结果
        grid_shape: 网格形状 (nrows, ncols)

    Returns:
        (omega_pix_map, omega_pix_count): 中位数图和有效样本数图
    """
    nrows, ncols = grid_shape
    omega_map = np.full((nrows, ncols), np.nan)
    omega_count = np.zeros((nrows, ncols), dtype=np.int32)

    # 按线性索引聚合
    pixel_omegas: dict[int, list[float]] = {}
    for r in results:
        if not (1 <= r.iy <= nrows and 1 <= r.ix <= ncols):
            continue
        lin = (r.iy - 1) * ncols + (r.ix - 1)  # 0-based
        om = r.omega[np.isfinite(r.omega)]
        if len(om) == 0:
            continue
        if lin not in pixel_omegas:
            pixel_omegas[lin] = []
        pixel_omegas[lin].extend(om.tolist())

    for lin, vals in pixel_omegas.items():
        iy = lin // ncols
        ix = lin % ncols
        omega_map[iy, ix] = float(np.median(vals))
        omega_count[iy, ix] = len(vals)

    return omega_map, omega_count


# ─── 单像元反演核心 ─────────────────────────────────────────────────────────


def execute_pixel_inversion(
    tbv: np.ndarray,
    tbh: np.ndarray,
    ia: np.ndarray,
    ts: np.ndarray,
    sm_ref: np.ndarray,
    ndvi: np.ndarray,
    sf_col: np.ndarray,
    ndvi_max: float,
    ndvi_min: float,
    albedo: float,
    b_param: float,
    clay_fraction: float,
    porosity: float,
    h_static: float,
    landcover: int,
    config: OmegaSfConfig,
    block_struct: BlockStructure,
    omega_fixed: float | None = None,
) -> PixelResult | None:
    """单像元 SF 块反演核心。

    对应 Matlab ``run_one_pixel_core_preloaded`` (L928-1424)。

    流程：
        Step 0: 逐日 Tau 计算
        Step 1: 低 τ 样本 → h/alpha 反演
        Step 2: OMEGA 识别（块级优化或固定值）
        Step 3: 逐日 SM/VOD 反演（DDCA）

    Args:
        tbv, tbh, ia, ts: 时间序列亮温/角度/温度 (Nt,)
        sm_ref: 参考土壤水分 (Nt,)
        ndvi: NDVI 时间序列 (Nt,)
        sf_col: SF 时间序列 (Nt,)
        ndvi_max, ndvi_min: NDVI 气候态极值
        albedo, b_param, clay_fraction, porosity, h_static: 静态参数
        landcover: IGBP 类型
        config: OmegaSfConfig
        block_struct: 8 天块结构
        omega_fixed: 固定 OMEGA 值（PFT/PIXEL 模式）

    Returns:
        PixelResult 或 None（反演失败时）
    """
    nt = len(tbv)
    freq = config.freq_ghz

    # ── Step 0: Tau ──
    tau_star = np.full(nt, np.nan)
    for k in range(nt):
        if np.isfinite(ndvi[k]) and np.isfinite(ia[k]) and np.isfinite(sf_col[k]):
            tau_star[k] = float(
                tau_from_ndvi(
                    ndvi[k],
                    ndvi_max,
                    ndvi_min,
                    landcover,
                    b_param,
                    sf_col[k],
                    ia[k],
                )
            )

    # ── 有效性判断 ──
    if config.temp_scheme.upper() == "ORIG_TS":
        ok_base = (
            np.isfinite(tbv)
            & np.isfinite(tbh)
            & np.isfinite(ts)
            & np.isfinite(sm_ref)
            & np.isfinite(ndvi)
            & np.isfinite(ia)
        )
    else:
        ok_base = (
            np.isfinite(tbv)
            & np.isfinite(tbh)
            & np.isfinite(sm_ref)
            & np.isfinite(ndvi)
            & np.isfinite(ia)
        )

    valid_tau = ok_base & np.isfinite(tau_star)

    if not np.any(valid_tau):
        return None

    # 低 τ 阈值
    tau_vals = tau_star[valid_tau]
    tau_min = float(np.min(tau_vals))
    tau_max = float(np.max(tau_vals))
    tau_thr = tau_min + config.tau_rel_frac * (tau_max - tau_min)
    low_tau = valid_tau & (tau_star <= tau_thr)

    n_low_tau = int(np.sum(low_tau))
    if n_low_tau < config.kmin:
        return None

    # ── Step 1: h/alpha 联合优化 ──
    # 对应 Matlab L1039-1063: lsqnonlin(resid_halpha_single_temp, [h0; ALPHA0], ...)
    # 使用所有低 τ 样本联合优化 [h, alpha]，而非逐样本反演 h 再倒推 alpha
    h_star = float("nan")
    alpha_star = float("nan")

    # 预计算介电上下文（仅依赖 freq/clay）；Fresnel 依赖入射角，按样本缓存
    dielectric_ctx = build_tb_model_context(freq, clay_fraction, 40.0).dielectric
    fresnel_cache: dict[float, object] = {}

    def _tb_ctx_for_theta(theta: float):
        key = round(float(theta), 2)
        cached = fresnel_cache.get(key)
        if cached is not None:
            return cached
        ctx = build_tb_model_context(freq, clay_fraction, key)
        ctx = TbModelContext(dielectric=dielectric_ctx, fresnel=ctx.fresnel)
        fresnel_cache[key] = ctx
        return ctx

    # omega_low：低 τ 模式的单次散射反照率
    # 对应 Matlab L1033-1037: omega_low = omega_fixed (Exp1b) or ALB_ij
    omega_low = float(omega_fixed) if omega_fixed is not None else albedo

    # 低 τ 样本索引
    low_tau_idx = np.where(low_tau)[0]

    # 构建低 τ 样本数组
    tbv_low = tbv[low_tau_idx].astype(np.float64)
    tbh_low = tbh[low_tau_idx].astype(np.float64)
    ts_low = ts[low_tau_idx].astype(np.float64)
    tau_low = tau_star[low_tau_idx].astype(np.float64)
    sm_low = sm_ref[low_tau_idx].astype(np.float64)
    theta_low = ia[low_tau_idx].astype(np.float64)

    # 介电上下文（低 τ 样本共用，Fresnel 按样本入射角现算）
    model_ctx_halpha = build_tb_model_context(freq, clay_fraction, 40.0)

    # 初始猜测：[h0, ALPHA0]，h0 = clamp(h_static, BOUNDS_H)
    # 对应 Matlab L1044: h0 = min(max(H_ij, BOUNDS_H(1)), BOUNDS_H(2))
    h0 = max(min(h_static, config.bounds_h[1]), config.bounds_h[0])
    x0_halpha = np.array([h0, config.alpha0])

    # V/H 极化权重（EQUAL 模式：wV=wH=1）
    w_v = 1.0
    w_h = 1.0

    def _resid_halpha(x):
        return _resid_halpha_single_temp(
            x,
            tbv_low,
            tbh_low,
            ts_low,
            tau_low,
            sm_low,
            theta_low,
            clay_fraction,
            freq,
            omega_low,
            config.alpha0,
            config.lambda_alpha,
            w_v,
            w_h,
            model_ctx_halpha,
        )

    try:
        from scipy.optimize import least_squares

        result_halpha = least_squares(
            _resid_halpha,
            x0_halpha,
            bounds=(
                np.array([config.bounds_h[0], config.bounds_alpha[0]]),
                np.array([config.bounds_h[1], config.bounds_alpha[1]]),
            ),
            max_nfev=400,
            ftol=1e-6,
            xtol=1e-6,
        )
        h_star = float(result_halpha.x[0])
        alpha_star = float(result_halpha.x[1])
    except Exception as exc:
        logger.warning("h/alpha 联合优化失败: %s", exc)
        return None

    if not np.isfinite(h_star) or not np.isfinite(alpha_star):
        return None

    # 逐样本 h/alpha 序列（Step 1 结果广播到所有 valid_tau 样本）
    # 对应 Matlab L1062-1063: h_star_series(valid_tau) = h_star; alpha_series(valid_tau) = alpha_star
    h_star_series = np.full(nt, np.nan)
    alpha_series = np.full(nt, np.nan)
    h_star_series[valid_tau] = h_star
    alpha_series[valid_tau] = alpha_star

    # ── Step 2: OMEGA 块识别（逐样本 h/alpha + 时间平滑） ──
    # 对应 Matlab L1194-1245: 逐块 lsqnonlin(resid_omega_block_single_temp, ...)
    omega_series = np.full(nt, np.nan)

    if omega_fixed is not None:
        # 固定 OMEGA 模式
        omega_series[valid_tau] = omega_fixed
    else:
        omega_prev = float("nan")
        prev_blk_start = None

        for bb, blk_idx in enumerate(block_struct.indices):
            blk_valid_mask = valid_tau[blk_idx]
            blk_use = blk_idx[blk_valid_mask]

            if len(blk_use) == 0:
                prev_blk_start = block_struct.starts[bb]
                continue

            # 时间间隔检测：gap > block_days + 2 则重置 omega_prev
            # 对应 Matlab L1198-1203
            if prev_blk_start is not None:
                gap_days = (block_struct.starts[bb] - prev_blk_start).days
                if gap_days > config.block_days + 2:
                    omega_prev = float("nan")

            # 块内有效样本
            tbv_blk = tbv[blk_use].astype(np.float64)
            tbh_blk = tbh[blk_use].astype(np.float64)
            ts_blk = ts[blk_use].astype(np.float64)
            tau_blk = tau_star[blk_use].astype(np.float64)
            sm_blk = sm_ref[blk_use].astype(np.float64)
            theta_blk = ia[blk_use].astype(np.float64)
            h_blk = h_star_series[blk_use].astype(np.float64)
            a_blk = alpha_series[blk_use].astype(np.float64)

            model_ctx_blk = build_tb_model_context(freq, clay_fraction, 40.0)

            def _resid_omega(om):
                return _resid_omega_block_single_temp(
                    float(om[0]) if hasattr(om, "__len__") else float(om),
                    tbv_blk,
                    tbh_blk,
                    ts_blk,
                    tau_blk,
                    sm_blk,
                    theta_blk,
                    clay_fraction,
                    freq,
                    h_blk,
                    a_blk,
                    config.lambda_smooth,
                    omega_prev,
                    w_v,
                    w_h,
                    model_ctx_blk,
                )

            # 初始猜测：omega_prev if finite else OMEGA0
            # 对应 Matlab L1238: om_init = iff(isfinite(omega_prev), omega_prev, OMEGA0)
            om_init = omega_prev if np.isfinite(omega_prev) else config.omega0

            try:
                result_om = least_squares(
                    lambda om: _resid_omega(om),
                    x0=np.array([om_init]),
                    bounds=(
                        np.array([config.bounds_omega[0]]),
                        np.array([config.bounds_omega[1]]),
                    ),
                    max_nfev=400,
                    ftol=1e-6,
                    xtol=1e-6,
                )
                om_hat = float(result_om.x[0])
            except Exception as exc:
                logger.warning("块 %d OMEGA 优化失败: %s", bb, exc)
                om_hat = float("nan")

            if np.isfinite(om_hat):
                omega_series[blk_use] = om_hat
                omega_prev = om_hat
            else:
                # 优化失败时不更新 omega_prev
                pass

            prev_blk_start = block_struct.starts[bb]

    # ── Step 3: 逐日 SM/VOD（DDCA with Q=max(alpha*h,0)） ──
    # 对应 Matlab L1326-1351: DDCA_single_temp(TBv, TBh, Ts, Tau_ini, hk, CF, OMEGA, ...)
    sm_ret = np.full(nt, np.nan)
    vod_ret = np.full(nt, np.nan)

    for k in range(nt):
        if not valid_tau[k] or not np.isfinite(omega_series[k]):
            continue

        # 逐样本 h/alpha（对应 Matlab L1332-1333: pick_one）
        hk = h_star_series[k] if np.isfinite(h_star_series[k]) else h_star
        ak = alpha_series[k] if np.isfinite(alpha_series[k]) else alpha_star

        model_ctx_k = _tb_ctx_for_theta(float(ia[k]))

        sm_val, vod_val = _ddca_single_temp(
            float(tbv[k]),
            float(tbh[k]),
            float(ts[k]),
            float(tau_star[k]),
            float(hk),
            clay_fraction,
            float(omega_series[k]),
            porosity,
            freq,
            float(ia[k]),
            float(ak),
            config.lambda_tau,
            model_ctx_k,
        )
        if np.isfinite(sm_val):
            sm_ret[k] = sm_val
        if np.isfinite(vod_val):
            vod_ret[k] = vod_val

    return PixelResult(
        iy=0,
        ix=0,
        class_id=landcover,
        omega=omega_series,
        sm=sm_ret,
        vod=vod_ret,
        h_star=h_star,
        alpha_star=alpha_star,
    )


def _forward_tb(
    sm: float,
    tau: float,
    omega: float,
    h: float,
    ts: float,
    clay_fraction: float,
    albedo: float,
    theta_deg: float,
    freq_ghz: float,
    model_ctx: TbModelContext,
    alpha: float | None = None,
) -> tuple[float, float]:
    """前向 TB 模型：给定参数计算亮温。

    使用 Mironov 介电模型 + Fresnel 反射 + tau-omega 模型。

    对应 Matlab ``tb_forward_single_temp`` (L2166-2176)。

    关键：Q = max(alpha * h, 0)，其中 alpha 为极化混合系数（可优化变量）。
    当 alpha=None 时退化为固定 Q = 0.1771 * h（对应原始 F_sm.m）。

    omega 即 tau-omega 模型中的单次散射反照率（Matlab 中的 ``Albedo``/``omega``）。
    ``model_ctx.dielectric`` 可复用（仅依赖 freq/clay）；Fresnel 始终由
    ``theta_deg`` 现算，避免共享错误入射角上下文。

    Args:
        alpha: 极化混合系数。None 时使用固定值 0.1771（对应 ALPHA0）。

    Returns:
        (TBv, TBh) 模型亮温
    """
    from algorithms.physics import (
        build_fresnel_context,
        fresnel_reflectance_from_context,
        mironov_dielectric_from_context,
    )

    if any(np.isnan([sm, tau, omega, h, ts, theta_deg, clay_fraction])):
        return float("nan"), float("nan")
    if tau < 0.0 or h < 0.0:
        return float("nan"), float("nan")

    try:
        # 介电常数（复用 Mironov 上下文，仅依赖 freq/clay）
        epsilon = mironov_dielectric_from_context(sm, model_ctx.dielectric)
        # Fresnel 反射率（按样本入射角现算）
        fresnel_ctx = build_fresnel_context(theta_deg)
        # 掠射角（θ≈90°）物理上无效：卫星观测不可能平行地表入射
        if fresnel_ctx.cos_theta <= 1e-12:
            return float("nan"), float("nan")
        rh, rv = fresnel_reflectance_from_context(epsilon, fresnel_ctx)
        if not (np.isfinite(rh) and np.isfinite(rv)):
            return float("nan"), float("nan")

        # 粗糙表面反射率（含 Q 极化混合）
        # 对应 Matlab tb_forward_single_temp L2169:
        #   Q = max(alpha*h, 0);
        #   rh_r = ((1-Q)*rh + Q*rv) * exp(-h*cosd(Theta)^2);
        #   rv_r = ((1-Q)*rv + Q*rh) * exp(-h*cosd(Theta)^2);
        # alpha 为可优化变量；None 时退化为固定 0.1771（ALPHA0 / Q_FIXED）
        alpha_eff = float(alpha) if alpha is not None else 0.1771
        q_value = max(alpha_eff * h, 0.0)
        exp_term = math.exp(-h * fresnel_ctx.cos_theta_sq)
        rh_r = ((1.0 - q_value) * rh + q_value * rv) * exp_term
        rv_r = ((1.0 - q_value) * rv + q_value * rh) * exp_term

        # 冠层透过率：tau 已经过角度矫正，直接 exp(-tau)
        # 对应 Matlab tb_forward_single_temp L2173: gamma = exp(-Tau);
        gamma = math.exp(-tau)
        one_minus_gamma = -math.expm1(-tau)

        # tau-omega 模型
        # 对应 Matlab tb_forward_single_temp L2174-2175:
        #   TBv_m = C*Ts * ((1-rv_r)*gamma + (1-omega)*(1-gamma)*(1+rv_r*gamma));
        #   TBh_m = C*Ts * ((1-rh_r)*gamma + (1-omega)*(1-gamma)*(1+rh_r*gamma));
        # C=1.0；omega = 单次散射反照率
        _ = albedo  # 保留签名兼容，omega 已作为 albedo 使用
        tbv = ts * (
            (1.0 - rv_r) * gamma
            + (1.0 - omega) * one_minus_gamma * (1.0 + rv_r * gamma)
        )
        tbh = ts * (
            (1.0 - rh_r) * gamma
            + (1.0 - omega) * one_minus_gamma * (1.0 + rh_r * gamma)
        )

        if not (math.isfinite(tbv) and math.isfinite(tbh)):
            return float("nan"), float("nan")
        return float(tbv), float(tbh)
    except (ValueError, OverflowError, FloatingPointError):
        return float("nan"), float("nan")


def _resid_halpha_single_temp(
    x: np.ndarray,
    tbv: np.ndarray,
    tbh: np.ndarray,
    ts: np.ndarray,
    tau: np.ndarray,
    sm_ref: np.ndarray,
    theta: np.ndarray,
    clay_fraction: float,
    freq_ghz: float,
    omega_low: float,
    alpha0: float,
    lam_alpha: float,
    w_v: float,
    w_h: float,
    model_ctx: TbModelContext,
) -> np.ndarray:
    """h/alpha 联合优化残差函数（单温度方案）。

    对应 Matlab ``resid_halpha_single_temp`` (L2116-2127)。

    使用所有低 τ 样本联合优化 h 和 alpha（而非逐样本反演 h 再倒推 alpha）。
    alpha 有 L2 正则化项：sqrt(lam_alpha) * (alpha - alpha0)。

    Args:
        x: [h, alpha] 优化变量
        tbv, tbh, ts, tau, sm_ref, theta: 低 τ 样本序列
        clay_fraction, freq_ghz: 静态参数
        omega_low: 低 τ 模式的单次散射反照率（albedo 或 omega_fixed）
        alpha0: alpha 正则化目标值（通常 = 0.1771）
        lam_alpha: alpha 正则化系数
        w_v, w_h: V/H 极化权重
        model_ctx: 预计算的 TB 模型上下文

    Returns:
        残差向量 (2*K+1,)，前 2K 项为加权亮温残差，末项为 alpha 正则化
    """
    h_val = float(x[0])
    alpha_val = float(x[1])
    k = len(tbv)
    sv = math.sqrt(w_v)
    sh = math.sqrt(w_h)
    r = np.zeros(2 * k + 1)
    for i in range(k):
        tbv_m, tbh_m = _forward_tb(
            float(sm_ref[i]),
            float(tau[i]),
            omega_low,
            h_val,
            float(ts[i]),
            clay_fraction,
            omega_low,
            float(theta[i]),
            freq_ghz,
            model_ctx,
            alpha=alpha_val,
        )
        r[2 * i] = sv * (tbv_m - float(tbv[i]))
        r[2 * i + 1] = sh * (tbh_m - float(tbh[i]))
    r[-1] = math.sqrt(lam_alpha) * (alpha_val - alpha0)
    return r


def _resid_omega_block_single_temp(
    omega: float,
    tbv: np.ndarray,
    tbh: np.ndarray,
    ts: np.ndarray,
    tau: np.ndarray,
    sm_ref: np.ndarray,
    theta: np.ndarray,
    clay_fraction: float,
    freq_ghz: float,
    h_series: np.ndarray,
    alpha_series: np.ndarray,
    lam_smooth: float,
    omega_prev: float,
    w_v: float,
    w_h: float,
    model_ctx: TbModelContext,
) -> np.ndarray:
    """OMEGA 块识别残差函数（单温度方案）。

    对应 Matlab ``resid_omega_block_single_temp`` (L2129-2143)。

    使用逐样本 h/alpha 值（非中位数），并可选时间平滑正则化。
    Q = max(alpha_series(k) * h_series(k), 0)。

    Args:
        omega: OMEGA 优化变量（单次散射反照率）
        tbv, tbh, ts, tau, sm_ref, theta: 块内有效样本
        h_series, alpha_series: 逐样本 h/alpha 值
        lam_smooth: 时间平滑系数（LAMBDA_SMOOTH）
        omega_prev: 上一块的 OMEGA 值（NaN 表示无前块）
        w_v, w_h: V/H 极化权重

    Returns:
        残差向量 (2*K,) 或 (2*K+1,)（含时间平滑项）
    """
    k = len(tbv)
    sv = math.sqrt(w_v)
    sh = math.sqrt(w_h)
    rvh = np.zeros(2 * k)
    for i in range(k):
        tbv_m, tbh_m = _forward_tb(
            float(sm_ref[i]),
            float(tau[i]),
            omega,
            float(h_series[i]),
            float(ts[i]),
            clay_fraction,
            omega,
            float(theta[i]),
            freq_ghz,
            model_ctx,
            alpha=float(alpha_series[i]),
        )
        rvh[2 * i] = sv * (tbv_m - float(tbv[i]))
        rvh[2 * i + 1] = sh * (tbh_m - float(tbh[i]))
    if np.isfinite(omega_prev) and lam_smooth > 0:
        r = np.append(rvh, math.sqrt(lam_smooth) * (omega - omega_prev))
    else:
        r = rvh
    return r


def _f_sm_single_temp(
    x: np.ndarray,
    tbv: float,
    tbh: float,
    ts: float,
    tau_ini: float,
    h: float,
    clay_fraction: float,
    omega: float,
    freq_ghz: float,
    theta_deg: float,
    alpha: float,
    lambda_tau: float,
    model_ctx: TbModelContext,
) -> list[float]:
    """DDCA 残差函数（单温度方案，alpha 依赖 Q）。

    对应 Matlab ``F_sm_single_temp`` (L2152-2164)。

    与 ``inversion.f_sm_cost`` 的关键区别：Q = max(alpha * h, 0) 而非 0.1771 * h。
    初始猜测 [0.20, Tau_ini] 而非 [0.2, 0.5]。

    Returns:
        残差向量 [Tbv_m-Tbv, Tbh_m-Tbh, lambda_tau*(Tau-Tau_ini)]
    """
    sm = float(x[0])
    tau = float(x[1])
    tbv_m, tbh_m = _forward_tb(
        sm,
        tau,
        omega,
        h,
        ts,
        clay_fraction,
        omega,
        theta_deg,
        freq_ghz,
        model_ctx,
        alpha=alpha,
    )
    return [tbv_m - tbv, tbh_m - tbh, lambda_tau * (tau - tau_ini)]


def _ddca_single_temp(
    tbv: float,
    tbh: float,
    ts: float,
    tau_ini: float,
    h: float,
    clay_fraction: float,
    omega: float,
    porosity: float,
    freq_ghz: float,
    theta_deg: float,
    alpha: float,
    lambda_tau: float,
    model_ctx: TbModelContext,
) -> tuple[float, float]:
    """DDCA SM/VOD 反演（单温度方案，alpha 依赖 Q）。

    对应 Matlab ``DDCA_single_temp`` (L2145-2150)。

    与 ``inversion.ddca_retrieve_pixel`` 的关键区别：
    1. Q = max(alpha * h, 0) 而非 0.1771 * h
    2. 初始猜测 [0.20, Tau_ini] 而非 [0.2, 0.5]

    Returns:
        (SM, VOD) 反演结果
    """
    from scipy.optimize import least_squares

    if any(
        math.isnan(v)
        for v in [tbv, tbh, ts, tau_ini, h, clay_fraction, omega, porosity, theta_deg]
    ):
        return float("nan"), float("nan")

    def residual(x):
        return _f_sm_single_temp(
            x,
            tbv,
            tbh,
            ts,
            tau_ini,
            h,
            clay_fraction,
            omega,
            freq_ghz,
            theta_deg,
            alpha,
            lambda_tau,
            model_ctx,
        )

    lower_bounds = (0.02, 0.0)
    upper_bounds = (porosity, 5.0)
    if porosity <= 0.02:
        return float("nan"), float("nan")
    result = least_squares(
        residual,
        x0=[0.20, tau_ini],
        bounds=(lower_bounds, upper_bounds),
        jac=lambda x: _finite_difference_jacobian(
            x, residual, lower_bounds, upper_bounds
        ),
    )
    return float(result.x[0]), float(result.x[1])


# ─── 主反演循环 ─────────────────────────────────────────────────────────────


@dataclass
class OmegaSfResult:
    """omega_sf 反演结果。"""

    omega_pft: np.ndarray  # (17,) PFT 级 OMEGA 中位数
    omega_pixel_map: np.ndarray  # (nrows, ncols) 逐像元 OMEGA 中位数
    omega_pixel_count: np.ndarray  # (nrows, ncols) 有效样本数
    sm_maps: dict[int, np.ndarray]  # {block_idx: (nrows, ncols)} 块级 SM 均值
    vod_maps: dict[int, np.ndarray]  # {block_idx: (nrows, ncols)} 块级 VOD 均值
    omega_maps: dict[int, np.ndarray]  # {block_idx: (nrows, ncols)} 块级 OMEGA
    n_pixels_total: int = 0
    n_pixels_success: int = 0
    n_pixels_failed: int = 0
    output_paths: dict[str, str] = field(default_factory=dict)


def retrieve_omega_sf_daily(
    *,
    config: OmegaSfConfig,
    smap_folder: str,
    anc_root: str,
    ndvi_clim_folder: str = "",
    ndvi_folder: str = "",
    fy3d_folder: str = "",
    fy3b_folder: str = "",
    gldas_mat_folder: str = "",
    ddca_sm_folder: str = "",
    grid_shape: tuple[int, int] | None = None,
    output_dir: str = "",
    progress_callback: Any = None,
) -> OmegaSfResult:
    """omega_sf 逐日块反演主循环。

    对应 Matlab ``OMEGA_IDENT_FAST`` 主函数 (L9-801)。

    流程：
        1. 构建时间序列（扫描各数据源文件夹获取可用日期交集）
        2. 加载静态辅助库（IGBP/Albedo/B/SF/BD/H/CF/NDVI_v_max/min）
        3. 构建 8 天块结构
        4. 逐 chunk 预读 + 逐像元反演
        5. 汇总 OMEGA_pft / OMEGA_pixel + 块级 SM/VOD/OMEGA 网格
        6. 保存结果到 output_dir

    Args:
        config: OmegaSfConfig 配置
        smap_folder: SMAP 逐日 .mat 文件目录
        anc_root: 辅助库目录
        ndvi_clim_folder: NDVI DOY 气候态目录
        ndvi_folder: NDVI 逐日目录（DAILY_FILE 模式）
        fy3d_folder: FY-3D .mat 目录
        fy3b_folder: FY-3B .mat 目录
        gldas_mat_folder: GLDAS .mat 目录（DUAL 温度方案）
        ddca_sm_folder: DDCA SM 目录
        grid_shape: 网格形状 (nrows, ncols)
        output_dir: 输出目录
        progress_callback: 进度回调

    Returns:
        OmegaSfResult 包含所有输出产品
    """
    from ingest.mat_bundle import load_mat_file

    logger.info("=" * 60)
    logger.info("[START] omega_sf_fenkuai 反演")
    logger.info(
        "[RUN  ] EXP=Exp0 | RUN_DOMAIN=%s | TB_SOURCE=%s | SM_SOURCE=%s",
        config.run_domain,
        config.tb_source,
        config.sm_source,
    )
    logger.info("[FIXED] OMEGA_FIXED_MODE=%s", config.omega_fixed_mode)
    logger.info("[BLOCK] %d-day", config.block_days)
    logger.info("=" * 60)

    # 1) 构建时间序列
    tvec = _build_time_series(
        config, smap_folder, ndvi_folder, fy3d_folder, fy3b_folder, ddca_sm_folder
    )
    nt = len(tvec)
    if nt == 0:
        raise ValueError("时间交集为空，请检查 TB/NDVI/SMref 数据。")
    logger.info("[INIT] 可用日期：%d（%s ~ %s）", nt, tvec[0], tvec[-1])

    # 2) 加载静态辅助库
    logger.info("[LOAD] 加载静态辅助库 from %s", anc_root)
    anc = _load_ancillary(anc_root)
    landcover = anc["landcover"]
    if grid_shape is None:
        grid_shape = landcover.shape
    nrows, ncols = grid_shape
    npix = nrows * ncols

    # 3) 构建 8 天块结构
    block_struct = make_viirs8_blocks(tvec)
    logger.info("[BLOCK] 共 %d 个块", len(block_struct.starts))

    # 4) NDVI 气候态
    ndvi_clim_max = anc.get("ndvi_clim_max", np.full(npix, np.nan))
    ndvi_clim_min = anc.get("ndvi_clim_min", np.full(npix, np.nan))

    # 5) 固定 OMEGA（PFT 模式从 omega_pft_file 加载）
    omega_fixed_map: np.ndarray | None = None
    if config.omega_fixed_mode.upper() == "PFT":
        omega_pft_file = Path(config.out_aux or "") / "omega_pft_from_exp0.mat"
        if omega_pft_file.exists():
            data = load_mat_file(str(omega_pft_file))
            if "omega_pft" in data:
                omega_fixed_map = np.asarray(data["omega_pft"], dtype=np.float64)

    # 6) 逐 chunk 反演
    all_results: list[PixelResult] = []
    n_processed = 0
    n_success = 0
    n_failed = 0

    chunk_size = config.pixel_chunk_size
    chunks = [(i, min(i + chunk_size, npix)) for i in range(0, npix, chunk_size)]
    logger.info("[CHUNK] 共 %d 个 chunk（每 chunk %d 像元）", len(chunks), chunk_size)

    for ci, (chunk_start, chunk_end) in enumerate(chunks):
        chunk_pix = chunk_end - chunk_start
        logger.info(
            "[CHUNK %d/%d] 像元 %d~%d (%d)",
            ci + 1,
            len(chunks),
            chunk_start,
            chunk_end,
            chunk_pix,
        )

        # 预读 chunk 数据
        chunk_data = _preload_chunk(
            tvec,
            chunk_start,
            chunk_end,
            nrows,
            ncols,
            config,
            smap_folder,
            fy3d_folder,
            fy3b_folder,
            ndvi_clim_folder,
            ndvi_folder,
            anc,
        )

        # 逐像元反演
        for p in range(chunk_pix):
            lin_idx = chunk_start + p
            iy = lin_idx // ncols + 1  # 1-based
            ix = lin_idx % ncols + 1

            n_processed += 1

            result = execute_pixel_inversion(
                tbv=chunk_data["tbv"][:, p],
                tbh=chunk_data["tbh"][:, p],
                ia=chunk_data["ia"][:, p],
                ts=chunk_data["ts"][:, p],
                sm_ref=chunk_data["sm_ref"][:, p],
                ndvi=chunk_data["ndvi"][:, p],
                sf_col=chunk_data["sf"][:, p],
                ndvi_max=float(ndvi_clim_max[lin_idx])
                if lin_idx < len(ndvi_clim_max)
                else float("nan"),
                ndvi_min=float(ndvi_clim_min[lin_idx])
                if lin_idx < len(ndvi_clim_min)
                else float("nan"),
                albedo=float(anc["albedo"].ravel()[lin_idx])
                if lin_idx < npix
                else float("nan"),
                b_param=float(anc["b"].ravel()[lin_idx])
                if lin_idx < npix
                else float("nan"),
                clay_fraction=float(anc["clay"].ravel()[lin_idx])
                if lin_idx < npix
                else float("nan"),
                porosity=float(anc["porosity"].ravel()[lin_idx])
                if lin_idx < npix
                else float("nan"),
                h_static=float(anc["h"].ravel()[lin_idx])
                if lin_idx < npix
                else float("nan"),
                landcover=int(landcover.ravel()[lin_idx]) if lin_idx < npix else 0,
                config=config,
                block_struct=block_struct,
                omega_fixed=float(omega_fixed_map[landcover.ravel()[lin_idx]])
                if omega_fixed_map is not None and lin_idx < npix
                else None,
            )

            if result is not None:
                result.iy = iy
                result.ix = ix
                all_results.append(result)
                n_success += 1
            else:
                n_failed += 1

            if progress_callback and n_processed % 1000 == 0:
                progress_callback(n_processed, npix)

    logger.info(
        "[DONE] 反演完成：成功 %d / 失败 %d / 总计 %d",
        n_success,
        n_failed,
        n_processed,
    )

    # 7) 汇总输出
    omega_pft = build_omega_pft_from_results(all_results)
    omega_pix_map, omega_pix_count = build_omega_pixel_from_results(
        all_results, grid_shape
    )

    # 块级 SM/VOD/OMEGA 网格
    sm_maps: dict[int, np.ndarray] = {}
    vod_maps: dict[int, np.ndarray] = {}
    omega_maps: dict[int, np.ndarray] = {}

    for blk_idx, blk_indices in enumerate(block_struct.indices):
        sm_grid = np.full(grid_shape, np.nan)
        vod_grid = np.full(grid_shape, np.nan)
        om_grid = np.full(grid_shape, np.nan)

        for r in all_results:
            if not (1 <= r.iy <= nrows and 1 <= r.ix <= ncols):
                continue
            iy0 = r.iy - 1
            ix0 = r.ix - 1
            sm_blk = r.sm[blk_indices]
            vod_blk = r.vod[blk_indices]
            om_blk = r.omega[blk_indices]

            sm_valid = sm_blk[np.isfinite(sm_blk)]
            vod_valid = vod_blk[np.isfinite(vod_blk)]
            om_valid = om_blk[np.isfinite(om_blk)]

            if len(sm_valid) > 0:
                sm_grid[iy0, ix0] = float(np.median(sm_valid))
            if len(vod_valid) > 0:
                vod_grid[iy0, ix0] = float(np.median(vod_valid))
            if len(om_valid) > 0:
                om_grid[iy0, ix0] = float(np.median(om_valid))

        sm_maps[blk_idx] = sm_grid
        vod_maps[blk_idx] = vod_grid
        omega_maps[blk_idx] = om_grid

    # 8) 保存
    output_paths: dict[str, str] = {}
    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        try:
            from scipy.io import savemat

            # OMEGA PFT
            pft_file = out_path / "omega_pft.mat"
            savemat(str(pft_file), {"omega_pft": omega_pft})
            output_paths["omega_pft"] = str(pft_file)

            # OMEGA pixel
            pix_file = out_path / "omega_pixel.mat"
            savemat(
                str(pix_file),
                {
                    "omega_pix_map": omega_pix_map,
                    "omega_pix_count": omega_pix_count,
                },
            )
            output_paths["omega_pixel"] = str(pix_file)

            # 块级 SM / VOD / OMEGA
            for blk_idx in sm_maps:
                blk_file = out_path / f"block_{blk_idx:03d}.mat"
                savemat(
                    str(blk_file),
                    {
                        "SM": sm_maps[blk_idx],
                        "VOD": vod_maps[blk_idx],
                        "OMEGA": omega_maps[blk_idx],
                        "block_start": str(block_struct.starts[blk_idx]),
                        "block_end": str(block_struct.ends[blk_idx]),
                    },
                )
            output_paths["block_dir"] = str(out_path)

            logger.info("[SAVE] 结果已保存到 %s", out_path)
        except Exception as exc:
            logger.error("[SAVE] 保存失败: %s", exc)

    return OmegaSfResult(
        omega_pft=omega_pft,
        omega_pixel_map=omega_pix_map,
        omega_pixel_count=omega_pix_count,
        sm_maps=sm_maps,
        vod_maps=vod_maps,
        omega_maps=omega_maps,
        n_pixels_total=n_processed,
        n_pixels_success=n_success,
        n_pixels_failed=n_failed,
        output_paths=output_paths,
    )


# ─── 辅助函数 ───────────────────────────────────────────────────────────────


def _build_time_series(
    config: OmegaSfConfig,
    smap_folder: str,
    ndvi_folder: str,
    fy3d_folder: str,
    fy3b_folder: str,
    ddca_sm_folder: str,
) -> list[datetime]:
    """构建时间序列：取所有数据源的日期交集。"""
    start = datetime.strptime(config.start_date, "%Y%m%d")
    end = datetime.strptime(config.end_date, "%Y%m%d")
    tvec_req = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    # SMAP 日期
    t_smap = _scan_folder_dates(smap_folder)
    if t_smap:
        tvec_req = [t for t in tvec_req if t in t_smap]

    # NDVI 日期（仅 DAILY_FILE 模式需要）
    if config.ndvi_mode.upper() == "DAILY_FILE" and ndvi_folder:
        t_ndvi = _scan_folder_dates(ndvi_folder)
        if t_ndvi:
            tvec_req = [t for t in tvec_req if t in t_ndvi]

    # TB 日期
    if config.tb_source.upper() == "FY":
        tb_folder = fy3d_folder if config.fy_platform.upper() == "3D" else fy3b_folder
        if tb_folder:
            t_tb = _scan_folder_dates(tb_folder)
            if t_tb:
                tvec_req = [t for t in tvec_req if t in t_tb]
    else:
        # SMAP TB = SMAP 文件
        pass

    # SM 参考日期
    if config.sm_source.upper() == "DDCA" and ddca_sm_folder:
        t_smref = _scan_folder_dates(ddca_sm_folder)
        if t_smref:
            tvec_req = [t for t in tvec_req if t in t_smref]

    return sorted(tvec_req)


def _scan_folder_dates(folder: str) -> set[datetime]:
    """扫描文件夹中的 YYYYMMDD.mat 文件，返回日期集合。"""
    if not folder:
        return set()
    p = Path(folder)
    if not p.exists():
        logger.warning("文件夹不存在: %s", folder)
        return set()

    dates: set[datetime] = set()
    for f in p.glob("*.mat"):
        name = f.stem
        try:
            d = datetime.strptime(name, "%Y%m%d")
            dates.add(d)
        except ValueError:
            continue
    return dates


def _load_ancillary(anc_root: str) -> dict[str, np.ndarray]:
    """加载静态辅助库。

    对应 Matlab L338-362。
    """
    from ingest.mat_bundle import load_mat_file

    root = Path(anc_root)
    anc: dict[str, np.ndarray] = {}

    # IGBP 土地覆盖
    igbp_path = root / "IGBP_9km_12.mat"
    if igbp_path.exists():
        data = load_mat_file(str(igbp_path))
        for key in ("IGBP_9km_12", "landcover", "LC"):
            if key in data:
                anc["landcover"] = np.asarray(data[key], dtype=np.float64)
                break

    # Albedo
    albedo_path = root / "Albedo.mat"
    if albedo_path.exists():
        data = load_mat_file(str(albedo_path))
        for key in ("ALBEDO", "Albedo", "albedo"):
            if key in data:
                anc["albedo"] = np.asarray(data[key], dtype=np.float64)
                break

    # B
    b_path = root / "B.mat"
    if b_path.exists():
        data = load_mat_file(str(b_path))
        for key in ("B", "b"):
            if key in data:
                anc["b"] = np.asarray(data[key], dtype=np.float64)
                break

    # SF (static)
    sf_path = root / "SF.mat"
    if sf_path.exists():
        data = load_mat_file(str(sf_path))
        for key in ("SF_smap", "SF"):
            if key in data:
                anc["sf_static"] = np.asarray(data[key], dtype=np.float64)
                break

    # BD (bulk density)
    bd_path = root / "BD.mat"
    if bd_path.exists():
        data = load_mat_file(str(bd_path))
        for key in ("BD", "bd"):
            if key in data:
                anc["bd"] = np.asarray(data[key], dtype=np.float64)
                break

    # H (roughness)
    h_path = root / "H.mat"
    if h_path.exists():
        data = load_mat_file(str(h_path))
        for key in ("H", "h"):
            if key in data:
                anc["h"] = np.asarray(data[key], dtype=np.float64)
                break

    # CF (clay fraction)
    cf_path = root / "CF.mat"
    if cf_path.exists():
        data = load_mat_file(str(cf_path))
        for key in ("CF", "cf"):
            if key in data:
                anc["clay"] = np.asarray(data[key], dtype=np.float64)
                break

    # NDVI_v_max / NDVI_v_min
    ndvi_extrema_path = root / "NDVI_extrema.mat"
    if ndvi_extrema_path.exists():
        data = load_mat_file(str(ndvi_extrema_path))
        for key in ("NDVI_v_max", "ndvi_v_max"):
            if key in data:
                anc["ndvi_v_max"] = np.asarray(data[key], dtype=np.float64).ravel()
                break
        for key in ("NDVI_v_min", "ndvi_v_min"):
            if key in data:
                anc["ndvi_v_min"] = np.asarray(data[key], dtype=np.float64).ravel()
                break

    # NDVI climatology max/min
    ndvi_clim_folder = root / "NDVI_clim"
    if ndvi_clim_folder.exists():
        anc["ndvi_clim_max"] = _build_ndvi_clim_max(ndvi_clim_folder)
        anc["ndvi_clim_min"] = _build_ndvi_clim_min(ndvi_clim_folder)

    # 默认值
    if "landcover" not in anc:
        anc["landcover"] = np.zeros((1, 1))
    for key in ("albedo", "b", "bd", "h", "clay"):
        if key not in anc:
            anc[key] = np.full(anc["landcover"].shape, np.nan)
    if "ndvi_clim_max" not in anc:
        anc["ndvi_clim_max"] = np.full(anc["landcover"].size, np.nan)
    if "ndvi_clim_min" not in anc:
        anc["ndvi_clim_min"] = np.full(anc["landcover"].size, np.nan)

    # 孔隙度 = 1 - BD/2.65 (矿物颗粒密度)；过小/负值视为无效
    _POROSITY_MIN = 0.02
    _MINERAL_DENSITY = 2.65
    if "bd" in anc and "porosity" not in anc:
        porosity = 1.0 - np.asarray(anc["bd"], dtype=np.float64) / _MINERAL_DENSITY
        porosity = np.where(
            np.isfinite(porosity) & (porosity > _POROSITY_MIN),
            porosity,
            np.nan,
        )
        anc["porosity"] = porosity

    return anc


def _build_ndvi_clim_max(folder: Path) -> np.ndarray:
    """构建 NDVI 气候态年最大值。"""
    from ingest.mat_bundle import load_mat_file

    arrays: list[np.ndarray] = []
    for f in sorted(folder.glob("*.mat")):
        try:
            data = load_mat_file(str(f))
            for key in ("NDVI_clim", "ndvi_clim"):
                if key in data:
                    arrays.append(np.asarray(data[key], dtype=np.float64))
                    break
        except Exception:
            continue

    if not arrays:
        return np.full(1, np.nan)

    stacked = np.stack(arrays, axis=0)
    return np.nanmax(stacked, axis=0).ravel()


def _build_ndvi_clim_min(folder: Path) -> np.ndarray:
    """构建 NDVI 气候态年最小值。"""
    from ingest.mat_bundle import load_mat_file

    arrays: list[np.ndarray] = []
    for f in sorted(folder.glob("*.mat")):
        try:
            data = load_mat_file(str(f))
            for key in ("NDVI_clim", "ndvi_clim"):
                if key in data:
                    arrays.append(np.asarray(data[key], dtype=np.float64))
                    break
        except Exception:
            continue

    if not arrays:
        return np.full(1, np.nan)

    stacked = np.stack(arrays, axis=0)
    return np.nanmin(stacked, axis=0).ravel()


def _preload_chunk(
    tvec: list[datetime],
    chunk_start: int,
    chunk_end: int,
    nrows: int,
    ncols: int,
    config: OmegaSfConfig,
    smap_folder: str,
    fy3d_folder: str,
    fy3b_folder: str,
    ndvi_clim_folder: str,
    ndvi_folder: str,
    anc: dict[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """预读 chunk 数据。

    对应 Matlab 预读总函数 (L1425-1729)。

    返回 dict 包含 tbv/tbh/ia/ts/sm_ref/ndvi/sf，形状均为 (Nt, chunk_pix)。
    """
    from ingest.mat_bundle import load_mat_file

    nt = len(tvec)
    chunk_pix = chunk_end - chunk_start
    lin_pix = np.arange(chunk_start, chunk_end)

    tbv_mat = np.full((nt, chunk_pix), np.nan)
    tbh_mat = np.full((nt, chunk_pix), np.nan)
    ia_mat = np.full((nt, chunk_pix), np.nan)
    ts_mat = np.full((nt, chunk_pix), np.nan)
    sm_ref_mat = np.full((nt, chunk_pix), np.nan)
    ndvi_mat = np.full((nt, chunk_pix), np.nan)
    sf_mat = np.full((nt, chunk_pix), np.nan)

    landcover_flat = anc["landcover"].ravel()
    sf_static = anc.get("sf_static", np.full(anc["landcover"].size, np.nan)).ravel()
    ndvi_clim_max = anc.get("ndvi_clim_max", np.full(anc["landcover"].size, np.nan))
    ndvi_clim_min = anc.get("ndvi_clim_min", np.full(anc["landcover"].size, np.nan))

    for k, date in enumerate(tvec):
        date_str = date.strftime("%Y%m%d")
        doy = date.timetuple().tm_yday

        # SMAP 文件
        smap_file = Path(smap_folder) / f"{date_str}.mat"
        smap_data: dict[str, Any] = {}
        if smap_file.exists():
            try:
                smap_data = load_mat_file(str(smap_file))
            except Exception:
                pass

        # TB 数据
        if config.tb_source.upper() == "FY":
            tb_folder = (
                fy3d_folder if config.fy_platform.upper() == "3D" else fy3b_folder
            )
            tb_file = Path(tb_folder) / f"{date_str}.mat"
            if tb_file.exists():
                try:
                    tb_data = load_mat_file(str(tb_file))
                    for key in ("TBv_mat", "TBv"):
                        if key in tb_data:
                            vals = np.asarray(tb_data[key], dtype=np.float64).ravel()
                            tbv_mat[k, : len(vals)] = vals[lin_pix]
                            break
                    for key in ("TBh_mat", "TBh"):
                        if key in tb_data:
                            vals = np.asarray(tb_data[key], dtype=np.float64).ravel()
                            tbh_mat[k, : len(vals)] = vals[lin_pix]
                            break
                except Exception:
                    pass
        else:
            # SMAP TB
            for key in ("TBv", "TBv_mat"):
                if key in smap_data:
                    vals = np.asarray(smap_data[key], dtype=np.float64).ravel()
                    tbv_mat[k, : len(vals)] = vals[lin_pix]
                    break
            for key in ("TBh", "TBh_mat"):
                if key in smap_data:
                    vals = np.asarray(smap_data[key], dtype=np.float64).ravel()
                    tbh_mat[k, : len(vals)] = vals[lin_pix]
                    break

        # 入射角
        for key in ("IA", "IA_mat"):
            if key in smap_data:
                vals = np.asarray(smap_data[key], dtype=np.float64).ravel()
                ia_mat[k, : len(vals)] = vals[lin_pix]
                break

        # 温度
        for key in ("Ts", "Ts_mat"):
            if key in smap_data:
                vals = np.asarray(smap_data[key], dtype=np.float64).ravel()
                ts_mat[k, : len(vals)] = vals[lin_pix]
                break

        # 参考土壤水分
        for key in ("SM", "SM_mat", "soil_moisture"):
            if key in smap_data:
                vals = np.asarray(smap_data[key], dtype=np.float64).ravel()
                sm_ref_mat[k, : len(vals)] = vals[lin_pix]
                break

        # NDVI
        if config.ndvi_mode.upper() == "DOY_CLIM" and ndvi_clim_folder:
            clim_file = Path(ndvi_clim_folder) / f"{doy}.mat"
            if clim_file.exists():
                try:
                    clim_data = load_mat_file(str(clim_file))
                    for key in ("NDVI_clim", "ndvi_clim"):
                        if key in clim_data:
                            vals = np.asarray(clim_data[key], dtype=np.float64).ravel()
                            ndvi_mat[k, : len(vals)] = vals[lin_pix]
                            break
                except Exception:
                    pass
        elif config.ndvi_mode.upper() == "DAILY_FILE" and ndvi_folder:
            ndvi_file = Path(ndvi_folder) / f"{date_str}.mat"
            if ndvi_file.exists():
                try:
                    ndvi_data = load_mat_file(str(ndvi_file))
                    for key in ("NDVI", "ndvi"):
                        if key in ndvi_data:
                            vals = np.asarray(ndvi_data[key], dtype=np.float64).ravel()
                            ndvi_mat[k, : len(vals)] = vals[lin_pix]
                            break
                except Exception:
                    pass

        # SF
        if config.sf_mode.upper() == "STATIC":
            sf_mat[k, :] = sf_static[lin_pix]
        elif config.sf_mode.upper() == "INVERTED_DAILY":
            # 需要 vwc 和 NDVI_clim
            vwc_vals = np.full(chunk_pix, np.nan)
            for key in ("vwc", "VWC"):
                if key in smap_data:
                    vals = np.asarray(smap_data[key], dtype=np.float64).ravel()
                    vwc_vals = vals[lin_pix]
                    break

            # 读当天 DOY 的 NDVI_clim
            clim_file = Path(ndvi_clim_folder) / f"{doy}.mat"
            ndvi_clim_row = np.full(chunk_pix, np.nan)
            if clim_file.exists():
                try:
                    clim_data = load_mat_file(str(clim_file))
                    for key in ("NDVI_clim", "ndvi_clim"):
                        if key in clim_data:
                            vals = np.asarray(clim_data[key], dtype=np.float64).ravel()
                            ndvi_clim_row = vals[lin_pix]
                            break
                except Exception:
                    pass

            cls_row = (
                landcover_flat[lin_pix]
                if lin_pix.max() < len(landcover_flat)
                else np.zeros(chunk_pix)
            )
            ndvi_max_row = (
                ndvi_clim_max[lin_pix]
                if lin_pix.max() < len(ndvi_clim_max)
                else np.full(chunk_pix, np.nan)
            )
            ndvi_min_row = (
                ndvi_clim_min[lin_pix]
                if lin_pix.max() < len(ndvi_clim_min)
                else np.full(chunk_pix, np.nan)
            )

            sf_mat[k, :] = build_sf_row_daily(
                vwc_vals,
                ndvi_clim_row,
                ndvi_max_row,
                ndvi_min_row,
                cls_row,
                config.sf_invert_mode,
            )

    return {
        "tbv": tbv_mat,
        "tbh": tbh_mat,
        "ia": ia_mat,
        "ts": ts_mat,
        "sm_ref": sm_ref_mat,
        "ndvi": ndvi_mat,
        "sf": sf_mat,
    }
