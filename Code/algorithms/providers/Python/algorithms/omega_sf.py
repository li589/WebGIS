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

import contextlib
import json
import logging
import math
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from collections.abc import Sequence

import numpy as np

from algorithms.inversion import (
    TbModelContext,
    _finite_difference_jacobian,
    build_tb_model_context,
)
from algorithms.physics import tau_from_ndvi

# ingest.daily_bundle 经 contracts 包 → runner.registry → pipelines 回引自身，
# 须先完整加载 contracts 才能安全 lazy-import daily_bundle（否则部分初始化循环导入）
import contracts  # noqa: E402,F401

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

    # ── 双温度方案（temp_scheme="DUAL"）──
    # 字段语义与 ingest/daily_bundle.py DailyBundleConfig 对齐
    dual_tg_mode: str = "PAPER_CT"  # "PAPER_CT" | "TSOIL1_ONLY" | "TSOIL2_ONLY"
    ct_smref: float = 0.30  # PAPER_CT 幂律参考土壤水分
    ct_exp: float = 0.30  # PAPER_CT 幂律指数
    gldas_time_tol_hours: float = 1.6  # GLDAS 过境时间匹配容差（小时）
    fy3d_desc_local_hour: float = 2.0  # FY-3D 降轨过境本地时
    fy3b_desc_local_hour: float = 1.0 + 40.0 / 60.0  # FY-3B 降轨过境本地时
    smap_desc_local_hour: float = 6.0  # SMAP 降轨过境本地时
    use_gldas_template: bool = False  # True=按模板槽位选 GLDAS；False=过境本地时匹配

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
    max_workers: int | None = None  # None → auto_process_count；1 强制串行
    pixel_chunk_size: int = 200000

    # ── 日期范围 ──
    start_date: str = "20250101"
    end_date: str = "20251231"

    # ── 空间裁剪 / 抽样（验证窗；None 表示不裁剪）──
    bbox_west: float | None = None
    bbox_south: float | None = None
    bbox_east: float | None = None
    bbox_north: float | None = None
    max_pixels: int = 0  # >0 时限制有效像元数（等价 OMEGA_SF_MAX_PIXELS）

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
        """从 algorithm_params 字典构建配置。

        兼容 ``bbox: [west, south, east, north]``（与 API/seed 常用写法），
        展开为 ``bbox_west/south/east/north``。
        """
        known_fields = {f.name for f in OmegaSfConfig.__dataclass_fields__.values()}
        filtered = {k: v for k, v in params.items() if k in known_fields}
        raw_bbox = params.get("bbox")
        if (
            filtered.get("bbox_west") is None
            and isinstance(raw_bbox, (list, tuple))
            and len(raw_bbox) == 4
        ):
            filtered["bbox_west"] = float(raw_bbox[0])
            filtered["bbox_south"] = float(raw_bbox[1])
            filtered["bbox_east"] = float(raw_bbox[2])
            filtered["bbox_north"] = float(raw_bbox[3])
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


