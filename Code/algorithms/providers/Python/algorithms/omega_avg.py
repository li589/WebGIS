"""D2 avg-omega 逐日反演核心算法。

将 Matlab ``D2_avg_sm_vod.m`` 迁移为 Python：从 D1 (omega_block) 逐日 OMEGA 输出
构建 DOY 气候态平均 omega，再用平均 omega 作为固定值逐日回代 DDCA，产出最终
逐日 SM/VOD/OMEGA 产品。支持全量方案（FY/SMAP × ORIG_TS/DUAL 温度方案）。

四阶段流水线：
    Stage A: ``build_raw_omega_daily_cache`` — 从 omega_block 的 ``daily_omega/``
        逐日文件加载 OMEGA（1D npix），重组为 2D grid 并按年缓存。
    Stage B: ``build_doy_omega_climatology`` — 遍历 366 个 DOY，对每个 DOY 收集
        多年同 DOY 的 OMEGA_daily 计算均值 → OMEGA_AVG，输出 ``doy_001.mat`` ~ ``doy_366.mat``。
    Stage C: ``extract_halpha_maps`` — 从 omega_block ``.mat`` 提取
        ``h_star_vec`` / ``alpha_star_vec``（1D npix），reshape 为 2D grid。
    Stage D: ``retrieve_daily_with_avg_omega`` — 对目标年每一天：加载 DOY 对应的
        OMEGA_AVG，复用 ``build_daily_bundle_for_date()`` 加载逐日 TB/NDVI/SF/温度，
        对有效像元调用 ``ddca_single_temp`` / ``ddca_dual_temp``（传入
        ``omega_value=OMEGA_AVG[pixel]`` 作为固定值），产出 SM/VOD/OMEGA。

与 Matlab D2 的关键差异：Python ``omega_block`` 已直接产出逐日 ``OMEGA_mat``
（nt×npix），无需块→日展开，Stage A 退化为读取+重组，且只实现 ``ALL_DAYS`` 模式。

量纲约定：
    温度（Ts/tc/tg/TBv/TBh）单位 K；freq_ghz 单位 GHz；theta_deg 单位度 (°)；
    soil_moisture 单位 m³/m³；omega/h/alpha/tau/vod 无量纲。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# BrokenProcessPool 用于 except 子句匹配，需模块级可见
from concurrent.futures.process import BrokenProcessPool

logger = logging.getLogger(__name__)

# 日期键格式（YYYYMMDD 字符串），与 daily_bundle / omega 模块一致
_DATE_KEY_FORMAT = "%Y%m%d"

# DOY 气候态文件命名前缀（doy_001.mat ~ doy_366.mat）
_DOY_FILE_PREFIX = "doy_"

# 闰年 DOY 数量上限（366）
_MAX_DOY = 366


@dataclass(frozen=True, slots=True)
class OmegaAvgConfig:
    """D2 avg-omega 反演配置参数。

    量纲: 所有字段无量纲，除 ``avg_build_start_year`` / ``avg_build_end_year``
    为年份整数、``pixel_chunk_size`` / ``print_every_days`` 为计数整数、
    ``lambda_tau`` 为正则化权重（无量纲）。
    """

    # DOY 气候态构建的年份范围 [start, end]（含两端）
    avg_build_start_year: int = 2015
    avg_build_end_year: int = 2025
    # 缺失 DOY 气候态时是否自动构建
    auto_build_avg_if_missing: bool = True
    # 强制重建 DOY 气候态（即使已存在）
    force_rebuild_avg: bool = False
    # 像元分块大小（控制内存；并行时每个 chunk 的像元数）
    pixel_chunk_size: int = 200_000
    # 日循环进度打印间隔（每 N 天打印一次）
    print_every_days: int = 20
    # DDCA tau 正则化权重（透传给 ddca_single_temp / ddca_dual_temp）
    lambda_tau: float = 20.0
    # L 波段中心频率（GHz），透传给 DDCA 前向模型
    freq_ghz: float = 1.4
    # 是否启用像元级并行（ProcessPoolExecutor + spawn）；失败自动回退串行
    enable_parallel: bool = True


def build_omega_avg_config(params: dict[str, Any]) -> OmegaAvgConfig:
    """从 workflow 参数字典构建 ``OmegaAvgConfig``。"""
    return OmegaAvgConfig(
        avg_build_start_year=int(params.get("avg_build_start_year", 2015)),
        avg_build_end_year=int(params.get("avg_build_end_year", 2025)),
        auto_build_avg_if_missing=bool(params.get("auto_build_avg_if_missing", True)),
        force_rebuild_avg=bool(params.get("force_rebuild_avg", False)),
        pixel_chunk_size=int(params.get("pixel_chunk_size", 200_000)),
        print_every_days=int(params.get("print_every_days", 20)),
        lambda_tau=float(params.get("lambda_tau", 20.0)),
        freq_ghz=float(params.get("freq_ghz", 1.4)),
        enable_parallel=bool(params.get("enable_parallel", True)),
    )


# ─── Stage A: 逐日 OMEGA 缓存 ───────────────────────────────────────────────


def _iter_date_keys_for_year(year: int) -> list[str]:
    """返回某年所有日期键（YYYYMMDD），含闰日。"""
    start = datetime(year, 1, 1)
    end = datetime(year, 12, 31)
    keys: list[str] = []
    current = start
    while current <= end:
        keys.append(current.strftime(_DATE_KEY_FORMAT))
        current += timedelta(days=1)
    return keys


def build_raw_omega_daily_cache(
    omega_block_dir: Path,
    output_cache_dir: Path,
    years: list[int],
    grid_shape: tuple[int, int],
) -> dict[str, Any]:
    """Stage A: 从 omega_block 逐日输出加载 OMEGA，重组为 2D grid 并按年缓存。

    Python ``omega_block`` 已产出 ``daily_omega/{date}.mat``（含 1D ``OMEGA`` 向量，
    长度 npix = grid_shape[0] × grid_shape[1]）。本函数将其 reshape 为 2D grid，
    写入 ``{output_cache_dir}/{year}/{date}.mat``（变量名 ``OMEGA_2d``）。

    量纲: OMEGA 无量纲（单次散射反照率）。grid_shape 为 (nrows, ncols)。

    Args:
        omega_block_dir: D1 omega_block 输出目录（含 ``daily_omega/`` 子目录）。
        output_cache_dir: Stage A 缓存输出根目录。
        years: 需缓存的年份列表。
        grid_shape: (nrows, ncols) 用于 1D→2D reshape。

    Returns:
        统计字典：``{"cached_days": int, "skipped_days": int, "years": list[int]}``。
    """
    from scipy.io import savemat

    import numpy as np

    daily_dir = Path(omega_block_dir) / "daily_omega"
    output_cache_dir = Path(output_cache_dir)
    npix = int(grid_shape[0]) * int(grid_shape[1])

    cached_days = 0
    skipped_days = 0
    processed_years: list[int] = []

    for year in years:
        year_dir = output_cache_dir / str(year)
        year_dir.mkdir(parents=True, exist_ok=True)
        year_cached = 0
        for date_key in _iter_date_keys_for_year(year):
            src = daily_dir / f"{date_key}.mat"
            if not src.exists():
                skipped_days += 1
                continue
            dst = year_dir / f"{date_key}.mat"
            if dst.exists():
                # 已缓存则跳过（避免重复 I/O）
                cached_days += 1
                year_cached += 1
                continue
            payload = _load_mat_payload_local(src)
            omega_vec = _pick_field_local(payload, ("OMEGA", "omega"))
            omega_arr = np.asarray(omega_vec, dtype=np.float64).reshape(-1)
            if omega_arr.size != npix:
                raise ValueError(
                    f"OMEGA vector size {omega_arr.size} != grid npix {npix} "
                    f"for {date_key}"
                )
            omega_2d = omega_arr.reshape(grid_shape)
            savemat(dst, {"OMEGA_2d": omega_2d}, do_compression=True)
            cached_days += 1
            year_cached += 1
        if year_cached > 0:
            processed_years.append(year)

    logger.info(
        "Stage A: cached %d daily OMEGA files (%d skipped) for years %s",
        cached_days,
        skipped_days,
        processed_years,
    )
    return {
        "cached_days": cached_days,
        "skipped_days": skipped_days,
        "years": processed_years,
    }


# ─── Stage B: DOY 气候态 OMEGA_AVG ──────────────────────────────────────────


def build_doy_omega_climatology(
    cache_dir: Path,
    output_doy_dir: Path,
    years: list[int],
    grid_shape: tuple[int, int],
) -> dict[str, Any]:
    """Stage B: 构建 DOY 气候态 OMEGA_AVG。

    遍历 366 个 DOY，对每个 DOY 收集多年同 DOY 的 ``OMEGA_2d``（来自 Stage A 缓存），
    计算逐像元 nanmean → ``OMEGA_AVG``，有效计数 → ``count_grid``，使用的年份列表 →
    ``used_years``。输出 ``doy_001.mat`` ~ ``doy_366.mat``。

    量纲: OMEGA_AVG / count_grid 无量纲；grid_shape 为 (nrows, ncols)。

    Args:
        cache_dir: Stage A 缓存根目录（含 ``{year}/{date}.mat``）。
        output_doy_dir: DOY 气候态输出目录。
        years: 参与气候态构建的年份列表。
        grid_shape: (nrows, ncols)。

    Returns:
        统计字典：``{"doy_files": int, "total_samples": int}``。
    """
    from scipy.io import savemat

    import numpy as np

    cache_dir = Path(cache_dir)
    output_doy_dir = Path(output_doy_dir)
    output_doy_dir.mkdir(parents=True, exist_ok=True)

    # 预索引：每个 DOY 收集 (year, date_key) 列表
    doy_index: dict[int, list[tuple[int, str]]] = {
        d: [] for d in range(1, _MAX_DOY + 1)
    }
    for year in years:
        year_dir = cache_dir / str(year)
        if not year_dir.exists():
            continue
        for date_key in _iter_date_keys_for_year(year):
            src = year_dir / f"{date_key}.mat"
            if src.exists():
                doy = datetime.strptime(date_key, _DATE_KEY_FORMAT).timetuple().tm_yday
                doy_index[doy].append((year, date_key))

    doy_files = 0
    total_samples = 0
    for doy in range(1, _MAX_DOY + 1):
        samples = doy_index[doy]
        if not samples:
            continue
        stack = []
        used_years: list[int] = []
        for year, date_key in samples:
            payload = _load_mat_payload_local(cache_dir / str(year) / f"{date_key}.mat")
            omega_2d = _pick_field_local(payload, ("OMEGA_2d", "OMEGA"))
            stack.append(np.asarray(omega_2d, dtype=np.float64))
            if year not in used_years:
                used_years.append(year)
        stacked = np.stack(stack, axis=0)  # (nsamples, nrows, ncols)
        omega_avg = np.nanmean(stacked, axis=0)
        count_grid = np.sum(~np.isnan(stacked), axis=0).astype(np.float64)
        dst = output_doy_dir / f"{_DOY_FILE_PREFIX}{doy:03d}.mat"
        savemat(
            dst,
            {
                "OMEGA_AVG": omega_avg,
                "count_grid": count_grid,
                "used_years": np.asarray(used_years, dtype=np.int64),
            },
            do_compression=True,
        )
        doy_files += 1
        total_samples += len(samples)

    logger.info(
        "Stage B: built %d DOY climatology files from %d samples",
        doy_files,
        total_samples,
    )
    return {"doy_files": doy_files, "total_samples": total_samples}


# ─── Stage C: h/alpha map 提取 ──────────────────────────────────────────────


def extract_halpha_maps(
    omega_block_mat_path: Path,
    grid_shape: tuple[int, int],
) -> tuple[Any, Any]:
    """Stage C: 从 omega_block 输出提取 h/alpha map。

    Python ``omega_block`` ``.mat`` 已含 ``h_star_vec`` / ``alpha_star_vec``
    （1D npix 向量，来自 ``execute_omega_retrieval`` 返回值）。本函数 reshape
    为 2D grid。无需解析 Matlab ``R`` struct。

    量纲: h/alpha 无量纲（粗糙度/极化混合系数）。grid_shape 为 (nrows, ncols)。

    Args:
        omega_block_mat_path: omega_block ``.mat`` 文件路径。
        grid_shape: (nrows, ncols)。

    Returns:
        (h_map, alpha_map)：均为 2D numpy 数组，shape = grid_shape。
    """
    import numpy as np

    payload = _load_mat_payload_local(Path(omega_block_mat_path))
    h_vec = _pick_field_local(
        payload,
        ("h_star_vec", "h_exp0_vec", "h_star_map"),
    )
    alpha_vec = _pick_field_local(
        payload,
        ("alpha_star_vec", "alpha_exp0_vec", "alpha_star_map"),
    )
    h_arr = np.asarray(h_vec, dtype=np.float64).reshape(-1)
    alpha_arr = np.asarray(alpha_vec, dtype=np.float64).reshape(-1)
    npix = int(grid_shape[0]) * int(grid_shape[1])
    if h_arr.size != npix:
        raise ValueError(f"h_star_vec size {h_arr.size} != grid npix {npix}")
    if alpha_arr.size != npix:
        raise ValueError(f"alpha_star_vec size {alpha_arr.size} != grid npix {npix}")
    return h_arr.reshape(grid_shape), alpha_arr.reshape(grid_shape)


# ─── Stage D: 逐日 DDCA 回代（omega 固定） ─────────────────────────────────


def _process_day_pixel_chunk(
    start: int,
    end: int,
    *,
    temp_scheme: str,
    tbv_vec: Any,
    tbh_vec: Any,
    ts_vec: Any,
    tc_vec: Any,
    tg_vec: Any,
    tau_ini_vec: Any,
    h_vec: Any,
    alpha_vec: Any,
    omega_vec: Any,
    clay_vec: Any,
    albedo_vec: Any,
    porosity_vec: Any,
    ia_vec: Any,
    freq_ghz: float,
    lambda_tau: float,
) -> dict[str, Any]:
    """处理单日内一个像元分块（模块级函数，可被 pickle 到子进程）。

    对像元 ``[start:end)`` 逐像素调用 ``ddca_single_temp`` / ``ddca_dual_temp``，
    传入 ``omega_value=omega_vec[pixel]`` 作为固定值。

    量纲: tbv/tbh/ts/tc/tg 单位 K，ia_vec 单位度 (°)，freq_ghz 单位 GHz，
    其余无量纲。返回 ``{"start", "end", "sm", "vod"}``，sm/vod 为 1D 数组。
    """
    import numpy as np

    from algorithms.omega import ddca_dual_temp, ddca_single_temp

    chunk_npix = end - start
    sm_chunk = np.full(chunk_npix, np.nan, dtype=np.float64)
    vod_chunk = np.full(chunk_npix, np.nan, dtype=np.float64)

    use_dual = temp_scheme.upper() == "DUAL"
    for i in range(chunk_npix):
        pixel = start + i
        omega_value = float(omega_vec[pixel])
        h_value = float(h_vec[pixel])
        alpha_value = float(alpha_vec[pixel])
        porosity = float(porosity_vec[pixel])
        clay = float(clay_vec[pixel])
        theta_deg = float(ia_vec[pixel])
        tau_ini = float(tau_ini_vec[pixel])
        tbv = float(tbv_vec[pixel])
        tbh = float(tbh_vec[pixel])

        # 有效性检查：任一关键量 NaN 则跳过（DDCA 内部也会检查，但提前短路省开销）
        if not np.isfinite(omega_value) or not np.isfinite(h_value):
            continue
        if not np.isfinite(tbv) or not np.isfinite(tbh):
            continue
        if not np.isfinite(porosity) or porosity <= 0.02:
            continue

        if use_dual:
            tc = float(tc_vec[pixel])
            tg = float(tg_vec[pixel])
            if not np.isfinite(tc) or not np.isfinite(tg):
                continue
            sm, vod = ddca_dual_temp(
                tbv,
                tbh,
                tc,
                tg,
                tau_ini,
                h_value,
                clay,
                omega_value,
                porosity,
                freq_ghz,
                theta_deg,
                alpha_value,
                lambda_tau,
            )
        else:
            ts = float(ts_vec[pixel])
            if not np.isfinite(ts):
                continue
            sm, vod = ddca_single_temp(
                tbv,
                tbh,
                ts,
                tau_ini,
                h_value,
                clay,
                omega_value,
                porosity,
                freq_ghz,
                theta_deg,
                alpha_value,
                lambda_tau,
            )
        sm_chunk[i] = sm
        vod_chunk[i] = vod

    return {"start": start, "end": end, "sm": sm_chunk, "vod": vod_chunk}


def _build_pixel_chunks(npix: int, pixel_chunk_size: int) -> list[tuple[int, int]]:
    """将 npix 个像元切分为 ``[(start, end), ...]`` 分块列表。"""
    chunks: list[tuple[int, int]] = []
    size = max(1, int(pixel_chunk_size))
    for start in range(0, npix, size):
        end = min(start + size, npix)
        chunks.append((start, end))
    return chunks


def _run_day_chunks_serial(
    chunks: list[tuple[int, int]],
    *,
    temp_scheme: str,
    day_arrays: dict[str, Any],
    freq_ghz: float,
    lambda_tau: float,
) -> list[dict[str, Any]]:
    """串行执行单日所有像元分块（与原循环等价）。"""
    results: list[dict[str, Any]] = []
    for start, end in chunks:
        results.append(
            _process_day_pixel_chunk(
                start,
                end,
                temp_scheme=temp_scheme,
                tbv_vec=day_arrays["tbv"],
                tbh_vec=day_arrays["tbh"],
                ts_vec=day_arrays["ts"],
                tc_vec=day_arrays["tc"],
                tg_vec=day_arrays["tg"],
                tau_ini_vec=day_arrays["tau_ini"],
                h_vec=day_arrays["h"],
                alpha_vec=day_arrays["alpha"],
                omega_vec=day_arrays["omega"],
                clay_vec=day_arrays["clay"],
                albedo_vec=day_arrays["albedo"],
                porosity_vec=day_arrays["porosity"],
                ia_vec=day_arrays["ia"],
                freq_ghz=freq_ghz,
                lambda_tau=lambda_tau,
            )
        )
    return results


def _run_day_chunks_parallel(
    chunks: list[tuple[int, int]],
    *,
    temp_scheme: str,
    day_arrays: dict[str, Any],
    freq_ghz: float,
    lambda_tau: float,
    process_count: int,
    timeout_per_chunk: float | None = None,
) -> list[dict[str, Any]]:
    """使用 ProcessPoolExecutor 并行执行单日所有像元分块。

    使用 spawn 上下文以兼容 Celery prefork worker。任何异常向上抛出，由调用方
    catch 后回退到串行。
    """
    import os
    from concurrent.futures import (
        ALL_COMPLETED,
        ProcessPoolExecutor,
        wait,
    )

    from algorithms._parallel import get_spawn_context

    if timeout_per_chunk is None:
        env_val = os.environ.get("CGDA_PARALLEL_TIMEOUT_PER_CHUNK")
        try:
            timeout_per_chunk = float(env_val) if env_val else 300.0
        except ValueError:
            timeout_per_chunk = 300.0

    ctx = get_spawn_context()
    total_timeout = max(1.0, timeout_per_chunk) * len(chunks)

    ex = ProcessPoolExecutor(max_workers=process_count, mp_context=ctx)
    try:
        futures = [
            ex.submit(
                _process_day_pixel_chunk,
                start,
                end,
                temp_scheme=temp_scheme,
                tbv_vec=day_arrays["tbv"],
                tbh_vec=day_arrays["tbh"],
                ts_vec=day_arrays["ts"],
                tc_vec=day_arrays["tc"],
                tg_vec=day_arrays["tg"],
                tau_ini_vec=day_arrays["tau_ini"],
                h_vec=day_arrays["h"],
                alpha_vec=day_arrays["alpha"],
                omega_vec=day_arrays["omega"],
                clay_vec=day_arrays["clay"],
                albedo_vec=day_arrays["albedo"],
                porosity_vec=day_arrays["porosity"],
                ia_vec=day_arrays["ia"],
                freq_ghz=freq_ghz,
                lambda_tau=lambda_tau,
            )
            for start, end in chunks
        ]
        done, not_done = wait(futures, timeout=total_timeout, return_when=ALL_COMPLETED)
        if not_done:
            for fut in not_done:
                fut.cancel()
            raise TimeoutError(
                f"Parallel day chunk execution timed out after {total_timeout:.0f}s "
                f"({len(not_done)}/{len(futures)} chunks unfinished)"
            )
        return [fut.result() for fut in futures]
    finally:
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            ex.shutdown(wait=False)


def retrieve_daily_with_avg_omega(
    target_year: int,
    omega_avg_doy_dir: Path,
    h_map: Any,
    alpha_map: Any,
    datasource_selection: dict[str, Any],
    config: OmegaAvgConfig,
    daily_bundle_config: Any,
    lin_pix: list[int] | None,
    grid_shape: tuple[int, int],
    output_dir: Path,
    logger_adapter: Any = None,
) -> dict[str, Any]:
    """Stage D: 逐日 DDCA 回代，用平均 omega 产出 SM/VOD/OMEGA。

    对目标年每一天：
        1. 加载 DOY 对应的 ``OMEGA_AVG``（从 ``omega_avg_doy_dir``）。
        2. 复用 ``build_daily_bundle_for_date()`` 加载 TB/NDVI/SF/温度。
        3. 计算 ``tau_ini``（复用 ``algorithms.physics.tau_from_ndvi``）。
        4. 对有效像元调用 ``ddca_single_temp`` / ``ddca_dual_temp``，
           传入 ``omega_value=OMEGA_AVG[pixel]`` 作为固定值。
        5. 保存 ``{date}.mat``（含 SM/VOD/OMEGA 2D grid）。

    支持像元分块（``pixel_chunk_size``）控制内存；启用 ``enable_parallel`` 时
    使用 ``ProcessPoolExecutor`` 并行，失败自动回退串行。

    量纲: SM 单位 m³/m³，VOD/OMEGA 无量纲，温度单位 K。

    Args:
        target_year: 目标年份。
        omega_avg_doy_dir: DOY 气候态目录（Stage B 输出）。
        h_map: 粗糙度 h 的 2D grid（Stage C 输出）。
        alpha_map: 极化混合 alpha 的 2D grid（Stage C 输出）。
        datasource_selection: 数据源选择字典（透传给 ``build_daily_bundle_for_date``）。
        config: ``OmegaAvgConfig`` 实例。
        daily_bundle_config: ``DailyBundleConfig`` 实例。
        lin_pix: 像元线性索引选择（None 表示全网格）。
        grid_shape: (nrows, ncols)。
        output_dir: 逐日产品输出目录。
        logger_adapter: 可选的日志适配器（``emit_stage_start`` / ``emit_artifact`` 等）。

    Returns:
        统计字典：``{"days_processed", "days_skipped", "output_dir"}``。
    """
    from scipy.io import savemat

    import numpy as np

    from algorithms._parallel import (
        adjust_chunk_size_for_parallelism,
        auto_process_count,
    )
    from algorithms.physics import tau_from_ndvi
    from ingest.daily_bundle import build_daily_bundle_for_date

    omega_avg_doy_dir = Path(omega_avg_doy_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_scheme = str(getattr(daily_bundle_config, "temp_scheme", "ORIG_TS"))
    use_dual = temp_scheme.upper() == "DUAL"
    freq_ghz = float(config.freq_ghz)
    lambda_tau = float(config.lambda_tau)

    # h/alpha map 展平为 1D（全网格），后续按 lin_pix 子集
    h_full = np.asarray(h_map, dtype=np.float64).reshape(-1)
    alpha_full = np.asarray(alpha_map, dtype=np.float64).reshape(-1)

    # 像元子集工具：lin_pix 采用 1-based 约定（与 daily_bundle._normalize_selection 一致）
    if lin_pix is not None:
        sel = np.asarray(lin_pix, dtype=np.int64)
        if sel.size > 0 and sel.min() >= 1:
            sel = sel - 1
        h_vec = h_full[sel]
        alpha_vec = alpha_full[sel]
    else:
        h_vec = h_full
        alpha_vec = alpha_full

    npix = h_vec.size
    date_keys = _iter_date_keys_for_year(target_year)
    days_processed = 0
    days_skipped = 0

    if logger_adapter is not None:
        logger_adapter.emit_stage_start(
            "omega_avg_daily",
            f"Stage D: per-day DDCA retrieval for {target_year} ({len(date_keys)} days)",
        )

    # 预计算并行参数（一次）
    raw_chunks = _build_pixel_chunks(npix, config.pixel_chunk_size)
    process_count = 1
    chunk_size_adjusted = config.pixel_chunk_size
    if config.enable_parallel and len(raw_chunks) > 1:
        process_count = auto_process_count(chunk_count=len(raw_chunks))
        if process_count > 1:
            chunk_size_adjusted = adjust_chunk_size_for_parallelism(
                config.pixel_chunk_size, npix, process_count
            )
            raw_chunks = _build_pixel_chunks(npix, chunk_size_adjusted)

    for day_idx, date_key in enumerate(date_keys):
        # 1. 加载 DOY 对应的 OMEGA_AVG
        doy = datetime.strptime(date_key, _DATE_KEY_FORMAT).timetuple().tm_yday
        doy_file = omega_avg_doy_dir / f"{_DOY_FILE_PREFIX}{doy:03d}.mat"
        if not doy_file.exists():
            days_skipped += 1
            continue
        doy_payload = _load_mat_payload_local(doy_file)
        omega_avg_2d = _pick_field_local(doy_payload, ("OMEGA_AVG",))
        omega_full = np.asarray(omega_avg_2d, dtype=np.float64).reshape(-1)
        if lin_pix is not None:
            omega_vec = omega_full[sel]
        else:
            omega_vec = omega_full

        # 2. 加载逐日 bundle（复用 daily_bundle）
        try:
            bundle = build_daily_bundle_for_date(
                date_key,
                daily_bundle_config,
                datasource_selection,
                lin_pix=lin_pix,
            )
        except FileNotFoundError:
            days_skipped += 1
            continue

        tbv = np.asarray(bundle["TBv"], dtype=np.float64).reshape(-1)
        tbh = np.asarray(bundle["TBh"], dtype=np.float64).reshape(-1)
        ia = np.asarray(bundle.get("IA"), dtype=np.float64).reshape(-1)
        ts = np.asarray(bundle.get("Ts"), dtype=np.float64).reshape(-1)
        ndvi = np.asarray(bundle["NDVI"], dtype=np.float64).reshape(-1)
        sf = np.asarray(bundle["SF"], dtype=np.float64).reshape(-1)
        clay = np.asarray(bundle["CF"], dtype=np.float64).reshape(-1)
        albedo = np.asarray(bundle["Albedo"], dtype=np.float64).reshape(-1)
        porosity = np.asarray(bundle["porosity"], dtype=np.float64).reshape(-1)
        ndvi_v_max = np.asarray(bundle["NDVI_v_max"], dtype=np.float64).reshape(-1)
        ndvi_v_min = np.asarray(bundle["NDVI_v_min"], dtype=np.float64).reshape(-1)
        landcover = np.asarray(bundle["LC"], dtype=np.float64).reshape(-1)
        b_param = np.asarray(bundle["B"], dtype=np.float64).reshape(-1)

        if use_dual:
            tc = np.asarray(bundle.get("Ct"), dtype=np.float64).reshape(-1)
            tg = np.asarray(bundle.get("TG"), dtype=np.float64).reshape(-1)
        else:
            tc = np.full(npix, np.nan, dtype=np.float64)
            tg = np.full(npix, np.nan, dtype=np.float64)

        # 3. 计算 tau_ini（复用 tau_from_ndvi）
        tau_ini = tau_from_ndvi(
            ndvi=ndvi,
            ndvi_max=ndvi_v_max,
            ndvi_min=ndvi_v_min,
            landcover=landcover,
            b_param=b_param,
            stem_factor=sf,
            theta_deg=ia,
        )
        tau_ini = np.asarray(tau_ini, dtype=np.float64).reshape(-1)

        # 4. 像元分块 DDCA 回代
        day_arrays = {
            "tbv": tbv,
            "tbh": tbh,
            "ts": ts,
            "tc": tc,
            "tg": tg,
            "tau_ini": tau_ini,
            "h": h_vec,
            "alpha": alpha_vec,
            "omega": omega_vec,
            "clay": clay,
            "albedo": albedo,
            "porosity": porosity,
            "ia": ia,
        }

        chunk_results: list[dict[str, Any]] = []
        if config.enable_parallel and process_count > 1 and len(raw_chunks) > 1:
            try:
                chunk_results = _run_day_chunks_parallel(
                    raw_chunks,
                    temp_scheme=temp_scheme,
                    day_arrays=day_arrays,
                    freq_ghz=freq_ghz,
                    lambda_tau=lambda_tau,
                    process_count=process_count,
                )
            except (TimeoutError, BrokenProcessPool):
                # 并行失败（超时/进程池崩溃）→ 静默回退串行
                logger.warning(
                    "Parallel day chunks failed for %s, falling back to serial",
                    date_key,
                    exc_info=True,
                )
                chunk_results = _run_day_chunks_serial(
                    raw_chunks,
                    temp_scheme=temp_scheme,
                    day_arrays=day_arrays,
                    freq_ghz=freq_ghz,
                    lambda_tau=lambda_tau,
                )
            except Exception:
                # pickle/spawn 等其他失败 → 静默回退串行
                logger.warning(
                    "Parallel day chunks error for %s, falling back to serial",
                    date_key,
                    exc_info=True,
                )
                chunk_results = _run_day_chunks_serial(
                    raw_chunks,
                    temp_scheme=temp_scheme,
                    day_arrays=day_arrays,
                    freq_ghz=freq_ghz,
                    lambda_tau=lambda_tau,
                )
        else:
            chunk_results = _run_day_chunks_serial(
                raw_chunks,
                temp_scheme=temp_scheme,
                day_arrays=day_arrays,
                freq_ghz=freq_ghz,
                lambda_tau=lambda_tau,
            )

        # 5. 汇集 chunk 结果 → 1D → 2D grid
        sm_vec = np.full(npix, np.nan, dtype=np.float64)
        vod_vec = np.full(npix, np.nan, dtype=np.float64)
        for res in chunk_results:
            s, e = res["start"], res["end"]
            sm_vec[s:e] = res["sm"]
            vod_vec[s:e] = res["vod"]

        # lin_pix 子集 → 全网格 2D（未选取像元填 NaN）
        sm_2d = np.full(
            int(grid_shape[0]) * int(grid_shape[1]), np.nan, dtype=np.float64
        )
        vod_2d = np.full_like(sm_2d, np.nan)
        omega_out_2d = np.full_like(sm_2d, np.nan)
        if lin_pix is not None:
            sm_2d[sel] = sm_vec
            vod_2d[sel] = vod_vec
            omega_out_2d[sel] = omega_vec
        else:
            sm_2d[:] = sm_vec
            vod_2d[:] = vod_vec
            omega_out_2d[:] = omega_vec

        day_path = output_dir / f"{date_key}.mat"
        savemat(
            day_path,
            {
                "SM": sm_2d.reshape(grid_shape),
                "VOD": vod_2d.reshape(grid_shape),
                "OMEGA": omega_out_2d.reshape(grid_shape),
            },
            do_compression=True,
        )
        days_processed += 1

        if day_idx % config.print_every_days == 0:
            logger.info(
                "Stage D: %s (%d/%d) processed", date_key, day_idx + 1, len(date_keys)
            )
            if logger_adapter is not None:
                logger_adapter.emit_artifact(
                    "omega_avg_daily", str(day_path), "omega_avg_daily_mat"
                )

    if logger_adapter is not None:
        logger_adapter.emit_stage_end(
            "omega_avg_daily",
            f"Stage D: processed {days_processed} days, skipped {days_skipped}",
        )

    logger.info(
        "Stage D: processed %d days, skipped %d for year %d",
        days_processed,
        days_skipped,
        target_year,
    )
    return {
        "days_processed": days_processed,
        "days_skipped": days_skipped,
        "output_dir": str(output_dir),
    }


# ─── 内部 .mat 加载辅助（避免与 ingest 模块循环导入） ──────────────────────


def _load_mat_payload_local(file_path: Path) -> dict[str, Any]:
    """加载 .mat 文件为字典（本地辅助，避免循环依赖）。"""
    from ingest.mat_bundle import load_mat_file

    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"MAT file not found: {file_path}")
    return load_mat_file(file_path)


def _pick_field_local(
    payload: dict[str, Any], aliases: tuple[str, ...], *, required: bool = True
) -> Any:
    """从字典按别名取字段（本地辅助）。"""
    for alias in aliases:
        if alias in payload:
            return payload[alias]
    if required:
        raise KeyError(f"Missing field. Tried aliases: {aliases}")
    return None