def make_viirs8_blocks(tvec: Sequence[datetime], block_days: int = 8) -> BlockStructure:
    """按 N 天划分时间块（默认 8 天）。

    对应 Matlab ``make_viirs8_blocks`` (L2813-2831)。

    算法：以每年 1 月 1 日为起点，每 ``block_days`` 天一块，跨年重置。
    不足 ``block_days`` 天的末尾块也保留（年末不足则到 12.31）。

    Args:
        tvec: 日期序列（datetime 数组）
        block_days: 每块天数（默认 8，对应 VIIRS 8-day 合成周期）

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
        datetime(y, 1, 1) + timedelta(days=block_days * ((d - 1) // block_days))
        for y, d in zip(yy, doy)
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


def _step0_compute_tau_star(
    ndvi: np.ndarray,
    ia: np.ndarray,
    sf_col: np.ndarray,
    ndvi_max: float,
    ndvi_min: float,
    landcover: int,
    b_param: float,
    nt: int,
) -> np.ndarray:
    """Step 0: 逐日 Tau 计算（矢量化）。

    使用 tau_from_ndvi 计算全时序 Tau。
    对应原 ``execute_pixel_inversion`` L613–629。

    Args:
        ndvi: NDVI 时间序列 (Nt,)
        ia: 入射角时间序列 (Nt,)
        sf_col: SF 时间序列 (Nt,)
        ndvi_max, ndvi_min: NDVI 气候态极值
        landcover: IGBP 类型
        b_param: B 参数
        nt: 时间序列长度

    Returns:
        tau_star (Nt,) — 缺测位置为 NaN
    """
    ok_tau_input = np.isfinite(ndvi) & np.isfinite(ia) & np.isfinite(sf_col)
    tau_star = np.full(nt, np.nan)
    if np.any(ok_tau_input):
        ndvi_safe = np.where(ok_tau_input, ndvi, 0.5)
        sf_safe = np.where(ok_tau_input, sf_col, 0.0)
        ia_safe = np.where(ok_tau_input, ia, 40.0)
        tau_all = tau_from_ndvi(
            ndvi_safe,
            ndvi_max,
            ndvi_min,
            landcover,
            b_param,
            sf_safe,
            ia_safe,
        )
        tau_star = np.where(ok_tau_input, tau_all, np.nan)
    return tau_star


def _step1_invert_halpha(
    tbv: np.ndarray,
    tbh: np.ndarray,
    ts: np.ndarray,
    tau_star: np.ndarray,
    sm_ref: np.ndarray,
    ia: np.ndarray,
    low_tau: np.ndarray,
    valid_tau: np.ndarray,
    clay_fraction: float,
    freq_ghz: float,
    omega_low: float,
    h_static: float,
    config: OmegaSfConfig,
    tc: np.ndarray | None = None,
    tg: np.ndarray | None = None,
) -> tuple[float, float, np.ndarray, np.ndarray]:
    """Step 1: h/alpha 联合优化（所有低 τ 样本）。

    使用 scipy least_squares 联合优化 [h, alpha]。
    内部定义 _resid_halpha 闭包调用 _resid_halpha_single_temp；
    ``tc``/``tg`` 非 None 时（DUAL）改调 _resid_halpha_dual_temp。
    对应原 ``execute_pixel_inversion`` L666–760。

    Args:
        tbv, tbh, ts, tau_star, sm_ref, ia: 全时序 (Nt,)（ts 仅 ORIG_TS 使用）
        low_tau: 低 τ 布尔掩码 (Nt,)
        valid_tau: 有效 τ 布尔掩码 (Nt,)，用于广播 h_star_series/alpha_series
        clay_fraction: 黏土含量
        freq_ghz: 频率
        omega_low: 低 τ 模式单次散射反照率
        h_static: 静态 h 值
        config: OmegaSfConfig（读取 bounds_h, bounds_alpha, alpha0, lambda_alpha）
        tc, tg: DUAL 温度序列 (Nt,)（None 表示 ORIG_TS）

    Returns:
        (h_star, alpha_star, h_star_series, alpha_series)
        h_star/alpha_star: 标量优化结果
        h_star_series/alpha_series: (Nt,) 广播到 valid_tau 样本
    """
    nt = len(tbv)
    use_dual = tc is not None and tg is not None

    h_star = float("nan")
    alpha_star = float("nan")

    # 低 τ 样本索引
    low_tau_idx = np.where(low_tau)[0]

    # 构建低 τ 样本数组
    tbv_low = tbv[low_tau_idx].astype(np.float64)
    tbh_low = tbh[low_tau_idx].astype(np.float64)
    ts_low = ts[low_tau_idx].astype(np.float64)
    tau_low = tau_star[low_tau_idx].astype(np.float64)
    sm_low = sm_ref[low_tau_idx].astype(np.float64)
    theta_low = ia[low_tau_idx].astype(np.float64)
    tc_low = (
        np.asarray(tc, dtype=np.float64)[low_tau_idx]
        if use_dual
        else np.array([], dtype=np.float64)
    )
    tg_low = (
        np.asarray(tg, dtype=np.float64)[low_tau_idx]
        if use_dual
        else np.array([], dtype=np.float64)
    )

    # 介电上下文（低 τ 样本共用，Fresnel 按样本入射角现算）
    model_ctx_halpha = build_tb_model_context(freq_ghz, clay_fraction, 40.0)

    # 初始猜测：[h0, ALPHA0]，h0 = clamp(h_static, BOUNDS_H)
    # 对应 Matlab L1044: h0 = min(max(H_ij, BOUNDS_H(1)), BOUNDS_H(2))
    h0 = max(min(h_static, config.bounds_h[1]), config.bounds_h[0])
    x0_halpha = np.array([h0, config.alpha0])

    # V/H 极化权重（EQUAL 模式：wV=wH=1）
    w_v = 1.0
    w_h = 1.0

    if use_dual:

        def _resid_halpha(x):
            return _resid_halpha_dual_temp(
                x,
                tbv_low,
                tbh_low,
                tc_low,
                tg_low,
                tau_low,
                sm_low,
                theta_low,
                clay_fraction,
                freq_ghz,
                omega_low,
                config.alpha0,
                config.lambda_alpha,
                w_v,
                w_h,
                model_ctx_halpha,
            )
    else:

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
                freq_ghz,
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
            max_nfev=100,
            ftol=1e-6,
            xtol=1e-6,
        )
        h_star = float(result_halpha.x[0])
        alpha_star = float(result_halpha.x[1])
    except Exception as exc:
        logger.warning("h/alpha 联合优化失败: %s", exc)
        return float("nan"), float("nan"), np.full(nt, np.nan), np.full(nt, np.nan)

    # 逐样本 h/alpha 序列（Step 1 结果广播到所有 valid_tau 样本）
    # 对应 Matlab L1062-1063: h_star_series(valid_tau) = h_star; alpha_series(valid_tau) = alpha_star
    h_star_series = np.full(nt, np.nan)
    alpha_series = np.full(nt, np.nan)
    h_star_series[valid_tau] = h_star
    alpha_series[valid_tau] = alpha_star

    return h_star, alpha_star, h_star_series, alpha_series


def _step3_ddca_retrieval(
    tbv: np.ndarray,
    tbh: np.ndarray,
    ts: np.ndarray,
    ia: np.ndarray,
    tau_star: np.ndarray,
    valid_tau: np.ndarray,
    omega_series: np.ndarray,
    h_star_series: np.ndarray,
    alpha_series: np.ndarray,
    h_star: float,
    alpha_star: float,
    clay_fraction: float,
    porosity: float,
    freq_ghz: float,
    config: OmegaSfConfig,
    tc: np.ndarray | None = None,
    tg: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Step 3: 逐日 SM/VOD DDCA 反演。

    使用 _ddca_single_temp 逐日反演；``tc``/``tg`` 非 None 时（DUAL）
    改调 _ddca_dual_temp。
    内部重建 _tb_ctx_for_theta 闭包（含 Fresnel 缓存）。
    对应原 ``execute_pixel_inversion`` L850–883。

    Args:
        tbv, tbh, ts, ia, tau_star: 全时序 (Nt,)（ts 仅 ORIG_TS 使用）
        valid_tau: 有效 τ 布尔掩码 (Nt,)
        omega_series: OMEGA 序列 (Nt,)
        h_star_series, alpha_series: h/alpha 序列 (Nt,)
        h_star, alpha_star: 标量回退值
        clay_fraction, porosity: 静态参数
        freq_ghz: 频率
        config: OmegaSfConfig（读取 lambda_tau）
        tc, tg: DUAL 温度序列 (Nt,)（None 表示 ORIG_TS）

    Returns:
        (sm_ret, vod_ret) — 各 (Nt,)，无效位置 NaN
    """
    nt = len(tbv)
    use_dual = tc is not None and tg is not None

    # 重建 _tb_ctx_for_theta 闭包（含 Fresnel 缓存）
    dielectric_ctx = build_tb_model_context(freq_ghz, clay_fraction, 40.0).dielectric
    fresnel_cache: dict[float, object] = {}

    def _tb_ctx_for_theta(theta: float):
        key = round(float(theta), 2)
        cached = fresnel_cache.get(key)
        if cached is not None:
            return cached
        ctx = build_tb_model_context(freq_ghz, clay_fraction, key)
        ctx = TbModelContext(dielectric=dielectric_ctx, fresnel=ctx.fresnel)
        fresnel_cache[key] = ctx
        return ctx

    sm_ret = np.full(nt, np.nan)
    vod_ret = np.full(nt, np.nan)

    for k in range(nt):
        if not valid_tau[k] or not np.isfinite(omega_series[k]):
            continue

        # 逐样本 h/alpha（对应 Matlab L1332-1333: pick_one）
        hk = h_star_series[k] if np.isfinite(h_star_series[k]) else h_star
        ak = alpha_series[k] if np.isfinite(alpha_series[k]) else alpha_star

        model_ctx_k = _tb_ctx_for_theta(float(ia[k]))

        if use_dual:
            sm_val, vod_val = _ddca_dual_temp(
                float(tbv[k]),
                float(tbh[k]),
                float(tc[k]),
                float(tg[k]),
                float(tau_star[k]),
                float(hk),
                clay_fraction,
                float(omega_series[k]),
                porosity,
                freq_ghz,
                float(ia[k]),
                float(ak),
                config.lambda_tau,
                model_ctx_k,
            )
        else:
            sm_val, vod_val = _ddca_single_temp(
                float(tbv[k]),
                float(tbh[k]),
                float(ts[k]),
                float(tau_star[k]),
                float(hk),
                clay_fraction,
                float(omega_series[k]),
                porosity,
                freq_ghz,
                float(ia[k]),
                float(ak),
                config.lambda_tau,
                model_ctx_k,
            )
        if np.isfinite(sm_val):
            sm_ret[k] = sm_val
        if np.isfinite(vod_val):
            vod_ret[k] = vod_val

    return sm_ret, vod_ret


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
    tc: np.ndarray | None = None,
    tsoil1: np.ndarray | None = None,
    tsoil2: np.ndarray | None = None,
) -> PixelResult | None:
    """单像元 SF 块反演核心。

    对应 Matlab ``run_one_pixel_core_preloaded`` (L928-1424)。

    流程：
        Step 0: 逐日 Tau 计算
        Step 1: 低 τ 样本 → h/alpha 反演
        Step 2: OMEGA 识别（块级优化或固定值）
        Step 3: 逐日 SM/VOD 反演（DDCA）

    Args:
        tbv, tbh, ia, ts: 时间序列亮温/角度/温度 (Nt,)（ts 仅 ORIG_TS 使用）
        sm_ref: 参考土壤水分 (Nt,)
        ndvi: NDVI 时间序列 (Nt,)
        sf_col: SF 时间序列 (Nt,)
        ndvi_max, ndvi_min: NDVI 气候态极值
        albedo, b_param, clay_fraction, porosity, h_static: 静态参数
        landcover: IGBP 类型
        config: OmegaSfConfig
        block_struct: 8 天块结构
        omega_fixed: 固定 OMEGA 值（PFT/PIXEL 模式）
        tc, tsoil1, tsoil2: DUAL 温度方案 GLDAS 三温度序列 (Nt,)

    Returns:
        PixelResult 或 None（反演失败时）
    """
    nt = len(tbv)
    freq = config.freq_ghz
    use_dual = config.temp_scheme.upper() == "DUAL"

    # Mironov / TB 模型要求 clay∈[0,1]；辅助库陆地掩膜外常为 NaN，应跳过而非抛错
    if (
        not np.isfinite(clay_fraction)
        or clay_fraction < 0.0
        or clay_fraction > 1.0
        or not np.isfinite(porosity)
    ):
        return None

    # ── DUAL：由 Tsoil1/Tsoil2 合成 Ct/TG 序列（PAPER_CT 幂律或子模式） ──
    tc_series = np.full(nt, np.nan)
    tg_series = np.full(nt, np.nan)
    if use_dual:
        from ingest.daily_bundle import build_effective_soil_temperature_scheme

        tc_series = np.asarray(
            tc if tc is not None else np.full(nt, np.nan), dtype=np.float64
        )
        t1 = np.asarray(
            tsoil1 if tsoil1 is not None else np.full(nt, np.nan), dtype=np.float64
        )
        t2 = np.asarray(
            tsoil2 if tsoil2 is not None else np.full(nt, np.nan), dtype=np.float64
        )
        _ct_series, _tg_series = build_effective_soil_temperature_scheme(
            sm_ref,
            t1,
            t2,
            dual_tg_mode=config.dual_tg_mode,
            ct_smref=config.ct_smref,
            ct_exp=config.ct_exp,
        )
        tg_series = np.asarray(_tg_series, dtype=np.float64)

    # ── Step 0: Tau (delegated) ──
    tau_star = _step0_compute_tau_star(
        ndvi, ia, sf_col, ndvi_max, ndvi_min, landcover, b_param, nt
    )

    # ── 有效性判断 ──
    if use_dual:
        # DUAL：温度有效性改为 TC+TG（TG 依赖 sm_ref/Tsoil1/Tsoil2）
        ok_base = (
            np.isfinite(tbv)
            & np.isfinite(tbh)
            & np.isfinite(sm_ref)
            & np.isfinite(ndvi)
            & np.isfinite(ia)
            & np.isfinite(tc_series)
            & np.isfinite(tg_series)
        )
    else:
        ok_base = (
            np.isfinite(tbv)
            & np.isfinite(tbh)
            & np.isfinite(ts)
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

    # ── Step 1: h/alpha 联合优化（delegated） ──
    # omega_low：低 τ 模式的单次散射反照率
    # 对应 Matlab L1033-1037: omega_low = omega_fixed (Exp1b) or ALB_ij
    omega_low = float(omega_fixed) if omega_fixed is not None else albedo

    h_star, alpha_star, h_star_series, alpha_series = _step1_invert_halpha(
        tbv,
        tbh,
        ts,
        tau_star,
        sm_ref,
        ia,
        low_tau,
        valid_tau,
        clay_fraction,
        freq,
        omega_low,
        h_static,
        config,
        tc=tc_series if use_dual else None,
        tg=tg_series if use_dual else None,
    )

    if not np.isfinite(h_star) or not np.isfinite(alpha_star):
        return None

    # ── Step 2: OMEGA 块识别（逐样本 h/alpha + 时间平滑） ──
    # 对应 Matlab L1194-1245: 逐块 lsqnonlin(resid_omega_block_single_temp, ...)
    omega_series = np.full(nt, np.nan)

    if omega_fixed is not None:
        # 固定 OMEGA 模式
        omega_series[valid_tau] = omega_fixed
    else:
        omega_prev = float("nan")
        prev_blk_start = None

        # V/H 极化权重（EQUAL 模式：wV=wH=1）
        from scipy.optimize import least_squares

        w_v = 1.0
        w_h = 1.0

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
            tc_blk = tc_series[blk_use].astype(np.float64)
            tg_blk = tg_series[blk_use].astype(np.float64)

            model_ctx_blk = build_tb_model_context(freq, clay_fraction, 40.0)

            if use_dual:

                def _resid_omega(om):
                    return _resid_omega_block_dual_temp(
                        float(om[0]) if hasattr(om, "__len__") else float(om),
                        tbv_blk,
                        tbh_blk,
                        tc_blk,
                        tg_blk,
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
            else:

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
                    max_nfev=100,
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

    # ── Step 3: 逐日 SM/VOD（delegated） ──
    sm_ret, vod_ret = _step3_ddca_retrieval(
        tbv,
        tbh,
        ts,
        ia,
        tau_star,
        valid_tau,
        omega_series,
        h_star_series,
        alpha_series,
        h_star,
        alpha_star,
        clay_fraction,
        porosity,
        freq,
        config,
        tc=tc_series if use_dual else None,
        tg=tg_series if use_dual else None,
    )

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


def _forward_tb_dual(
    sm: float,
    tau: float,
    omega: float,
    h: float,
    tc: float,
    tg: float,
    clay_fraction: float,
    theta_deg: float,
    freq_ghz: float,
    model_ctx: TbModelContext,
    alpha: float | None = None,
) -> tuple[float, float]:
    """双温度前向 TB 模型：冠层温度 TC 与有效土壤温度 TG 分离。

    对应 Matlab ``tb_forward_dual_temp`` (L2245-2255)：
        TBv = C·( TG·(1-rv_r)·γ + TC·(1-ω)·(1-γ)·(1+rv_r·γ) )
    与单温度版共用 Mironov 介电 + Fresnel + 粗糙度（Q=max(alpha·h,0)），
    仅发射项由 Ts 单一乘子改为 TG(土壤)/TC(冠层) 两项加权和。

    Args:
        tc: 冠层温度（GLDAS Ts_gldas，K）
        tg: 有效土壤温度（由 Tsoil1/Tsoil2 按 Ct 合成，K）

    Returns:
        (TBv, TBh) 模型亮温
    """
    from algorithms.physics import (
        build_fresnel_context,
        fresnel_reflectance_from_context,
        mironov_dielectric_from_context,
    )

    if any(np.isnan([sm, tau, omega, h, tc, tg, theta_deg, clay_fraction])):
        return float("nan"), float("nan")
    if tau < 0.0 or h < 0.0:
        return float("nan"), float("nan")

    try:
        epsilon = mironov_dielectric_from_context(sm, model_ctx.dielectric)
        fresnel_ctx = build_fresnel_context(theta_deg)
        if fresnel_ctx.cos_theta <= 1e-12:
            return float("nan"), float("nan")
        rh, rv = fresnel_reflectance_from_context(epsilon, fresnel_ctx)
        if not (np.isfinite(rh) and np.isfinite(rv)):
            return float("nan"), float("nan")

        alpha_eff = float(alpha) if alpha is not None else 0.1771
        q_value = max(alpha_eff * h, 0.0)
        exp_term = math.exp(-h * fresnel_ctx.cos_theta_sq)
        rh_r = ((1.0 - q_value) * rh + q_value * rv) * exp_term
        rv_r = ((1.0 - q_value) * rv + q_value * rh) * exp_term

        gamma = math.exp(-tau)
        one_minus_gamma = -math.expm1(-tau)
        canopy_factor = (1.0 - omega) * one_minus_gamma

        # C=1.0；土壤发射项乘 TG，冠层发射/散射项乘 TC
        tbv = tg * ((1.0 - rv_r) * gamma) + tc * (canopy_factor * (1.0 + rv_r * gamma))
        tbh = tg * ((1.0 - rh_r) * gamma) + tc * (canopy_factor * (1.0 + rh_r * gamma))

        if not (math.isfinite(tbv) and math.isfinite(tbh)):
            return float("nan"), float("nan")
        return float(tbv), float(tbh)
    except (ValueError, OverflowError, FloatingPointError):
        return float("nan"), float("nan")


def _resid_halpha_dual_temp(
    x: np.ndarray,
    tbv: np.ndarray,
    tbh: np.ndarray,
    tc: np.ndarray,
    tg: np.ndarray,
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
    """h/alpha 联合优化残差函数（双温度方案）。

    对应 Matlab ``resid_halpha_dual_temp`` (L2195-2206)。
    结构与单温度版一致，仅前向算子换成 ``_forward_tb_dual``。
    """
    h_val = float(x[0])
    alpha_val = float(x[1])
    k = len(tbv)
    sv = math.sqrt(w_v)
    sh = math.sqrt(w_h)
    r = np.zeros(2 * k + 1)
    for i in range(k):
        tbv_m, tbh_m = _forward_tb_dual(
            float(sm_ref[i]),
            float(tau[i]),
            omega_low,
            h_val,
            float(tc[i]),
            float(tg[i]),
            clay_fraction,
            float(theta[i]),
            freq_ghz,
            model_ctx,
            alpha=alpha_val,
        )
        r[2 * i] = sv * (tbv_m - float(tbv[i]))
        r[2 * i + 1] = sh * (tbh_m - float(tbh[i]))
    r[-1] = math.sqrt(lam_alpha) * (alpha_val - alpha0)
    return r


def _resid_omega_block_dual_temp(
    omega: float,
    tbv: np.ndarray,
    tbh: np.ndarray,
    tc: np.ndarray,
    tg: np.ndarray,
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
    """OMEGA 块识别残差函数（双温度方案）。

    对应 Matlab ``resid_omega_block_dual_temp`` (L2208-2222)。
    逐样本 h/alpha + 可选时间平滑尾项 sqrt(lam_smooth)·(ω-ω_prev)。
    """
    k = len(tbv)
    sv = math.sqrt(w_v)
    sh = math.sqrt(w_h)
    rvh = np.zeros(2 * k)
    for i in range(k):
        tbv_m, tbh_m = _forward_tb_dual(
            float(sm_ref[i]),
            float(tau[i]),
            omega,
            float(h_series[i]),
            float(tc[i]),
            float(tg[i]),
            clay_fraction,
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


def _f_sm_dual_temp(
    x: np.ndarray,
    tbv: float,
    tbh: float,
    tc: float,
    tg: float,
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
    """DDCA 残差函数（双温度方案，alpha 依赖 Q）。

    对应 Matlab ``F_sm_dual_temp`` (L2231-2243)。
    """
    sm = float(x[0])
    tau = float(x[1])
    tbv_m, tbh_m = _forward_tb_dual(
        sm,
        tau,
        omega,
        h,
        tc,
        tg,
        clay_fraction,
        theta_deg,
        freq_ghz,
        model_ctx,
        alpha=alpha,
    )
    return [tbv_m - tbv, tbh_m - tbh, lambda_tau * (tau - tau_ini)]


def _ddca_dual_temp(
    tbv: float,
    tbh: float,
    tc: float,
    tg: float,
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
    """DDCA SM/VOD 反演（双温度方案，alpha 依赖 Q）。

    对应 Matlab ``DDCA_dual_temp`` (L2224-2229)：lsqnonlin → least_squares，
    初始 [0.20, Tau_ini]，边界 [0.02,0]~[porosity,5]。

    Returns:
        (SM, VOD) 反演结果
    """
    from scipy.optimize import least_squares

    if any(
        math.isnan(v)
        for v in [
            tbv,
            tbh,
            tc,
            tg,
            tau_ini,
            h,
            clay_fraction,
            omega,
            porosity,
            theta_deg,
        ]
    ):
        return float("nan"), float("nan")

    def residual(x):
        return _f_sm_dual_temp(
            x,
            tbv,
            tbh,
            tc,
            tg,
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


def _build_bbox_lin_mask(
    anc: dict[str, np.ndarray],
    nrows: int,
    ncols: int,
    config: OmegaSfConfig,
) -> np.ndarray | None:
    """根据 config.bbox_* 构建 (npix,) 布尔掩膜；未配置 bbox 时返回 None。"""
    if (
        config.bbox_west is None
        or config.bbox_south is None
        or config.bbox_east is None
        or config.bbox_north is None
    ):
        return None
    lat = anc.get("lat")
    lon = anc.get("lon")
    if lat is None or lon is None:
        logger.warning("[BBOX] 已配置 bbox 但辅助库缺少 lat/lon，忽略空间裁剪")
        return None
    lat_f = np.asarray(lat, dtype=np.float64).ravel()
    lon_f = np.asarray(lon, dtype=np.float64).ravel()
    npix = nrows * ncols
    if lat_f.size != npix or lon_f.size != npix:
        logger.warning(
            "[BBOX] lat/lon 大小 (%d,%d) != npix %d，忽略空间裁剪",
            lat_f.size,
            lon_f.size,
            npix,
        )
        return None
    mask = (
        (lat_f >= float(config.bbox_south))
        & (lat_f <= float(config.bbox_north))
        & (lon_f >= float(config.bbox_west))
        & (lon_f <= float(config.bbox_east))
    )
    logger.info(
        "[BBOX] 裁剪 [%s,%s]x[%s,%s] → %d/%d 像元",
        config.bbox_west,
        config.bbox_east,
        config.bbox_south,
        config.bbox_north,
        int(mask.sum()),
        npix,
    )
    return mask


def _emit_progress(
    progress_callback: Any,
    *,
    processed: int,
    total: int,
    chunks_done: int,
    chunks_total: int,
    pixels_done: int,
    pixels_total: int,
    phase: str,
    blocks_done: int | None = None,
    blocks_total: int | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    block_idx: int | None = None,
    block_dir: str | None = None,
) -> None:
    if not progress_callback:
        return
    detail: dict[str, Any] = {
        "chunks_done": chunks_done,
        "chunks_total": chunks_total,
        "pixels_done": pixels_done,
        "pixels_total": pixels_total,
        "phase": phase,
    }
    if blocks_done is not None:
        detail["blocks_done"] = int(blocks_done)
    if blocks_total is not None:
        detail["blocks_total"] = int(blocks_total)
    if date_start:
        detail["date_start"] = str(date_start)
    if date_end:
        detail["date_end"] = str(date_end)
    if block_idx is not None:
        detail["block_idx"] = int(block_idx)
    if block_dir:
        detail["block_dir"] = str(block_dir)
    try:
        progress_callback(processed, total, detail)
    except TypeError:
        progress_callback(processed, total)


class OmegaSfCancelled(InterruptedError):
    """用户取消：协作式停止 omega_sf 反演。"""


def _check_cancel_requested(cancel_flag_path: str | Path | None) -> None:
    if not cancel_flag_path:
        return
    if Path(cancel_flag_path).exists():
        raise OmegaSfCancelled("omega_sf cancelled by user (cancel.requested)")


def _checkpoint_path(output_dir: str | Path) -> Path:
    # G4-02: pickle.load → safe deserialization 防 RCE
    # 扩展名由 .pkl 改为 .json，旧 .pkl 检查点将被忽略（安全降级，非数据丢失）。
    return Path(output_dir) / ".omega_sf_chunk_checkpoint.json"


def _chunks_checkpoint_dir(output_dir: str | Path) -> Path:
    """P3 增量 checkpoint（2026-08-23）：每 chunk 一个文件的目录。

    旧单文件全量重写是 O(N·chunks) 总 IO（每 chunk 完成都重序列化全部
    结果），且 JSON 全量超 500MB 即失效拒载。增量目录下每 chunk 只写
    自身结果（O(N) 总 IO），单文件只有几 MB。
    """
    return Path(output_dir) / ".omega_sf_chunks"


def _chunks_meta_path(chunks_dir: Path) -> Path:
    return chunks_dir / "meta.json"


def _chunk_file_path(chunks_dir: Path, chunk_index: int) -> Path:
    return chunks_dir / f"chunk_{int(chunk_index):04d}.json"


def _assert_checkpoint_path_safe(path: Path, output_dir: str | Path) -> Path:
    """G4-02: 校验检查点路径归属，防止路径遍历导致加载外部恶意文件。

    确保解析后的 ``path`` 严格位于 ``output_dir`` 目录内（或等于该目录本身）。
    """
    base = Path(output_dir).resolve()
    resolved = path.resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError(f"Checkpoint path {resolved} is outside output_dir {base}")
    return resolved


def _pixel_result_to_jsonable(r: PixelResult) -> dict[str, Any]:
    """将 PixelResult 转为 JSON 可序列化的纯字典。"""
    return {
        "iy": int(r.iy),
        "ix": int(r.ix),
        "class_id": int(r.class_id),
        "omega": np.asarray(r.omega, dtype=np.float64).tolist(),
        "sm": np.asarray(r.sm, dtype=np.float64).tolist(),
        "vod": np.asarray(r.vod, dtype=np.float64).tolist(),
        "h_star": float(r.h_star),
        "alpha_star": float(r.alpha_star),
    }


def _jsonable_to_pixel_result(d: dict[str, Any]) -> PixelResult:
    """从 JSON 字典重建 PixelResult。"""
    return PixelResult(
        iy=int(d["iy"]),
        ix=int(d["ix"]),
        class_id=int(d["class_id"]),
        omega=np.asarray(d.get("omega") or [], dtype=np.float64),
        sm=np.asarray(d.get("sm") or [], dtype=np.float64),
        vod=np.asarray(d.get("vod") or [], dtype=np.float64),
        h_star=float(d.get("h_star", float("nan"))),
        alpha_star=float(d.get("alpha_star", float("nan"))),
    )


def _load_chunk_checkpoint(
    output_dir: str | Path,
    *,
    start_date: str,
    end_date: str,
) -> tuple[set[int], list[Any]] | None:
    """加载块/chunk 检查点；日期范围不一致则忽略。

    P3 增量化（2026-08-23）：优先读 ``.omega_sf_chunks/`` 增量目录（每 chunk
    一个文件）；旧单文件 ``.omega_sf_chunk_checkpoint.json`` 仍兼容读取——
    读到后 rename 为 ``.done`` 防重复消费（旧结果并入内存 all_results，
    completed 集合防重跑；增量保存只写新完成 chunk 的文件，二者键不同不冲突）。

    G4-02: pickle.load → safe deserialization 防 RCE
    使用 json.load 替代 pickle.load，JSON 无法携带可执行代码，
    从根本上消除反序列化 RCE 风险。同时校验路径归属，防止路径遍历。
    """
    done: set[int] = set()
    results: list[Any] = []
    loaded_any = False

    # ── 1) 增量目录（新格式）─────────────────────────────────────────
    chunks_dir = _chunks_checkpoint_dir(output_dir)
    if chunks_dir.is_dir():
        try:
            _assert_checkpoint_path_safe(chunks_dir, output_dir)
            meta_path = _chunks_meta_path(chunks_dir)
            if meta_path.is_file():
                with meta_path.open("r", encoding="utf-8") as fh:
                    meta = json.load(fh)
                if (
                    isinstance(meta, dict)
                    and meta.get("start_date") == start_date
                    and meta.get("end_date") == end_date
                ):
                    # 单个 chunk 文件仅几 MB；500MB 防御上限针对整个目录
                    for cf in sorted(chunks_dir.glob("chunk_*.json")):
                        if cf.stat().st_size > 500 * 1024 * 1024:
                            logger.warning(
                                "[CHECKPOINT] chunk 文件异常过大，跳过: %s", cf
                            )
                            continue
                        with cf.open("r", encoding="utf-8") as fh:
                            payload = json.load(fh)
                        if not isinstance(payload, dict):
                            continue
                        ci = payload.get("chunk_index")
                        if not isinstance(ci, int):
                            continue
                        done.add(ci)
                        for r in payload.get("results") or []:
                            if isinstance(r, dict):
                                results.append(_jsonable_to_pixel_result(r))
                        loaded_any = True
        except Exception:
            logger.warning(
                "[CHECKPOINT] 增量目录加载失败，忽略: %s", chunks_dir, exc_info=True
            )
            done, results, loaded_any = set(), [], False

    # ── 2) 旧单文件（兼容迁移）───────────────────────────────────────
    path = _checkpoint_path(output_dir)
    if path.exists():
        try:
            _assert_checkpoint_path_safe(path, output_dir)
            if path.stat().st_size > 500 * 1024 * 1024:
                logger.warning(
                    "[CHECKPOINT] 检查点文件异常过大（%d bytes），跳过加载",
                    path.stat().st_size,
                )
            else:
                with path.open("r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                if isinstance(payload, dict) and (
                    payload.get("start_date") == start_date
                    and payload.get("end_date") == end_date
                ):
                    done.update(int(i) for i in (payload.get("completed_chunks") or []))
                    raw_results = payload.get("all_results") or []
                    results.extend(
                        _jsonable_to_pixel_result(r) if isinstance(r, dict) else r
                        for r in raw_results
                    )
                    loaded_any = True
                # 已消费的旧文件改名防重复（结果已在内存，增量保存不会重写它）
                migrated = path.with_suffix(path.suffix + ".done")
                with contextlib.suppress(OSError):
                    os.replace(path, migrated)
        except Exception:
            logger.warning("[CHECKPOINT] 旧格式加载失败，忽略: %s", path, exc_info=True)

    if not loaded_any:
        return None
    return done, results


def _append_chunk_checkpoint(
    output_dir: str | Path,
    *,
    start_date: str,
    end_date: str,
    chunk_index: int,
    chunk_results: list[Any],
) -> None:
    """P3 增量保存：只写本 chunk 的结果文件（O(单 chunk)）。

    替代旧 ``_save_chunk_checkpoint`` 的全量重写（O(全部累积结果)/次）。
    meta.json 只在目录首次创建时写一次（日期窗口标识）；chunk 文件
    tmp+os.replace 原子落盘。
    """
    chunks_dir = _chunks_checkpoint_dir(output_dir)
    try:
        _assert_checkpoint_path_safe(chunks_dir, output_dir)
    except ValueError:
        logger.warning("[CHECKPOINT] 路径归属校验失败，跳过增量写入: %s", chunks_dir)
        return
    try:
        chunks_dir.mkdir(parents=True, exist_ok=True)
        meta_path = _chunks_meta_path(chunks_dir)
        if not meta_path.exists():
            # tmp 名含 uuid：同 pid 多线程（节点级并行若未来波及 chunk 循环）
            # 下唯一化，避免交错写损坏（回顾审查 2026-08-23）
            meta_tmp = meta_path.with_suffix(
                meta_path.suffix + f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
            )
            with meta_tmp.open("w", encoding="utf-8") as fh:
                json.dump({"start_date": start_date, "end_date": end_date}, fh)
            os.replace(meta_tmp, meta_path)

        chunk_path = _chunk_file_path(chunks_dir, chunk_index)
        tmp_path = chunk_path.with_suffix(
            chunk_path.suffix + f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
        )
        payload = {
            "chunk_index": int(chunk_index),
            "results": [
                _pixel_result_to_jsonable(r) if isinstance(r, PixelResult) else r
                for r in chunk_results
            ],
        }
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, allow_nan=True)
        os.replace(tmp_path, chunk_path)
    except Exception:
        logger.warning(
            "[CHECKPOINT] 增量写入失败（chunk %d）: %s",
            chunk_index,
            chunks_dir,
            exc_info=True,
        )


def _cleanup_chunk_checkpoint(output_dir: str | Path) -> None:
    """成功完成后清理检查点（增量目录 + 旧单文件及其 .done 迁移残留）。

    此前成功后检查点永久残留（下次同日期运行会误 resume 到旧结果
    之外的重复计算窗口）。
    """
    import shutil

    chunks_dir = _chunks_checkpoint_dir(output_dir)
    with contextlib.suppress(OSError):
        shutil.rmtree(chunks_dir, ignore_errors=True)
    legacy = _checkpoint_path(output_dir)
    for suffix in ("", ".done"):
        with contextlib.suppress(OSError):
            legacy.with_suffix(legacy.suffix + suffix).unlink(missing_ok=True)


def _assemble_block_grids(
    all_results: list[PixelResult],
    block_struct: BlockStructure,
    grid_shape: tuple[int, int],
) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray], dict[int, np.ndarray]]:
    """从像元结果组装块级 SM/VOD/OMEGA 网格。"""
    nrows, ncols = grid_shape
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

    return sm_maps, vod_maps, omega_maps


def _save_one_block_mat(
    out_path: Path,
    *,
    blk_idx: int,
    block_struct: BlockStructure,
    sm_grid: np.ndarray,
    vod_grid: np.ndarray,
    om_grid: np.ndarray,
) -> tuple[str, str, str]:
    """写入单个块 mat，返回 (path, date_start, date_end)。"""
    from scipy.io import savemat

    blk_start = block_struct.starts[blk_idx]
    blk_end = block_struct.ends[blk_idx]
    date_start_str = blk_start.strftime("%Y%m%d")
    date_end_str = blk_end.strftime("%Y%m%d")
    blk_file = out_path / f"{date_start_str}_{date_end_str}.mat"
    payload = {
        "SM": sm_grid,
        "VOD": vod_grid,
        "OMEGA": om_grid,
        "block_start": str(blk_start),
        "block_end": str(blk_end),
        "block_idx": blk_idx,
        "date_start": date_start_str,
        "date_end": date_end_str,
    }
    savemat(str(blk_file), payload)
    compat = out_path / f"block_{blk_idx:03d}.mat"
    savemat(str(compat), payload)
    return str(blk_file), date_start_str, date_end_str


def _persist_block_maps(
    output_dir: str | Path | None,
    *,
    block_struct: BlockStructure,
    sm_maps: dict[int, np.ndarray],
    vod_maps: dict[int, np.ndarray],
    omega_maps: dict[int, np.ndarray],
    progress_callback: Any = None,
    processed: int = 0,
    total: int = 0,
    chunks_done: int = 0,
    chunks_total: int = 0,
    pixels_done: int = 0,
    pixels_total: int = 0,
    finalize: bool = False,
) -> dict[str, str]:
    """按块顺序写盘并逐块发 progress（phase=block_commit）。"""
    output_paths: dict[str, str] = {}
    if not output_dir:
        return output_paths
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    n_blocks = len(sm_maps)
    for i, blk_idx in enumerate(sorted(sm_maps.keys())):
        path, d0, d1 = _save_one_block_mat(
            out_path,
            blk_idx=blk_idx,
            block_struct=block_struct,
            sm_grid=sm_maps[blk_idx],
            vod_grid=vod_maps[blk_idx],
            om_grid=omega_maps[blk_idx],
        )
        output_paths[f"block_{blk_idx:03d}"] = path
        output_paths[f"{d0}_{d1}"] = path
        _emit_progress(
            progress_callback,
            processed=processed,
            total=total,
            chunks_done=chunks_done,
            chunks_total=chunks_total,
            pixels_done=pixels_done,
            pixels_total=pixels_total,
            phase="block_commit" if finalize else "block_refresh",
            blocks_done=i + 1,
            blocks_total=n_blocks,
            date_start=d0,
            date_end=d1,
            block_idx=blk_idx,
            block_dir=str(out_path),
        )
    output_paths["block_dir"] = str(out_path)
    return output_paths


def _invert_omega_sf_pixel_indices(
    local_indices: list[int],
    *,
    lin_pix: np.ndarray,
    ncols: int,
    npix: int,
    tbv: np.ndarray,
    tbh: np.ndarray,
    ia: np.ndarray,
    ts: np.ndarray,
    sm_ref: np.ndarray,
    ndvi: np.ndarray,
    sf: np.ndarray,
    ndvi_v_max_arr: np.ndarray,
    ndvi_v_min_arr: np.ndarray,
    albedo_flat: np.ndarray,
    b_flat: np.ndarray,
    clay_flat: np.ndarray,
    porosity_flat: np.ndarray,
    h_flat: np.ndarray,
    landcover_flat: np.ndarray,
    omega_fixed_map: np.ndarray | None,
    config: OmegaSfConfig,
    block_struct: BlockStructure,
    tc: np.ndarray | None = None,
    tsoil1: np.ndarray | None = None,
    tsoil2: np.ndarray | None = None,
) -> tuple[list[PixelResult], int, int]:
    """串行处理一批局部像元索引（模块级，可供 ProcessPool pickle）。

    tc/tsoil1/tsoil2 为 DUAL 温度方案 (Nt, chunk_pix) 数组（ORIG_TS 传 None）。

    Returns:
        (成功结果列表, 尝试数, 失败数)
    """
    results: list[PixelResult] = []
    n_ok = 0
    n_fail = 0
    for p in local_indices:
        lin_idx = int(lin_pix[p])
        iy = lin_idx // ncols + 1
        ix = lin_idx % ncols + 1
        lc = int(landcover_flat[lin_idx]) if lin_idx < npix else 0
        omega_fixed = None
        if omega_fixed_map is not None and lin_idx < npix:
            omega_fixed = float(omega_fixed_map[lc])
        try:
            result = execute_pixel_inversion(
                tbv=tbv[:, p],
                tbh=tbh[:, p],
                ia=ia[:, p],
                ts=ts[:, p],
                sm_ref=sm_ref[:, p],
                ndvi=ndvi[:, p],
                sf_col=sf[:, p],
                ndvi_max=float(ndvi_v_max_arr[lin_idx])
                if lin_idx < len(ndvi_v_max_arr)
                else float("nan"),
                ndvi_min=float(ndvi_v_min_arr[lin_idx])
                if lin_idx < len(ndvi_v_min_arr)
                else float("nan"),
                albedo=float(albedo_flat[lin_idx]) if lin_idx < npix else float("nan"),
                b_param=float(b_flat[lin_idx]) if lin_idx < npix else float("nan"),
                clay_fraction=float(clay_flat[lin_idx])
                if lin_idx < npix
                else float("nan"),
                porosity=float(porosity_flat[lin_idx])
                if lin_idx < npix
                else float("nan"),
                h_static=float(h_flat[lin_idx]) if lin_idx < npix else float("nan"),
                landcover=lc,
                config=config,
                block_struct=block_struct,
                omega_fixed=omega_fixed,
                tc=tc[:, p] if tc is not None else None,
                tsoil1=tsoil1[:, p] if tsoil1 is not None else None,
                tsoil2=tsoil2[:, p] if tsoil2 is not None else None,
            )
        except ValueError:
            # 单像元物理约束失败（如 clay NaN）不拖垮整块并行/串行批次
            result = None
        n_ok += 1
        if result is not None:
            result.iy = iy
            result.ix = ix
            results.append(result)
        else:
            n_fail += 1
    return results, n_ok, n_fail


def _run_omega_sf_pixels_parallel(
    valid_local: list[int],
    *,
    process_count: int,
    lin_pix: np.ndarray,
    ncols: int,
    npix: int,
    chunk_data: dict[str, np.ndarray],
    ndvi_v_max_arr: np.ndarray,
    ndvi_v_min_arr: np.ndarray,
    albedo_flat: np.ndarray,
    b_flat: np.ndarray,
    clay_flat: np.ndarray,
    porosity_flat: np.ndarray,
    h_flat: np.ndarray,
    landcover_flat: np.ndarray,
    omega_fixed_map: np.ndarray | None,
    config: OmegaSfConfig,
    block_struct: BlockStructure,
) -> tuple[list[PixelResult], int, int]:
    """ProcessPoolExecutor 并行反演一批有效像元；异常向上抛出由调用方回退。"""
    import os
    from concurrent.futures import ALL_COMPLETED, ProcessPoolExecutor, wait

    from algorithms._parallel import get_spawn_context

    n = len(valid_local)
    if n == 0:
        return [], 0, 0

    # 按进程数切批，保证每进程至少有工作
    n_batches = min(process_count, n)
    batch_size = (n + n_batches - 1) // n_batches
    batches = [valid_local[i : i + batch_size] for i in range(0, n, batch_size)]

    env_val = os.environ.get("CGDA_PARALLEL_TIMEOUT_PER_CHUNK")
    try:
        timeout_per_batch = float(env_val) if env_val else 600.0
    except ValueError:
        timeout_per_batch = 600.0
    total_timeout = max(1.0, timeout_per_batch) * len(batches)

    common_kwargs = {
        "lin_pix": lin_pix,
        "ncols": ncols,
        "npix": npix,
        "tbv": chunk_data["tbv"],
        "tbh": chunk_data["tbh"],
        "ia": chunk_data["ia"],
        "ts": chunk_data["ts"],
        "sm_ref": chunk_data["sm_ref"],
        "ndvi": chunk_data["ndvi"],
        "sf": chunk_data["sf"],
        "ndvi_v_max_arr": ndvi_v_max_arr,
        "ndvi_v_min_arr": ndvi_v_min_arr,
        "albedo_flat": albedo_flat,
        "b_flat": b_flat,
        "clay_flat": clay_flat,
        "porosity_flat": porosity_flat,
        "h_flat": h_flat,
        "landcover_flat": landcover_flat,
        "omega_fixed_map": omega_fixed_map,
        "config": config,
        "block_struct": block_struct,
        "tc": chunk_data.get("tc"),
        "tsoil1": chunk_data.get("tsoil1"),
        "tsoil2": chunk_data.get("tsoil2"),
    }

    ctx = get_spawn_context()
    ex = ProcessPoolExecutor(max_workers=process_count, mp_context=ctx)
    try:
        futures = [
            ex.submit(_invert_omega_sf_pixel_indices, batch, **common_kwargs)
            for batch in batches
        ]
        done, not_done = wait(futures, timeout=total_timeout, return_when=ALL_COMPLETED)
        if not_done:
            for fut in not_done:
                fut.cancel()
            raise TimeoutError(
                f"omega_sf parallel timed out after {total_timeout:.0f}s "
                f"({len(not_done)}/{len(futures)} batches unfinished)"
            )
        all_results: list[PixelResult] = []
        n_attempted = 0
        n_failed = 0
        for fut in futures:
            res, n_ok, n_fail = fut.result()
            all_results.extend(res)
            n_attempted += n_ok
            n_failed += n_fail
        return all_results, n_attempted, n_failed
    finally:
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            ex.shutdown(wait=False)


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


@dataclass
class _ChunkLoopState:
    """主循环跨迭代可变状态（提取 _process_one_chunk 用）。

    原内联变量 all_results/n_processed/n_success/n_failed/n_valid_processed/
    completed_chunks 的可变容器。
    """

    all_results: list[PixelResult]
    n_processed: int = 0
    n_success: int = 0
    n_failed: int = 0
    n_valid_processed: int = 0
    completed_chunks: set[int] = field(default_factory=set)
    stop: bool = False  # max_valid_pixels 触发的提前终止


def _emit_diag_pixels(
    valid_local: list[int],
    lin_pix: np.ndarray,
    ncols: int,
    chunk_data: dict[str, np.ndarray],
    n_valid_processed: int,
) -> None:
    """诊断日志：前 3 个有效像元的 finite 计数 + range。"""
    for diag_i, p in enumerate(valid_local[:3]):
        if n_valid_processed + diag_i >= 3:
            break
        lin_idx = int(lin_pix[p])
        iy = lin_idx // ncols + 1
        ix = lin_idx % ncols + 1
        _tbv = chunk_data["tbv"][:, p]
        _tbh = chunk_data["tbh"][:, p]
        _ia = chunk_data["ia"][:, p]
        _ts = chunk_data["ts"][:, p]
        _sm = chunk_data["sm_ref"][:, p]
        _ndvi = chunk_data["ndvi"][:, p]
        _sf = chunk_data["sf"][:, p]
        logger.warning(
            "[DIAG PIX %d] iy=%d ix=%d | "
            "tbv_finite=%d/%d tbh_finite=%d/%d ia_finite=%d/%d "
            "ts_finite=%d/%d sm_finite=%d/%d ndvi_finite=%d/%d "
            "sf_finite=%d/%d | sm_range=[%.3f,%.3f] ndvi_range=[%.3f,%.3f] "
            "sf_range=[%.3f,%.3f]",
            n_valid_processed + diag_i + 1,
            iy,
            ix,
            int(np.isfinite(_tbv).sum()),
            len(_tbv),
            int(np.isfinite(_tbh).sum()),
            len(_tbh),
            int(np.isfinite(_ia).sum()),
            len(_ia),
            int(np.isfinite(_ts).sum()),
            len(_ts),
            int(np.isfinite(_sm).sum()),
            len(_sm),
            int(np.isfinite(_ndvi).sum()),
            len(_ndvi),
            int(np.isfinite(_sf).sum()),
            len(_sf),
            float(np.nanmin(_sm)) if np.any(np.isfinite(_sm)) else float("nan"),
            float(np.nanmax(_sm)) if np.any(np.isfinite(_sm)) else float("nan"),
            float(np.nanmin(_ndvi)) if np.any(np.isfinite(_ndvi)) else float("nan"),
            float(np.nanmax(_ndvi)) if np.any(np.isfinite(_ndvi)) else float("nan"),
            float(np.nanmin(_sf)) if np.any(np.isfinite(_sf)) else float("nan"),
            float(np.nanmax(_sf)) if np.any(np.isfinite(_sf)) else float("nan"),
        )


def _run_pixel_inversion(
    valid_local: list[int],
    lin_pix: np.ndarray,
    ncols: int,
    npix: int,
    chunk_data: dict[str, np.ndarray],
    anc: dict[str, np.ndarray],
    landcover: np.ndarray,
    block_struct: BlockStructure,
    ndvi_v_max_arr: np.ndarray,
    ndvi_v_min_arr: np.ndarray,
    omega_fixed_map: np.ndarray | None,
    config: OmegaSfConfig,
    ci: int,
    n_chunks: int,
) -> tuple[list[PixelResult], int, int]:
    """逐像元反演：并行或串行，含并行失败回退。

    Returns:
        (batch_results, n_attempted, n_batch_failed)
    """
    use_parallel = bool(config.enable_parallel) and len(valid_local) >= 8
    process_count = 1
    if use_parallel:
        try:
            from algorithms._parallel import auto_process_count

            process_count = auto_process_count(
                chunk_count=len(valid_local),
                max_workers=config.max_workers,
            )
        except Exception as exc:
            logger.warning("[PARALLEL] auto_process_count failed: %s", exc)
            process_count = 1
        use_parallel = process_count > 1

    albedo_flat = anc["albedo"].ravel()
    b_flat = anc["b"].ravel()
    clay_flat = anc["clay"].ravel()
    porosity_flat = anc["porosity"].ravel()
    h_flat = anc["h"].ravel()
    landcover_flat = landcover.ravel()

    if use_parallel:
        logger.info(
            "[PARALLEL] chunk %d/%d：%d 像元，%d 进程",
            ci + 1,
            n_chunks,
            len(valid_local),
            process_count,
        )
        try:
            return _run_omega_sf_pixels_parallel(
                valid_local,
                process_count=process_count,
                lin_pix=lin_pix,
                ncols=ncols,
                npix=npix,
                chunk_data=chunk_data,
                ndvi_v_max_arr=ndvi_v_max_arr,
                ndvi_v_min_arr=ndvi_v_min_arr,
                albedo_flat=albedo_flat,
                b_flat=b_flat,
                clay_flat=clay_flat,
                porosity_flat=porosity_flat,
                h_flat=h_flat,
                landcover_flat=landcover_flat,
                omega_fixed_map=omega_fixed_map,
                config=config,
                block_struct=block_struct,
            )
        except Exception as exc:
            logger.warning("[PARALLEL] 失败，回退串行：%s", exc, exc_info=True)

    return _invert_omega_sf_pixel_indices(
        valid_local,
        lin_pix=lin_pix,
        ncols=ncols,
        npix=npix,
        tbv=chunk_data["tbv"],
        tbh=chunk_data["tbh"],
        ia=chunk_data["ia"],
        ts=chunk_data["ts"],
        sm_ref=chunk_data["sm_ref"],
        ndvi=chunk_data["ndvi"],
        sf=chunk_data["sf"],
        ndvi_v_max_arr=ndvi_v_max_arr,
        ndvi_v_min_arr=ndvi_v_min_arr,
        albedo_flat=albedo_flat,
        b_flat=b_flat,
        clay_flat=clay_flat,
        porosity_flat=porosity_flat,
        h_flat=h_flat,
        landcover_flat=landcover_flat,
        omega_fixed_map=omega_fixed_map,
        config=config,
        block_struct=block_struct,
        tc=chunk_data.get("tc"),
        tsoil1=chunk_data.get("tsoil1"),
        tsoil2=chunk_data.get("tsoil2"),
    )


def _chunk_progressive_write(
    ci: int,
    chunk_lin_list: list[np.ndarray],
    state: _ChunkLoopState,
    block_struct: BlockStructure,
    grid_shape: tuple[int, int],
    npix: int,
    config: OmegaSfConfig,
    output_dir: str,
    max_valid_pixels: int,
    progress_callback: Any,
    reuse_block_cache: bool,
    chunk_results: list[Any] | None = None,
) -> None:
    """Checkpoint 保存 + 进度回调 + 渐进写盘。

    对应原 ``_process_one_chunk`` L2207–2246。

    Args:
        ci: chunk 索引
        chunk_lin_list: chunk 列表
        state: chunk 循环状态
        block_struct: 8 天块结构
        grid_shape: (nrows, ncols)
        npix: 总像元数
        config: OmegaSfConfig
        output_dir: 输出目录
        max_valid_pixels: 最大有效像元数
        progress_callback: 进度回调
        reuse_block_cache: 是否复用缓存
        chunk_results: 本 chunk 新增的像元结果（增量 checkpoint 用）
    """
    if reuse_block_cache and output_dir:
        # P3 增量化：只写本 chunk 结果文件（旧全量重写 O(N)/次 → O(单 chunk)/次）
        _append_chunk_checkpoint(
            output_dir,
            start_date=config.start_date,
            end_date=config.end_date,
            chunk_index=ci,
            chunk_results=chunk_results or [],
        )

    _emit_progress(
        progress_callback,
        processed=state.n_processed,
        total=npix,
        chunks_done=ci + 1,
        chunks_total=len(chunk_lin_list),
        pixels_done=state.n_valid_processed,
        pixels_total=max_valid_pixels or npix,
        phase="step2_omega",
    )

    # 渐进：每个空间 chunk 后按块写盘，供运行中上图
    if output_dir and state.all_results:
        sm_i, vod_i, om_i = _assemble_block_grids(
            state.all_results, block_struct, grid_shape
        )
        _persist_block_maps(
            output_dir,
            block_struct=block_struct,
            sm_maps=sm_i,
            vod_maps=vod_i,
            omega_maps=om_i,
            progress_callback=progress_callback,
            processed=state.n_processed,
            total=npix,
            chunks_done=ci + 1,
            chunks_total=len(chunk_lin_list),
            pixels_done=state.n_valid_processed,
            pixels_total=max_valid_pixels or npix,
            finalize=False,
        )


def _build_chunk_validity_mask(
    chunk_data: dict[str, np.ndarray],
    anc: dict[str, np.ndarray],
    lin_pix: np.ndarray,
    config: OmegaSfConfig | None = None,
) -> np.ndarray:
    """构建 chunk 有效像元掩码。

    检查 TBv/TBh/温度/SM_ref/NDVI 至少有一个有限值 + clay/porosity 有效。
    DUAL（temp_scheme=DUAL）时温度项改查 tc/tsoil1/tsoil2。
    对应原 ``_process_one_chunk`` L1990–2007。

    Args:
        chunk_data: _preload_chunk 返回的 dict（含 tbv/tbh/ts/sm_ref/ndvi）
        anc: 辅助库 dict（含 clay/porosity）
        lin_pix: 像元线性索引
        config: OmegaSfConfig（None 按 ORIG_TS 处理）

    Returns:
        valid_mask (chunk_pix,) bool 数组
    """
    tbv_chunk = chunk_data["tbv"]
    tbh_chunk = chunk_data["tbh"]
    sm_chunk = chunk_data["sm_ref"]
    ndvi_chunk = chunk_data["ndvi"]
    if config is not None and config.temp_scheme.upper() == "DUAL":
        temp_ok = (
            np.any(
                np.isfinite(chunk_data.get("tc", np.full_like(tbv_chunk, np.nan))),
                axis=0,
            )
            & np.any(
                np.isfinite(chunk_data.get("tsoil1", np.full_like(tbv_chunk, np.nan))),
                axis=0,
            )
            & np.any(
                np.isfinite(chunk_data.get("tsoil2", np.full_like(tbv_chunk, np.nan))),
                axis=0,
            )
        )
    else:
        temp_ok = np.any(np.isfinite(chunk_data["ts"]), axis=0)
    clay_chunk = anc["clay"].ravel()[lin_pix]
    porosity_chunk = anc["porosity"].ravel()[lin_pix]
    valid_mask = (
        np.any(np.isfinite(tbv_chunk), axis=0)
        & np.any(np.isfinite(tbh_chunk), axis=0)
        & temp_ok
        & np.any(np.isfinite(sm_chunk), axis=0)
        & np.any(np.isfinite(ndvi_chunk), axis=0)
        & np.isfinite(clay_chunk)
        & (clay_chunk >= 0.0)
        & (clay_chunk <= 1.0)
        & np.isfinite(porosity_chunk)
    )
    return valid_mask


def _process_one_chunk(
    ci: int,
    lin_pix: np.ndarray,
    chunk_lin_list: list[np.ndarray],
    state: _ChunkLoopState,
    *,
    tvec: list[datetime],
    nrows: int,
    ncols: int,
    npix: int,
    config: OmegaSfConfig,
    smap_folder: str,
    fy3d_folder: str,
    fy3b_folder: str,
    ndvi_clim_folder: str,
    ndvi_folder: str,
    anc: dict[str, np.ndarray],
    landcover: np.ndarray,
    block_struct: BlockStructure,
    ndvi_v_max_arr: np.ndarray,
    ndvi_v_min_arr: np.ndarray,
    omega_fixed_map: np.ndarray | None,
    max_valid_pixels: int,
    output_dir: str,
    progress_callback: Any,
    cancel_flag_path: str | Path | None,
    reuse_block_cache: bool,
    grid_shape: tuple[int, int],
    gldas_mat_folder: str = "",
    anc_root: str = "",
    gldas_template_mat: str = "",
) -> None:
    """处理单个 chunk：预读 → 像元反演 → 汇总 → checkpoint → 渐进写盘。

    对应原 ``retrieve_omega_sf_daily`` 主循环体（L1975-2262）。
    更新 state 的 all_results/n_processed/n_success/n_failed/n_valid_processed/
    completed_chunks；max_valid_pixels 达限时设 state.stop=True。
    """
    _check_cancel_requested(cancel_flag_path)
    if ci in state.completed_chunks:
        return
    chunk_pix = int(lin_pix.size)
    if chunk_pix == 0:
        state.completed_chunks.add(ci)
        return

    logger.info(
        "[CHUNK %d/%d] 像元索引 %d 个（lin %d..%d）",
        ci + 1,
        len(chunk_lin_list),
        chunk_pix,
        int(lin_pix[0]),
        int(lin_pix[-1]),
    )

    _emit_progress(
        progress_callback,
        processed=state.n_processed,
        total=npix,
        chunks_done=ci,
        chunks_total=len(chunk_lin_list),
        pixels_done=state.n_valid_processed,
        pixels_total=max_valid_pixels or npix,
        phase="preload",
    )

    # 预读 chunk 数据
    chunk_data = _preload_chunk(
        tvec,
        nrows,
        ncols,
        config,
        smap_folder,
        fy3d_folder,
        fy3b_folder,
        ndvi_clim_folder,
        ndvi_folder,
        anc,
        lin_pix=lin_pix,
        gldas_mat_folder=gldas_mat_folder,
        anc_root=anc_root,
        gldas_template_mat=gldas_template_mat,
    )

    _emit_progress(
        progress_callback,
        processed=state.n_processed,
        total=npix,
        chunks_done=ci,
        chunks_total=len(chunk_lin_list),
        pixels_done=state.n_valid_processed,
        pixels_total=max_valid_pixels or npix,
        phase="step2_omega",
    )

    # 逐像元反演：预计算有效像元掩码
    valid_mask = _build_chunk_validity_mask(chunk_data, anc, lin_pix)
    n_skip_chunk = int((~valid_mask).sum())
    if n_skip_chunk > 0:
        logger.info(
            "[CHUNK %d/%d] 跳过 %d 个无效像元（全 NaN），处理 %d 个",
            ci + 1,
            len(chunk_lin_list),
            n_skip_chunk,
            int(valid_mask.sum()),
        )

    valid_local = [int(p) for p in np.flatnonzero(valid_mask)]
    n_skip_chunk_count = chunk_pix - len(valid_local)
    state.n_processed += n_skip_chunk_count
    state.n_failed += n_skip_chunk_count

    # 诊断：前 3 个有效像元
    _emit_diag_pixels(valid_local, lin_pix, ncols, chunk_data, state.n_valid_processed)

    # 测试模式：截断到 max_pixels
    if max_valid_pixels > 0:
        remain = max_valid_pixels - state.n_valid_processed
        if remain <= 0:
            state.stop = True
            return
        if len(valid_local) > remain:
            valid_local = valid_local[:remain]

    batch_results, n_attempted, n_batch_failed = _run_pixel_inversion(
        valid_local,
        lin_pix,
        ncols,
        npix,
        chunk_data,
        anc,
        landcover,
        block_struct,
        ndvi_v_max_arr,
        ndvi_v_min_arr,
        omega_fixed_map,
        config,
        ci,
        len(chunk_lin_list),
    )

    state.all_results.extend(batch_results)
    state.n_processed += n_attempted
    state.n_valid_processed += n_attempted
    state.n_success += len(batch_results)
    state.n_failed += n_batch_failed
    state.completed_chunks.add(ci)
    _chunk_progressive_write(
        ci,
        chunk_lin_list,
        state,
        block_struct,
        grid_shape,
        npix,
        config,
        output_dir,
        max_valid_pixels,
        progress_callback,
        reuse_block_cache,
        chunk_results=list(batch_results),
    )

    # 测试模式：检查像元限制
    if max_valid_pixels > 0 and state.n_valid_processed >= max_valid_pixels:
        logger.warning(
            "[TEST MODE] 已达到像元限制 %d，停止处理",
            max_valid_pixels,
        )
        state.stop = True


def _pack_bbox_chunks(
    bbox_mask: np.ndarray,
    nrows: int,
    ncols: int,
    pack_size: int,
    max_valid_pixels: int,
) -> list[np.ndarray]:
    """bbox mask 像元打包为 chunk 列表（避免逐行重复 I/O）。

    含 max_valid_pixels 抽稀（均匀采样，避免只取北缘条带）。
    """
    idx = np.flatnonzero(bbox_mask).astype(np.int64, copy=False)
    if idx.size == 0:
        raise ValueError("bbox 内无有效像元（检查 lat/lon 与 bbox 配置）")
    ys, xs = np.unravel_index(idx, (nrows, ncols))
    ymin, ymax = int(ys.min()), int(ys.max())
    xmin, xmax = int(xs.min()), int(xs.max())
    row_width = xmax - xmin + 1
    if max_valid_pixels > 0 and idx.size > max_valid_pixels:
        step = float(idx.size) / float(max_valid_pixels)
        sel = (np.arange(max_valid_pixels) * step).astype(np.int64)
        sel = np.clip(sel, 0, idx.size - 1)
        idx = idx[sel]
    chunk_lin_list = [
        idx[i : i + pack_size] for i in range(0, int(idx.size), pack_size)
    ]
    logger.info(
        "[BBOX] 矩形行=%d..%d col=%d..%d → %d chunk（打包像元 %d，行宽 %d，"
        "按 mask 打包避免逐行重复 I/O）",
        ymin,
        ymax,
        xmin,
        xmax,
        len(chunk_lin_list),
        int(idx.size),
        row_width,
    )
    return chunk_lin_list


def _apply_chunk_test_env_vars(
    chunk_lin_list: list[np.ndarray],
    bbox_mask: np.ndarray | None,
) -> list[np.ndarray]:
    """应用 OMEGA_SF_CHUNK_OFFSET / OMEGA_SF_MAX_CHUNKS 测试模式裁剪。

    bbox 模式下两个 env var 都忽略（避免偏移到空区域）。
    """
    import os

    chunk_offset_env = os.environ.get("OMEGA_SF_CHUNK_OFFSET")
    if chunk_offset_env and bbox_mask is None:
        chunk_offset = int(chunk_offset_env)
        if chunk_offset > 0 and chunk_offset < len(chunk_lin_list):
            logger.warning(
                "[TEST MODE] 跳过前 %d 个 chunk（OMEGA_SF_CHUNK_OFFSET=%s），从 chunk %d 开始",
                chunk_offset,
                chunk_offset_env,
                chunk_offset + 1,
            )
            chunk_lin_list = chunk_lin_list[chunk_offset:]
    elif chunk_offset_env and bbox_mask is not None:
        logger.warning(
            "[TEST MODE] 已配置 bbox，忽略 OMEGA_SF_CHUNK_OFFSET=%s",
            chunk_offset_env,
        )

    max_chunks_env = os.environ.get("OMEGA_SF_MAX_CHUNKS")
    if max_chunks_env and bbox_mask is None:
        max_chunks = int(max_chunks_env)
        if max_chunks > 0 and max_chunks < len(chunk_lin_list):
            logger.warning(
                "[TEST MODE] 仅处理前 %d/%d 个 chunk（OMEGA_SF_MAX_CHUNKS=%s）",
                max_chunks,
                len(chunk_lin_list),
                max_chunks_env,
            )
            chunk_lin_list = chunk_lin_list[:max_chunks]
    elif max_chunks_env and bbox_mask is not None:
        logger.warning(
            "[TEST MODE] 已配置 bbox，忽略 OMEGA_SF_MAX_CHUNKS=%s",
            max_chunks_env,
        )
    return chunk_lin_list


def _prepare_chunks(
    config: OmegaSfConfig,
    anc: dict[str, np.ndarray],
    nrows: int,
    ncols: int,
    npix: int,
) -> tuple[list[np.ndarray], int]:
    """准备 chunk 线性索引列表 + max_valid_pixels。

    对应原 ``retrieve_omega_sf_daily`` 的 chunk 准备逻辑：
    1. 读 OMEGA_SF_MAX_PIXELS / config.max_pixels
    2. 按 pack_size 切 chunk
    3. bbox mask 打包（避免逐行重复 I/O）
    4. OMEGA_SF_CHUNK_OFFSET / OMEGA_SF_MAX_CHUNKS 测试模式裁剪

    Returns:
        (chunk_lin_list, max_valid_pixels)
    """
    import os

    max_pixels_env = os.environ.get("OMEGA_SF_MAX_PIXELS")
    max_valid_pixels = (
        int(max_pixels_env) if max_pixels_env else int(config.max_pixels or 0)
    )
    if max_valid_pixels > 0:
        logger.warning(
            "[TEST MODE] 限制有效像元总数 ≤ %d（OMEGA_SF_MAX_PIXELS/config.max_pixels）",
            max_valid_pixels,
        )

    chunk_size = config.pixel_chunk_size
    pack_size = (
        min(chunk_size, max_valid_pixels) if max_valid_pixels > 0 else chunk_size
    )
    chunk_lin_list: list[np.ndarray] = [
        np.arange(i, min(i + pack_size, npix), dtype=np.int64)
        for i in range(0, npix, pack_size)
    ]

    bbox_mask = _build_bbox_lin_mask(anc, nrows, ncols, config)
    if bbox_mask is not None:
        chunk_lin_list = _pack_bbox_chunks(
            bbox_mask, nrows, ncols, pack_size, max_valid_pixels
        )

    chunk_lin_list = _apply_chunk_test_env_vars(chunk_lin_list, bbox_mask)

    logger.info(
        "[CHUNK] 共 %d 个 chunk（每 chunk ≤ %d 像元）",
        len(chunk_lin_list),
        pack_size,
    )
    return chunk_lin_list, max_valid_pixels


def _load_fixed_omega_map(config: OmegaSfConfig) -> np.ndarray | None:
    """加载固定 OMEGA map（PFT 模式）。

    从 ``{config.out_aux}/omega_pft_from_exp0.mat`` 读取 omega_pft。
    非 PFT 模式或文件不存在时返回 None。
    对应原 ``retrieve_omega_sf_daily`` L2363–2370。

    Args:
        config: OmegaSfConfig（读取 omega_fixed_mode / out_aux）

    Returns:
        omega_fixed_map (npix,) 或 None
    """
    from ingest.mat_bundle import load_mat_file

    if config.omega_fixed_mode.upper() != "PFT":
        return None
    omega_pft_file = Path(config.out_aux or "") / "omega_pft_from_exp0.mat"
    if not omega_pft_file.exists():
        return None
    data = load_mat_file(str(omega_pft_file))
    if "omega_pft" not in data:
        return None
    return np.asarray(data["omega_pft"], dtype=np.float64)


def _finalize_and_save(
    state: _ChunkLoopState,
    block_struct: BlockStructure,
    grid_shape: tuple[int, int],
    npix: int,
    chunk_lin_list: list[np.ndarray],
    max_valid_pixels: int,
    output_dir: str,
    progress_callback: Any,
) -> OmegaSfResult:
    """汇总输出 + 保存 + 构建 OmegaSfResult。

    包含：
    - build_omega_pft_from_results / build_omega_pixel_from_results
    - _assemble_block_grids
    - _persist_block_maps (finalize=True)
    - omega_pft.mat / omega_pixel.mat 保存
    对应原 ``retrieve_omega_sf_daily`` L2451–2517。

    Args:
        state: chunk 循环状态（含 all_results / n_processed / n_success / n_failed）
        block_struct: 8 天块结构
        grid_shape: (nrows, ncols)
        npix: 总像元数
        chunk_lin_list: chunk 列表（用于进度）
        max_valid_pixels: 最大有效像元数
        output_dir: 输出目录（空字符串表示不写盘）
        progress_callback: 进度回调

    Returns:
        OmegaSfResult
    """
    omega_pft = build_omega_pft_from_results(state.all_results)
    omega_pix_map, omega_pix_count = build_omega_pixel_from_results(
        state.all_results, grid_shape
    )

    sm_maps, vod_maps, omega_maps = _assemble_block_grids(
        state.all_results, block_struct, grid_shape
    )

    output_paths: dict[str, str] = {}
    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        try:
            from scipy.io import savemat

            block_paths = _persist_block_maps(
                out_path,
                block_struct=block_struct,
                sm_maps=sm_maps,
                vod_maps=vod_maps,
                omega_maps=omega_maps,
                progress_callback=progress_callback,
                processed=state.n_processed,
                total=npix,
                chunks_done=len(chunk_lin_list),
                chunks_total=len(chunk_lin_list),
                pixels_done=state.n_valid_processed,
                pixels_total=max_valid_pixels or npix,
                finalize=True,
            )
            output_paths.update(block_paths)

            pft_file = out_path / "omega_pft.mat"
            savemat(str(pft_file), {"omega_pft": omega_pft})
            output_paths["omega_pft"] = str(pft_file)

            pix_file = out_path / "omega_pixel.mat"
            savemat(
                str(pix_file),
                {
                    "omega_pix_map": omega_pix_map,
                    "omega_pix_count": omega_pix_count,
                },
            )
            output_paths["omega_pixel"] = str(pix_file)

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
        n_pixels_total=state.n_processed,
        n_pixels_success=state.n_success,
        n_pixels_failed=state.n_failed,
        output_paths=output_paths,
    )


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
    gldas_template_mat: str = "",
    ddca_sm_folder: str = "",
    grid_shape: tuple[int, int] | None = None,
    output_dir: str = "",
    progress_callback: Any = None,
    cancel_flag_path: str | Path | None = None,
    reuse_block_cache: bool = True,
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
        gldas_template_mat: GLDAS UTC 过境模板 .mat
            （use_gldas_template=True 时按 slot 选取；缺省回退过境本地时匹配）
        ddca_sm_folder: DDCA SM 目录
        grid_shape: 网格形状 (nrows, ncols)
        output_dir: 输出目录
        progress_callback: 进度回调

    Returns:
        OmegaSfResult 包含所有输出产品
    """

    logger.info("=" * 60)
    logger.info("[START] omega_sf_fenkuai 反演")
    logger.info(
        "[RUN  ] EXP=Exp0 | TEMP_SCHEME=%s | RUN_DOMAIN=%s | TB_SOURCE=%s | SM_SOURCE=%s",
        config.temp_scheme,
        config.run_domain,
        config.tb_source,
        config.sm_source,
    )
    logger.info("[FIXED] OMEGA_FIXED_MODE=%s", config.omega_fixed_mode)
    logger.info("[BLOCK] %d-day", config.block_days)
    logger.info("=" * 60)

    if config.temp_scheme.upper() == "DUAL":
        if not gldas_mat_folder:
            raise ValueError(
                "temp_scheme=DUAL 需要提供 gldas_mat_folder（GLDAS 三温度 .mat 目录）；"
                "请在工作流数据源中配置 gldas_mat，或将 temp_scheme 设为 ORIG_TS。"
            )
        logger.info(
            "[DUAL ] mode=%s | ct_smref=%.2f | ct_exp=%.2f | tol=%.1fh | template=%s",
            config.dual_tg_mode,
            config.ct_smref,
            config.ct_exp,
            config.gldas_time_tol_hours,
            config.use_gldas_template,
        )

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

    # 2b) DUAL：按 GLDAS 可匹配性过滤运行日期（对齐 Matlab 日期交集，
    #     必须在块结构构建前完成以保证时间索引对齐）
    if config.temp_scheme.upper() == "DUAL":
        tvec = _filter_tvec_by_gldas_days(tvec, config, gldas_mat_folder, anc)
        nt = len(tvec)
        logger.info(
            "[DUAL ] GLDAS 交集后可用日期：%d（%s ~ %s）", nt, tvec[0], tvec[-1]
        )

    # 3) 构建 8 天块结构
    block_struct = make_viirs8_blocks(tvec, block_days=config.block_days)
    logger.info("[BLOCK] 共 %d 个块", len(block_struct.starts))

    # 4) NDVI 气候态（用于 SF 倒推中的 DOY NDVI 上下文）
    ndvi_clim_max = anc.get("ndvi_clim_max", np.full(npix, np.nan))
    ndvi_clim_min = anc.get("ndvi_clim_min", np.full(npix, np.nan))
    # NDVI 历史极值（VI_v_qa.mat → ndvi_v_max/min），用于 Tau 计算和 SF 倒推极值项
    # Matlab omega_sf_fenkuai.m L352-354: 从 VI_v_qa.mat 加载 NDVI_v_max/min
    # L710: 传入 Tau 函数；L633-634: 传入 SF 倒推
    ndvi_v_max_arr = anc.get("ndvi_v_max", ndvi_clim_max)
    ndvi_v_min_arr = anc.get("ndvi_v_min", ndvi_clim_min)

    # 诊断：辅助数据健康检查
    logger.info("[DIAG] 辅助数据键: %s", sorted(anc.keys()))
    logger.info(
        "[DIAG] landcover shape=%s, npix=%d, valid=%d",
        anc["landcover"].shape,
        npix,
        int(np.sum(np.isfinite(anc["landcover"].astype(float)))),
    )
    for _k in ("albedo", "b", "clay", "porosity", "h", "ndvi_v_max", "ndvi_v_min"):
        _v = anc.get(_k)
        if _v is not None:
            logger.info(
                "[DIAG] %-12s size=%d, finite=%d (%.1f%%), min=%.4f, max=%.4f",
                _k,
                _v.size,
                int(np.sum(np.isfinite(_v))),
                100.0 * np.sum(np.isfinite(_v)) / max(_v.size, 1),
                float(np.nanmin(_v)) if np.any(np.isfinite(_v)) else float("nan"),
                float(np.nanmax(_v)) if np.any(np.isfinite(_v)) else float("nan"),
            )
        else:
            logger.warning("[DIAG] %-12s MISSING", _k)

    # 5) 固定 OMEGA（PFT 模式从 omega_pft_file 加载）
    omega_fixed_map = _load_fixed_omega_map(config)

    # 6) 逐 chunk 反演
    chunk_lin_list, max_valid_pixels = _prepare_chunks(config, anc, nrows, ncols, npix)

    # 主循环可变状态（提取 _process_one_chunk 用容器封装）
    state = _ChunkLoopState(all_results=[])
    if reuse_block_cache and output_dir:
        loaded = _load_chunk_checkpoint(
            output_dir,
            start_date=config.start_date,
            end_date=config.end_date,
        )
        if loaded:
            state.completed_chunks, restored = loaded
            state.all_results.extend(restored)
            state.n_success = len(state.all_results)
            logger.info(
                "[CHECKPOINT] 复用 %d 个已完成 chunk，%d 条像元结果",
                len(state.completed_chunks),
                len(restored),
            )

    for ci, lin_pix in enumerate(chunk_lin_list):
        _process_one_chunk(
            ci,
            lin_pix,
            chunk_lin_list,
            state,
            tvec=tvec,
            nrows=nrows,
            ncols=ncols,
            npix=npix,
            config=config,
            smap_folder=smap_folder,
            fy3d_folder=fy3d_folder,
            fy3b_folder=fy3b_folder,
            ndvi_clim_folder=ndvi_clim_folder,
            ndvi_folder=ndvi_folder,
            anc=anc,
            landcover=landcover,
            block_struct=block_struct,
            ndvi_v_max_arr=ndvi_v_max_arr,
            ndvi_v_min_arr=ndvi_v_min_arr,
            omega_fixed_map=omega_fixed_map,
            max_valid_pixels=max_valid_pixels,
            output_dir=output_dir,
            progress_callback=progress_callback,
            cancel_flag_path=cancel_flag_path,
            reuse_block_cache=reuse_block_cache,
            grid_shape=grid_shape,
            gldas_mat_folder=gldas_mat_folder,
            anc_root=anc_root,
            gldas_template_mat=gldas_template_mat,
        )
        if state.stop:
            break

    # P3（2026-08-23）：正常走完（含 max_valid_pixels 达标的提前终止）即清理
    # 检查点——成功后残留会让下次同日期运行误 resume。异常/取消路径不经过
    # 此处，检查点保留供续算。
    if reuse_block_cache and output_dir:
        _cleanup_chunk_checkpoint(output_dir)

    _emit_progress(
        progress_callback,
        processed=state.n_processed,
        total=npix,
        chunks_done=len(chunk_lin_list),
        chunks_total=len(chunk_lin_list),
        pixels_done=state.n_valid_processed,
        pixels_total=max_valid_pixels or npix,
        phase="ddca",
    )

    logger.info(
        "[DONE] 反演完成：成功 %d / 失败 %d / 总计 %d (%.1f%%)",
        state.n_success,
        state.n_failed,
        state.n_processed,
        100.0 * state.n_success / max(state.n_processed, 1),
    )
    if state.n_success == 0:
        logger.error(
            "[DIAG] 反演成功率为 0%%！请检查："
            "1) SMAP/FY 数据文件是否存在且变量名正确；"
            "2) 辅助库（VI_v_qa.mat/IGBP_9km_12.mat 等）是否完整；"
            "3) grid_shape 是否与数据文件匹配。"
        )

    # 7) 汇总输出 + 保存
    return _finalize_and_save(
        state,
        block_struct,
        grid_shape,
        npix,
        chunk_lin_list,
        max_valid_pixels,
        output_dir,
        progress_callback,
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
    """构建时间序列：保留完整日期范围，缺失日由逐像元反演自然处理。

    与 Matlab 一致：tvec = start_date:end_date（全日期），缺失文件对应日
    数据为 NaN，由 ok_base / valid_tau 逻辑自动跳过。不取交集是为了保证
    8 天块结构与 Matlab 输出一致。
    """
    start = datetime.strptime(config.start_date, "%Y%m%d")
    end = datetime.strptime(config.end_date, "%Y%m%d")
    tvec_req = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    total_req = len(tvec_req)

    # 诊断：统计各数据源可用日期数（不用于过滤）
    t_smap = _scan_folder_dates(smap_folder)
    if t_smap:
        avail = sum(1 for t in tvec_req if t in t_smap)
        logger.info(
            "[TS] SMAP 可用日期: %d/%d (%.1f%%)",
            avail,
            total_req,
            100.0 * avail / max(total_req, 1),
        )
        if avail == 0:
            raise ValueError(f"SMAP 文件夹无可用日期数据: {smap_folder}")

    # NDVI 日期（仅 DAILY_FILE 模式诊断）
    if config.ndvi_mode.upper() == "DAILY_FILE" and ndvi_folder:
        t_ndvi = _scan_folder_dates(ndvi_folder)
        if t_ndvi:
            avail = sum(1 for t in tvec_req if t in t_ndvi)
            logger.info(
                "[TS] NDVI 可用日期: %d/%d (%.1f%%)",
                avail,
                total_req,
                100.0 * avail / max(total_req, 1),
            )

    # TB 日期诊断
    if config.tb_source.upper() == "FY":
        tb_folder = fy3d_folder if config.fy_platform.upper() == "3D" else fy3b_folder
        if tb_folder:
            t_tb = _scan_folder_dates(tb_folder)
            if t_tb:
                avail = sum(1 for t in tvec_req if t in t_tb)
                logger.info(
                    "[TS] FY TB 可用日期: %d/%d (%.1f%%)",
                    avail,
                    total_req,
                    100.0 * avail / max(total_req, 1),
                )
                if avail == 0:
                    raise ValueError(f"FY TB 文件夹无可用日期数据: {tb_folder}")

    # SM 参考日期诊断
    if config.sm_source.upper() == "DDCA" and ddca_sm_folder:
        t_smref = _scan_folder_dates(ddca_sm_folder)
        if t_smref:
            avail = sum(1 for t in tvec_req if t in t_smref)
            logger.info(
                "[TS] DDCA SM 可用日期: %d/%d (%.1f%%)",
                avail,
                total_req,
                100.0 * avail / max(total_req, 1),
            )

    logger.info(
        "[TS] 时间序列: %d 天（%s ~ %s），保留全日期范围",
        total_req,
        tvec_req[0].strftime("%Y%m%d"),
        tvec_req[-1].strftime("%Y%m%d"),
    )
    return tvec_req


# 增强版日期提取正则（支持 YYYYMMDD_*.* 格式）
_ENHANCED_DATE_PATTERN = re.compile(r"(\d{8})")


def _scan_folder_dates(folder: str) -> set[datetime]:
    """扫描文件夹中的 MAT 文件，提取日期集合。

    支持多种文件名格式：
    - YYYYMMDD.mat (纯日期)
    - YYYYMMDD_*.mat (日期+后缀，如 20250101_bundle.mat)
    - *_YYYYMMDD_*.mat (前缀+日期，如 FY3D_20250101_processed.mat)

    对应 Matlab 的日期提取逻辑，从文件名中提取任意 YYYYMMDD 模式。
    """
    if not folder:
        return set()
    p = Path(folder)
    if not p.exists():
        logger.warning("文件夹不存在: %s", folder)
        return set()

    dates: set[datetime] = set()
    skipped_files: list[str] = []

    for f in p.glob("*.mat"):
        name = f.stem

        # 方法 1: 尝试纯 YYYYMMDD 匹配（最高优先级）
        if re.fullmatch(r"\d{8}", name):
            try:
                d = datetime.strptime(name, "%Y%m%d")
                dates.add(d)
                continue
            except ValueError:
                pass

        # 方法 2: 从文件名任意位置提取 YYYYMMDD 模式
        match = _ENHANCED_DATE_PATTERN.search(f.name)
        if match:
            date_str = match.group(1)
            try:
                d = datetime.strptime(date_str, "%Y%m%d")
                dates.add(d)
                continue
            except ValueError:
                pass

        # 无法解析的文件记录日志
        skipped_files.append(f.name)

    if skipped_files:
        logger.debug(
            "文件夹 %s 中 %d 个文件无法解析日期: %s%s",
            folder,
            len(skipped_files),
            skipped_files[:5],
            "..." if len(skipped_files) > 5 else "",
        )

    return dates


def _load_anc_mat_field(
    root: Path, fname: str, keys: tuple[str, ...]
) -> np.ndarray | None:
    """加载 ``root/fname`` 的 mat 文件，返回第一个命中 key 的 float64 数组。

    文件不存在返回 None；文件存在但加载失败时异常逃逸（与原 _load_ancillary
    对 IGBP/Albedo/B/SF/BD/H/CF 的容错策略一致——这些字段不吞异常）。
    """
    from ingest.mat_bundle import load_mat_file

    path = root / fname
    if not path.exists():
        return None
    data = load_mat_file(str(path))
    return _load_mat_first_key(data, keys)


def _load_anc_lat_lon(root: Path) -> tuple[np.ndarray | None, np.ndarray | None]:
    """加载 lat/lon：优先 IGBP 文件内附，回退到独立 lat_lon 文件。

    回退文件的加载异常会逃逸（与原实现一致）。
    """
    lat = _load_anc_mat_field(root, "IGBP_9km_12.mat", ("lat_9km", "lat", "LAT"))
    lon = _load_anc_mat_field(root, "IGBP_9km_12.mat", ("lon_9km", "lon", "LON"))
    if lat is not None and lon is not None:
        return lat, lon
    # 独立经纬度文件回退
    for fname in ("smap_lat_lon.mat", "lat_lon_9km.mat"):
        path = root / fname
        if not path.exists():
            continue
        from ingest.mat_bundle import load_mat_file

        data = load_mat_file(str(path))
        if lat is None:
            lat = _load_mat_first_key(data, ("lat_9km", "lat", "LAT"))
        if lon is None:
            lon = _load_mat_first_key(data, ("lon_9km", "lon", "LON"))
        break
    return lat, lon


def _load_anc_ndvi_extrema(root: Path) -> tuple[np.ndarray | None, np.ndarray | None]:
    """加载 NDVI 历史极值（VI_v_qa.mat），含 NTFS 可访问性预检。

    返回 (ndvi_v_max, ndvi_v_min)，均 ravel；未找到对应 key 时为 None。
    双层异常保护（open 测试 + load_mat_file）对应 Windows NTFS 文件存在
    但无法读取的边缘情况。
    """
    from ingest.mat_bundle import load_mat_file

    for fname in ("VI_v_qa.mat", "NDVI_extrema.mat", "ndvi_extrema.mat"):
        path = root / fname
        if not path.exists():
            continue
        # NTFS 可访问性预检（原实现 L2614-2622）
        try:
            with open(path, "rb"):
                pass
        except (FileNotFoundError, OSError, PermissionError) as exc:
            logger.warning(
                "[ANC] 文件存在但无法 open() %s: %s，将使用 NDVI 气候态极值",
                path,
                exc,
            )
            break
        try:
            data = load_mat_file(str(path))
        except (FileNotFoundError, OSError) as exc:
            logger.warning(
                "[ANC] 文件可 open 但 load_mat_file 失败 %s: %s，将使用 NDVI 气候态极值",
                path,
                exc,
            )
            break
        vmax = _load_mat_first_key(data, ("NDVI_v_max", "ndvi_v_max"))
        vmin = _load_mat_first_key(data, ("NDVI_v_min", "ndvi_v_min"))
        if vmax is not None:
            vmax = vmax.ravel()
        if vmin is not None:
            vmin = vmin.ravel()
        logger.info(
            "[ANC] NDVI 极值加载自 %s: ndvi_v_max=%s, ndvi_v_min=%s",
            fname,
            "OK" if vmax is not None else "MISSING",
            "OK" if vmin is not None else "MISSING",
        )
        return vmax, vmin
    return None, None


def _load_anc_scalar_fields(root: Path) -> dict[str, np.ndarray]:
    """加载辅助库 6 个标量场：albedo/b/sf_static/bd/h/clay。

    每个字段从对应 .mat 文件加载，缺失时跳过（dict 中不含该 key）。
    对应原 ``_load_ancillary`` L2812–2823。

    Args:
        root: 辅助库根目录 Path

    Returns:
        dict，可能包含键: albedo, b, sf_static, bd, h, clay
        仅包含成功加载的字段。
    """
    _FIELDS: list[tuple[str, tuple[str, tuple[str, ...]]]] = [
        ("albedo", ("Albedo.mat", ("ALBEDO", "Albedo", "albedo"))),
        ("b", ("B.mat", ("B", "b"))),
        ("sf_static", ("SF.mat", ("SF_smap", "SF"))),
        ("bd", ("BD.mat", ("BD", "bd"))),
        ("h", ("H.mat", ("H", "h"))),
        ("clay", ("CF.mat", ("CF", "cf"))),
    ]
    result: dict[str, np.ndarray] = {}
    for field_name, (fname, keys) in _FIELDS:
        vals = _load_anc_mat_field(root, fname, keys)
        if vals is not None:
            result[field_name] = vals
    return result


def _fill_anc_defaults(anc: dict[str, np.ndarray]) -> None:
    """填充 ancillary 缺失项的默认值 + NDVI 极值回退到气候态。"""
    if "landcover" not in anc:
        anc["landcover"] = np.zeros((1, 1))
    for key in ("albedo", "b", "bd", "h", "clay"):
        if key not in anc:
            anc[key] = np.full(anc["landcover"].shape, np.nan)
    if "ndvi_clim_max" not in anc:
        anc["ndvi_clim_max"] = np.full(anc["landcover"].size, np.nan)
    if "ndvi_clim_min" not in anc:
        anc["ndvi_clim_min"] = np.full(anc["landcover"].size, np.nan)
    if "ndvi_v_max" not in anc:
        anc["ndvi_v_max"] = anc["ndvi_clim_max"].copy()
        logger.warning("[ANC] ndvi_v_max 未找到，回退到 ndvi_clim_max")
    if "ndvi_v_min" not in anc:
        anc["ndvi_v_min"] = anc["ndvi_clim_min"].copy()
        logger.warning("[ANC] ndvi_v_min 未找到，回退到 ndvi_clim_min")


def _compute_anc_porosity(anc: dict[str, np.ndarray]) -> None:
    """孔隙度 = 1 - BD/2.65（矿物颗粒密度）；过小/负值视为无效。"""
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


def _load_ancillary(anc_root: str) -> dict[str, np.ndarray]:
    """加载静态辅助库。

    对应 Matlab L338-362。各字段容错策略：IGBP/Albedo/B/SF/BD/H/CF 加载
    异常逃逸（不吞），NDVI 极值有双层异常保护（NTFS 可访问性预检）。
    """
    root = Path(anc_root)
    anc: dict[str, np.ndarray] = {}

    # IGBP 土地覆盖 + 经纬度（IGBP 文件内附或独立 lat_lon 文件回退）
    lc = _load_anc_mat_field(
        root, "IGBP_9km_12.mat", ("IGBP_9km_12", "landcover", "LC")
    )
    if lc is not None:
        anc["landcover"] = lc
    lat, lon = _load_anc_lat_lon(root)
    if lat is not None:
        anc["lat"] = lat
    if lon is not None:
        anc["lon"] = lon

    # 单文件标量场（Albedo / B / SF / BD / H / CF）
    anc.update(_load_anc_scalar_fields(root))

    # NDVI_v_max / NDVI_v_min（VI_v_qa.mat，权威历史极值；含 NTFS 预检）
    # Matlab 从 VI_v_qa.mat 加载（A5_NDVI_diff_all.m 产出），
    # 同时用于 SF 倒推和 Tau 计算（omega_sf_fenkuai.m L352-354, L633-634, L710）
    vmax, vmin = _load_anc_ndvi_extrema(root)
    if vmax is not None:
        anc["ndvi_v_max"] = vmax
    if vmin is not None:
        anc["ndvi_v_min"] = vmin

    # NDVI climatology max/min
    ndvi_clim_folder = root / "NDVI_clim"
    if ndvi_clim_folder.exists():
        anc["ndvi_clim_max"] = _build_ndvi_clim_max(ndvi_clim_folder)
        anc["ndvi_clim_min"] = _build_ndvi_clim_min(ndvi_clim_folder)

    # 默认值 + NDVI 极值回退到气候态
    _fill_anc_defaults(anc)

    # 孔隙度 = 1 - BD/2.65（矿物颗粒密度）；过小/负值视为无效
    _compute_anc_porosity(anc)

    return anc


def _build_ndvi_clim_max(folder: Path) -> np.ndarray:
    """构建 NDVI 气候态年最大值（增量计算，避免 OOM）。"""
    from ingest.mat_bundle import load_mat_file

    result: np.ndarray | None = None
    for f in sorted(folder.glob("*.mat")):
        try:
            data = load_mat_file(str(f))
            for key in ("NDVI_clim", "ndvi_clim"):
                if key in data:
                    arr = np.asarray(data[key], dtype=np.float64)
                    if result is None:
                        result = arr.copy()
                    else:
                        # np.fmax 传播 NaN，等价于 nanmax 但可原地更新
                        np.fmax(result, arr, out=result, where=np.isfinite(arr))
                    break
        except Exception:
            continue

    if result is None:
        return np.full(1, np.nan)

    return result.ravel()


def _build_ndvi_clim_min(folder: Path) -> np.ndarray:
    """构建 NDVI 气候态年最小值（增量计算，避免 OOM）。"""
    from ingest.mat_bundle import load_mat_file

    result: np.ndarray | None = None
    for f in sorted(folder.glob("*.mat")):
        try:
            data = load_mat_file(str(f))
            for key in ("NDVI_clim", "ndvi_clim"):
                if key in data:
                    arr = np.asarray(data[key], dtype=np.float64)
                    if result is None:
                        result = arr.copy()
                    else:
                        np.fmin(result, arr, out=result, where=np.isfinite(arr))
                    break
        except Exception:
            continue

    if result is None:
        return np.full(1, np.nan)

    return result.ravel()


# FY3B→FY3D 偏差缓存（避免每个 chunk 重复计算）
_fy3b_bias_cache: dict[str, tuple[float, float] | None] = {}


def _compute_fy3b_bias_cached(
    fy3d_folder: str,
    fy3b_folder: str,
    lin_pix: np.ndarray,
    method: str = "bias",
) -> tuple[float, float] | None:
    """计算并缓存 FY3B→FY3D 偏差校正量。

    从首个 FY3D/FY3B 同日可用日期计算偏差，缓存结果避免重复计算。
    返回 (bias_v, bias_h) 或 None（无重叠日期时）。
    """
    cache_key = f"{fy3d_folder}::{fy3b_folder}"
    if cache_key in _fy3b_bias_cache:
        return _fy3b_bias_cache[cache_key]

    from ingest.mat_bundle import load_mat_file

    bias_result: tuple[float, float] | None = None
    fy3d_dir = Path(fy3d_folder) if fy3d_folder else None
    fy3b_dir = Path(fy3b_folder) if fy3b_folder else None

    if fy3d_dir and fy3b_dir and fy3d_dir.exists() and fy3b_dir.exists():
        # 找首个同日可用日期
        fy3d_dates = {
            f.stem for f in fy3d_dir.glob("*.mat") if re.fullmatch(r"\d{8}", f.stem)
        }
        fy3b_dates = {
            f.stem for f in fy3b_dir.glob("*.mat") if re.fullmatch(r"\d{8}", f.stem)
        }
        common_dates = sorted(fy3d_dates & fy3b_dates)

        for date_str in common_dates[:5]:  # 最多尝试 5 个日期
            try:
                d3d = load_mat_file(str(fy3d_dir / f"{date_str}.mat"))
                d3b = load_mat_file(str(fy3b_dir / f"{date_str}.mat"))

                v3d = h3d = v3b = h3b = None
                for key in ("TBv_mat", "TBv"):
                    if key in d3d:
                        v3d = np.asarray(d3d[key], dtype=np.float64).ravel()
                        break
                for key in ("TBh_mat", "TBh"):
                    if key in d3d:
                        h3d = np.asarray(d3d[key], dtype=np.float64).ravel()
                        break
                for key in ("TBv_mat", "TBv"):
                    if key in d3b:
                        v3b = np.asarray(d3b[key], dtype=np.float64).ravel()
                        break
                for key in ("TBh_mat", "TBh"):
                    if key in d3b:
                        h3b = np.asarray(d3b[key], dtype=np.float64).ravel()
                        break

                if (
                    v3d is not None
                    and h3d is not None
                    and v3b is not None
                    and h3b is not None
                ):
                    match_info = match_fy3b_to_fy3d(v3b, h3b, v3d, h3d, method=method)
                    if match_info.applied:
                        bias_result = (match_info.bias_v, match_info.bias_h)
                        break
            except Exception:
                continue

    _fy3b_bias_cache[cache_key] = bias_result
    if bias_result is None:
        logger.warning(
            "[FY3B] 无法计算 FY3B→FY3D 偏差（无重叠日期或样本不足），回退数据不加校正"
        )
    return bias_result


def _fill_chunk_row(
    dest: np.ndarray,
    full_vals: np.ndarray | None,
    lin_pix: np.ndarray,
) -> None:
    """将全图 flat 数组按 lin_pix 填入 chunk 行（长度必须等于 chunk_pix）。

    旧实现 ``dest[:len(full)] = full[lin_pix]`` 在 chunk_pix < npix 时
    左右形状不一致，异常被吞掉后整行保持 NaN，是反演破碎的致命根因之一。
    """
    if full_vals is None:
        return
    flat = np.asarray(full_vals, dtype=np.float64).ravel()
    out = np.full(lin_pix.shape[0], np.nan, dtype=np.float64)
    ok = (lin_pix >= 0) & (lin_pix < flat.size)
    if np.any(ok):
        out[ok] = flat[lin_pix[ok]]
    dest[:] = out


def _load_mat_first_key(
    data: dict[str, Any], keys: tuple[str, ...]
) -> np.ndarray | None:
    """从 mat 字典中按 key 别名顺序取第一个命中项（float64、ravel）。

    消除 omega_sf 中反复出现的 ``for key in (...): if key in data: ...; break``
    模式。未命中返回 None。
    """
    for key in keys:
        if key in data:
            return np.asarray(data[key], dtype=np.float64)
    return None


def _fill_row_from_keys(
    dest_row: np.ndarray,
    data: dict[str, Any],
    keys: tuple[str, ...],
    lin_pix: np.ndarray,
) -> bool:
    """遍历 key 别名，取第一个命中项填入 chunk 行。

    Returns:
        True 若命中并填充；False 若无命中（dest_row 保持原值）。
    """
    vals = _load_mat_first_key(data, keys)
    if vals is None:
        return False
    _fill_chunk_row(dest_row, vals, lin_pix)
    return True


def _load_smap_day(smap_folder: str, date_str: str) -> dict[str, Any]:
    """加载当日 SMAP 文件，首文件触发网格校验。

    异常吞掉返回 ``{}``（与原实现 try/except: pass 一致）。
    """
    from ingest.mat_bundle import load_mat_file

    smap_file = Path(smap_folder) / f"{date_str}.mat"
    if not smap_file.exists():
        return {}
    try:
        data = load_mat_file(str(smap_file))
        return data
    except Exception:  # noqa: BLE001 — SMAP 容错
        return {}


def _load_fy_tb_day(
    fy3d_folder: str,
    fy3b_folder: str,
    date_str: str,
    config: OmegaSfConfig,
) -> tuple[dict[str, Any], bool]:
    """加载 FY TB 文件，含 FY3B→FY3D 回退。

    Returns:
        (tb_data, used_fy3b_fallback) — tb_data 为空 dict 表示无可用数据。
    """
    from ingest.mat_bundle import load_mat_file

    tb_folder = fy3d_folder if config.fy_platform.upper() == "3D" else fy3b_folder
    tb_file = Path(tb_folder) / f"{date_str}.mat"
    tb_data: dict[str, Any] = {}
    used_fy3b_fallback = False

    if tb_file.exists():
        try:
            tb_data = load_mat_file(str(tb_file))
        except Exception:  # noqa: BLE001 — FY 容错
            tb_data = {}

    # FY3B→FY3D 回退：FY3D 缺失时使用 FY3B + 偏差校正
    if (
        not tb_data
        and config.fy_platform.upper() == "3D"
        and config.match_enable
        and fy3b_folder
    ):
        fy3b_file = Path(fy3b_folder) / f"{date_str}.mat"
        if fy3b_file.exists():
            try:
                tb_data = load_mat_file(str(fy3b_file))
                used_fy3b_fallback = True
            except Exception:  # noqa: BLE001 — FY 容错
                tb_data = {}
    return tb_data, used_fy3b_fallback


def _fill_fy_tb_row(
    tb_data: dict[str, Any],
    used_fy3b_fallback: bool,
    fy3d_folder: str,
    fy3b_folder: str,
    lin_pix: np.ndarray,
    config: OmegaSfConfig,
    date_str: str,
    tbv_row: np.ndarray,
    tbh_row: np.ndarray,
    ia_row: np.ndarray,
) -> None:
    """从 FY tb_data 提取 TBv/TBh/IA，应用偏差校正，填入 chunk 行。

    异常吞掉（与原 try/except: pass 一致）。
    """
    if not tb_data:
        return
    try:
        tbv_vals = _load_mat_first_key(tb_data, ("TBv_mat", "TBv"))
        tbh_vals = _load_mat_first_key(tb_data, ("TBh_mat", "TBh"))
        ia_vals = _load_mat_first_key(tb_data, ("IA", "IA_mat"))

        # FY3B 数据（回退或主源=3B）均应用 FY3B→FY3D 偏差校正
        apply_fy3b_bias = used_fy3b_fallback or (
            config.fy_platform.upper() == "3B" and config.match_enable
        )
        if apply_fy3b_bias and tbv_vals is not None and tbh_vals is not None:
            bias = _compute_fy3b_bias_cached(
                fy3d_folder, fy3b_folder, lin_pix, config.match_method
            )
            if bias is not None:
                tbv_vals = tbv_vals + bias[0]
                tbh_vals = tbh_vals + bias[1]
            if used_fy3b_fallback:
                logger.debug(
                    "[TS] %s: FY3D 缺失，使用 FY3B 回退%s",
                    date_str,
                    f" (bias V={bias[0]:.3f} H={bias[1]:.3f})" if bias else " (无偏差)",
                )

        _fill_chunk_row(tbv_row, tbv_vals, lin_pix)
        _fill_chunk_row(tbh_row, tbh_vals, lin_pix)
        _fill_chunk_row(ia_row, ia_vals, lin_pix)
    except Exception:  # noqa: BLE001 — FY TB 填充容错
        pass


def _load_ndvi_day(
    config: OmegaSfConfig,
    ndvi_clim_folder: str,
    ndvi_folder: str,
    date_str: str,
    doy: int,
    lin_pix: np.ndarray,
) -> np.ndarray:
    """加载当日 NDVI（DOY_CLIM 或 DAILY_FILE），返回 chunk 行长度数组。

    缺失时全 NaN。异常吞掉（与原 try/except: pass 一致）。
    """
    from ingest.mat_bundle import load_mat_file

    chunk_pix = lin_pix.size
    out = np.full(chunk_pix, np.nan)
    if config.ndvi_mode.upper() == "DOY_CLIM" and ndvi_clim_folder:
        clim_file = Path(ndvi_clim_folder) / f"{doy}.mat"
        if clim_file.exists():
            try:
                clim_data = load_mat_file(str(clim_file))
                _fill_row_from_keys(out, clim_data, ("NDVI_clim", "ndvi_clim"), lin_pix)
            except Exception:  # noqa: BLE001 — NDVI 容错
                pass
    elif config.ndvi_mode.upper() == "DAILY_FILE" and ndvi_folder:
        ndvi_file = Path(ndvi_folder) / f"{date_str}.mat"
        if ndvi_file.exists():
            try:
                ndvi_data = load_mat_file(str(ndvi_file))
                _fill_row_from_keys(out, ndvi_data, ("NDVI", "ndvi"), lin_pix)
            except Exception:  # noqa: BLE001 — NDVI 容错
                pass
    return out


def _compute_sf_inverted_day(
    smap_data: dict[str, Any],
    ndvi_clim_folder: str,
    doy: int,
    lin_pix: np.ndarray,
    anc: dict[str, np.ndarray],
    config: OmegaSfConfig,
) -> np.ndarray:
    """SF INVERTED_DAILY：vwc + NDVI_clim 回退 + build_sf_row_daily。

    对应原 ``_preload_chunk`` SF 分支的 INVERTED_DAILY 子分支。
    """
    from ingest.mat_bundle import load_mat_file

    chunk_pix = lin_pix.size
    # vwc（直接索引，与原实现一致——无边界检查）
    vwc_vals = np.full(chunk_pix, np.nan)
    for key in ("vwc", "VWC"):
        if key in smap_data:
            vals = np.asarray(smap_data[key], dtype=np.float64).ravel()
            vwc_vals = vals[lin_pix]
            break

    # 当天 DOY 的 NDVI_clim
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
        except Exception:  # noqa: BLE001 — NDVI_clim 容错
            pass

    # 回退：NDVI_clim 缺测时用 NDVI 气候态年最大值填充
    # ndvi_v_max/min 由 _load_ancillary._fill_anc_defaults 保证存在（回退到 clim）
    ndvi_v_max = anc.get("ndvi_v_max")
    ndvi_v_min = anc.get("ndvi_v_min")
    assert ndvi_v_max is not None, "anc['ndvi_v_max'] 应由 _fill_anc_defaults 填充"
    assert ndvi_v_min is not None, "anc['ndvi_v_min'] 应由 _fill_anc_defaults 填充"
    _ndvi_clim_nan = ~np.isfinite(ndvi_clim_row)
    if np.any(_ndvi_clim_nan):
        _ndvi_max_fallback = (
            ndvi_v_max[lin_pix]
            if lin_pix.max() < len(ndvi_v_max)
            else np.full(chunk_pix, np.nan)
        )
        _fallback_valid = _ndvi_clim_nan & np.isfinite(_ndvi_max_fallback)
        ndvi_clim_row[_fallback_valid] = _ndvi_max_fallback[_fallback_valid]

    landcover_flat = anc["landcover"].ravel()
    cls_row = (
        landcover_flat[lin_pix]
        if lin_pix.max() < len(landcover_flat)
        else np.zeros(chunk_pix)
    )
    ndvi_max_row = (
        ndvi_v_max[lin_pix]
        if lin_pix.max() < len(ndvi_v_max)
        else np.full(chunk_pix, np.nan)
    )
    ndvi_min_row = (
        ndvi_v_min[lin_pix]
        if lin_pix.max() < len(ndvi_v_min)
        else np.full(chunk_pix, np.nan)
    )

    return build_sf_row_daily(
        vwc_vals,
        ndvi_clim_row,
        ndvi_max_row,
        ndvi_min_row,
        cls_row,
        config.sf_invert_mode,
    )


# ─── DUAL 双温度 GLDAS 预读（复用 ingest/daily_bundle） ─────────────────────


def _sf_desc_local_hour(config: OmegaSfConfig) -> float:
    """按 TB 源返回降轨过境本地时（与 daily_bundle 过境匹配一致）。"""
    if config.tb_source.upper() == "FY":
        if config.fy_platform.upper() == "3B":
            return config.fy3b_desc_local_hour
        return config.fy3d_desc_local_hour
    return config.smap_desc_local_hour


def _build_sf_daily_bundle_config(config: OmegaSfConfig) -> Any:
    """由 OmegaSfConfig 构造 DailyBundleConfig（仅 DUAL 相关字段）。"""
    from ingest.daily_bundle import DailyBundleConfig

    return DailyBundleConfig(
        tb_source=config.tb_source,
        fy_platform=config.fy_platform,
        temp_scheme="DUAL",
        dual_tg_mode=config.dual_tg_mode,
        ct_smref=config.ct_smref,
        ct_exp=config.ct_exp,
        use_gldas_template=config.use_gldas_template,
        fy3d_desc_local_hour=config.fy3d_desc_local_hour,
        fy3b_desc_local_hour=config.fy3b_desc_local_hour,
        smap_desc_local_hour=config.smap_desc_local_hour,
        gldas_time_tol_hours=config.gldas_time_tol_hours,
    )


def _build_sf_gldas_selection(
    gldas_mat_folder: str,
    anc_root: str,
    gldas_template_mat: str = "",
) -> dict[str, Any]:
    """构造 daily_bundle loader 所需的 datasource_selection（最小键集）。"""
    selection: dict[str, Any] = {
        "gldas_mat_folder": gldas_mat_folder,
        "anc_root": anc_root,
    }
    if gldas_template_mat:
        selection["gldas_template_mat"] = gldas_template_mat
    return selection


def _load_gldas_day_rows(
    date_str: str,
    lin_pix: np.ndarray,
    gldas_mat_folder: str,
    anc_root: str,
    config: OmegaSfConfig,
    gldas_template_mat: str = "",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """加载单日 GLDAS 三温度行（TC/Tsoil1/Tsoil2），形状 (chunk_pix,)。

    经 daily_bundle.load_dual_temperature_row_for_day 过境匹配（或模板法）。
    lin_pix 为 0-based 线性索引；loader 约定 1-based，此处 +1 传递。
    无匹配像元返回 NaN。
    """
    from ingest.daily_bundle import load_dual_temperature_row_for_day

    lin_pix_1based = np.asarray(lin_pix, dtype=np.int64).ravel() + 1
    tc_row, tsoil1_row, tsoil2_row, _diag = load_dual_temperature_row_for_day(
        date_str,
        _build_sf_gldas_selection(gldas_mat_folder, anc_root, gldas_template_mat),
        _build_sf_daily_bundle_config(config),
        lin_pix=lin_pix_1based,
    )
    tc = np.asarray(tc_row, dtype=np.float64).ravel()
    tsoil1 = np.asarray(tsoil1_row, dtype=np.float64).ravel()
    tsoil2 = np.asarray(tsoil2_row, dtype=np.float64).ravel()
    expected = int(lin_pix_1based.size)
    if tc.size != expected or tsoil1.size != expected or tsoil2.size != expected:
        raise ValueError(
            f"GLDAS 行长度 {tc.size}/{tsoil1.size}/{tsoil2.size} != chunk 像元数 "
            f"{expected}（date={date_str}）"
        )
    return tc, tsoil1, tsoil2


def _filter_tvec_by_gldas_days(
    tvec: list[datetime],
    config: OmegaSfConfig,
    gldas_mat_folder: str,
    anc: dict[str, np.ndarray],
) -> list[datetime]:
    """DUAL 模式下按 GLDAS 可匹配性过滤运行日期（对齐 Matlab 日期交集）。

    过境匹配法：给定卫星过境本地时 h 与经度范围 [lon_min, lon_max]，
    目标 UTC 窗口为 [day+h-lon_max/15-tol, day+h-lon_min/15+tol]；
    窗口内存在任一 GLDAS 文件则保留该日（像元级无匹配由 NaN 掩码处理）。
    模板法（use_gldas_template=True）无法用经度窗口预判，保留全部日期。
    """
    from bisect import bisect_left

    from ingest.daily_bundle import build_gldas_file_index

    if config.use_gldas_template:
        return list(tvec)

    lon = anc.get("lon")
    lon_vals = np.asarray(lon, dtype=np.float64).ravel() if lon is not None else None
    if lon_vals is None or not np.any(np.isfinite(lon_vals)):
        raise ValueError(
            "temp_scheme=DUAL 需要辅助库 lon 网格"
            "（IGBP_9km_12.mat 内附或 lat_lon 回退文件）用于 GLDAS 过境匹配。"
        )
    lon_min = float(np.nanmin(lon_vals))
    lon_max = float(np.nanmax(lon_vals))

    index = build_gldas_file_index(gldas_mat_folder)
    times = index["times"]
    tol = timedelta(hours=float(config.gldas_time_tol_hours))
    local_hour = _sf_desc_local_hour(config)

    kept: list[datetime] = []
    dropped: list[datetime] = []
    for date in tvec:
        day0 = datetime(date.year, date.month, date.day)
        t_lo = day0 + timedelta(hours=local_hour - lon_max / 15.0) - tol
        t_hi = day0 + timedelta(hours=local_hour - lon_min / 15.0) + tol
        i = bisect_left(times, t_lo)
        has_match = i < len(times) and times[i] <= t_hi
        (kept if has_match else dropped).append(date)

    if dropped:
        preview = ", ".join(d.strftime("%Y%m%d") for d in dropped[:8])
        suffix = "…" if len(dropped) > 8 else ""
        logger.warning(
            "[DUAL ] GLDAS 无匹配剔除 %d/%d 天：%s%s",
            len(dropped),
            len(tvec),
            preview,
            suffix,
        )
    if not kept:
        raise ValueError(
            f"temp_scheme=DUAL：{tvec[0]:%Y%m%d}~{tvec[-1]:%Y%m%d} 内无任何日期"
            f"可在 {gldas_mat_folder} 找到 ±{config.gldas_time_tol_hours}h 容差的"
            " GLDAS 匹配文件，请检查 GLDAS 数据覆盖范围。"
        )
    return kept


def _preload_one_day(
    date: datetime,
    doy: int,
    lin_pix: np.ndarray,
    *,
    config: OmegaSfConfig,
    smap_folder: str,
    fy3d_folder: str,
    fy3b_folder: str,
    ndvi_clim_folder: str,
    ndvi_folder: str,
    anc: dict[str, np.ndarray],
    sf_static: np.ndarray,
) -> tuple[
    np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray
]:
    """加载单日 chunk 数据。

    从 SMAP/FY/NDVI 文件加载一天的 TBv/TBh/IA/Ts/SM_ref/NDVI/SF，
    返回 7 个形状为 (chunk_pix,) 的 1D 数组。
    缺失数据时对应行保持 NaN（各 helper 内部容错）。

    Args:
        date: 日期
        doy: day of year
        lin_pix: 像元线性索引 (chunk_pix,)
        config: OmegaSfConfig
        smap_folder: SMAP .mat 文件目录
        fy3d_folder: FY-3D .mat 目录
        fy3b_folder: FY-3B .mat 目录
        ndvi_clim_folder: NDVI DOY 气候态目录
        ndvi_folder: NDVI 逐日目录
        anc: 辅助库 dict
        sf_static: 静态 SF 数组 (npix,) ravel

    Returns:
        (tbv_row, tbh_row, ia_row, ts_row, sm_ref_row, ndvi_row, sf_row)
        每个元素为 shape (chunk_pix,) 的 np.ndarray
    """
    date_str = date.strftime("%Y%m%d")
    chunk_pix = int(lin_pix.size)

    # SMAP 文件
    smap_data: dict[str, Any] = _load_smap_day(smap_folder, date_str)

    # 初始化行
    tbv_row = np.full(chunk_pix, np.nan)
    tbh_row = np.full(chunk_pix, np.nan)
    ia_row = np.full(chunk_pix, np.nan)
    ts_row = np.full(chunk_pix, np.nan)
    sm_ref_row = np.full(chunk_pix, np.nan)

    # TB + IA（FY 模式从 FY 文件读，SMAP 模式从 SMAP 文件读）
    if config.tb_source.upper() == "FY":
        tb_data, used_fy3b_fallback = _load_fy_tb_day(
            fy3d_folder, fy3b_folder, date_str, config
        )
        _fill_fy_tb_row(
            tb_data,
            used_fy3b_fallback,
            fy3d_folder,
            fy3b_folder,
            lin_pix,
            config,
            date_str,
            tbv_row,
            tbh_row,
            ia_row,
        )
    else:
        # SMAP TB + IA
        _fill_row_from_keys(tbv_row, smap_data, ("TBv", "TBv_mat"), lin_pix)
        _fill_row_from_keys(tbh_row, smap_data, ("TBh", "TBh_mat"), lin_pix)
        _fill_row_from_keys(ia_row, smap_data, ("IA", "IA_mat"), lin_pix)

    # 温度
    _fill_row_from_keys(ts_row, smap_data, ("Ts", "Ts_mat"), lin_pix)

    # 参考土壤水分（sm_dca 为 SMAP MAT 标准变量名，
    # 与 daily_bundle.py smap_sm_aliases 对齐）
    _fill_row_from_keys(
        sm_ref_row,
        smap_data,
        ("sm_dca", "SM", "SM_mat", "soil_moisture", "sm"),
        lin_pix,
    )

    # NDVI
    ndvi_row = _load_ndvi_day(
        config, ndvi_clim_folder, ndvi_folder, date_str, doy, lin_pix
    )

    # SF
    sf_mode = config.sf_mode.upper()
    if sf_mode == "STATIC":
        sf_row = sf_static[lin_pix].copy()
    elif sf_mode == "INVERTED_DAILY":
        sf_row = _compute_sf_inverted_day(
            smap_data, ndvi_clim_folder, doy, lin_pix, anc, config
        )
    else:
        sf_row = np.full(chunk_pix, np.nan)

    return tbv_row, tbh_row, ia_row, ts_row, sm_ref_row, ndvi_row, sf_row


def _preload_chunk(
    tvec: list[datetime],
    nrows: int,
    ncols: int,
    config: OmegaSfConfig,
    smap_folder: str,
    fy3d_folder: str,
    fy3b_folder: str,
    ndvi_clim_folder: str,
    ndvi_folder: str,
    anc: dict[str, np.ndarray],
    *,
    lin_pix: np.ndarray | None = None,
    chunk_start: int | None = None,
    chunk_end: int | None = None,
    gldas_mat_folder: str = "",
    anc_root: str = "",
    gldas_template_mat: str = "",
) -> dict[str, np.ndarray]:
    """预读 chunk 数据。

    对应 Matlab 预读总函数 (L1425-1729)。

    返回 dict 包含 tbv/tbh/ia/ts/sm_ref/ndvi/sf，形状均为 (Nt, chunk_pix)。
    ``temp_scheme=DUAL`` 时额外包含 tc/tsoil1/tsoil2 三键（GLDAS 双温度）。
    ``lin_pix`` 可为非连续索引（bbox mask 打包）；未给时退回 ``[chunk_start, chunk_end)``。
    """
    nt = len(tvec)
    if lin_pix is None:
        if chunk_start is None or chunk_end is None:
            raise ValueError("preload 需要 lin_pix 或 chunk_start/chunk_end")
        lin_pix = np.arange(chunk_start, chunk_end, dtype=np.int64)
    else:
        lin_pix = np.asarray(lin_pix, dtype=np.int64).ravel()
    chunk_pix = int(lin_pix.size)
    npix = nrows * ncols
    use_dual = config.temp_scheme.upper() == "DUAL"
    if use_dual and not gldas_mat_folder:
        raise ValueError("temp_scheme=DUAL 预读需要 gldas_mat_folder")

    tbv_mat = np.full((nt, chunk_pix), np.nan)
    tbh_mat = np.full((nt, chunk_pix), np.nan)
    ia_mat = np.full((nt, chunk_pix), np.nan)
    ts_mat = np.full((nt, chunk_pix), np.nan)
    sm_ref_mat = np.full((nt, chunk_pix), np.nan)
    ndvi_mat = np.full((nt, chunk_pix), np.nan)
    sf_mat = np.full((nt, chunk_pix), np.nan)
    if use_dual:
        tc_mat = np.full((nt, chunk_pix), np.nan)
        tsoil1_mat = np.full((nt, chunk_pix), np.nan)
        tsoil2_mat = np.full((nt, chunk_pix), np.nan)

    sf_static = anc.get("sf_static", np.full(anc["landcover"].size, np.nan)).ravel()

    # ── 显式 SMAP 网格校验（首个存在的 SMAP .mat 文件） ──
    _grid_validated = False
    for date in tvec:
        date_str = date.strftime("%Y%m%d")
        smap_file = Path(smap_folder) / f"{date_str}.mat"
        if smap_file.exists():
            try:
                from ingest.mat_bundle import load_mat_file

                test_data = load_mat_file(str(smap_file))
                for _k in ("TBv", "TBv_mat", "Ts", "Ts_mat", "sm_dca", "SM"):
                    if _k in test_data:
                        vals = np.asarray(test_data[_k], dtype=np.float64).ravel()
                        if vals.size != npix:
                            logger.warning(
                                "[GRID] SMAP/%s: 数据大小 %d != grid npix %d (nrows=%d ncols=%d)。"
                                "可能存在 MAT v7.3 转置问题或网格定义不匹配。",
                                date_str,
                                vals.size,
                                npix,
                                nrows,
                                ncols,
                            )
                        break
            except Exception:  # noqa: BLE001 — 网格校验容错
                pass
            break  # 仅校验首个存在的 SMAP 文件

    for k, date in enumerate(tvec):
        doy = date.timetuple().tm_yday
        (
            tbv_mat[k],
            tbh_mat[k],
            ia_mat[k],
            ts_mat[k],
            sm_ref_mat[k],
            ndvi_mat[k],
            sf_mat[k],
        ) = _preload_one_day(
            date,
            doy,
            lin_pix,
            config=config,
            smap_folder=smap_folder,
            fy3d_folder=fy3d_folder,
            fy3b_folder=fy3b_folder,
            ndvi_clim_folder=ndvi_clim_folder,
            ndvi_folder=ndvi_folder,
            anc=anc,
            sf_static=sf_static,
        )
        if use_dual:
            tc_mat[k], tsoil1_mat[k], tsoil2_mat[k] = _load_gldas_day_rows(
                date.strftime("%Y%m%d"),
                lin_pix,
                gldas_mat_folder,
                anc_root,
                config,
                gldas_template_mat,
            )

    if use_dual:
        return {
            "tbv": tbv_mat,
            "tbh": tbh_mat,
            "ia": ia_mat,
            "ts": ts_mat,
            "sm_ref": sm_ref_mat,
            "ndvi": ndvi_mat,
            "sf": sf_mat,
            "tc": tc_mat,
            "tsoil1": tsoil1_mat,
            "tsoil2": tsoil2_mat,
        }
    return {
        "tbv": tbv_mat,
        "tbh": tbh_mat,
        "ia": ia_mat,
        "ts": ts_mat,
        "sm_ref": sm_ref_mat,
        "ndvi": ndvi_mat,
        "sf": sf_mat,
    }
