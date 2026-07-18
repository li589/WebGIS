from __future__ import annotations

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from algorithms.inversion import ddca_retrieve_grid, retrieve_dynamic_h_grid
from algorithms.physics import _FREQ_GHZ_MAX, _FREQ_GHZ_MIN, tau_from_ndvi
from ingest.mat_bundle import get_first_available, load_mat_file, normalize_aliases_param

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BlockFieldConfig:
    """批量反演 .mat 字段别名配置。

    各 aliases 字段对应 .mat 文件中的变量名，按优先级匹配。
    量纲: TBv/TBh 单位 K（亮温），IA 单位度（入射角），Ts 单位 K（地表温度），
    NDVI 无量纲 (0-1)，SF 单位 kg/m²（茎干因子），Albedo 无量纲，B 无量纲（经验系数），
    CF 无量纲 (0-1)（黏粒含量），porosity 无量纲 (0-1)，LC 为 IGBP 类型代码（整数），
    NDVI_v_max/NDVI_v_min 无量纲，H/DH 无量纲（粗糙度参数）。
    """

    tbv_mat_aliases: tuple[str, ...] = ("TBv_mat",)
    tbh_mat_aliases: tuple[str, ...] = ("TBh_mat",)
    ia_mat_aliases: tuple[str, ...] = ("IA_mat",)
    ts_mat_aliases: tuple[str, ...] = ("Ts_mat",)
    ndvi_mat_aliases: tuple[str, ...] = ("NDVI_mat",)
    sf_mat_aliases: tuple[str, ...] = ("SF_mat",)
    albedo_aliases: tuple[str, ...] = ("Albedo", "ALBEDO")
    b_aliases: tuple[str, ...] = ("B", "b")
    clay_fraction_aliases: tuple[str, ...] = ("CF",)
    porosity_aliases: tuple[str, ...] = ("porosity", "Porosity")
    landcover_aliases: tuple[str, ...] = ("LC", "IGBP_9km_12")
    ndvi_v_max_aliases: tuple[str, ...] = ("NDVI_v_max",)
    ndvi_v_min_aliases: tuple[str, ...] = ("NDVI_v_min",)
    h_static_aliases: tuple[str, ...] = ("H", "h")
    dh_aliases: tuple[str, ...] = ("DH_mat", "DH", "dh_mat")


def build_block_field_config(params: dict[str, Any]) -> BlockFieldConfig:
    """从参数字典构建 BlockFieldConfig，允许覆盖各字段的默认别名。"""
    return BlockFieldConfig(
        tbv_mat_aliases=normalize_aliases_param(params.get("tbv_mat_aliases"), ("TBv_mat",)),
        tbh_mat_aliases=normalize_aliases_param(params.get("tbh_mat_aliases"), ("TBh_mat",)),
        ia_mat_aliases=normalize_aliases_param(params.get("ia_mat_aliases"), ("IA_mat",)),
        ts_mat_aliases=normalize_aliases_param(params.get("ts_mat_aliases"), ("Ts_mat",)),
        ndvi_mat_aliases=normalize_aliases_param(params.get("ndvi_mat_aliases"), ("NDVI_mat",)),
        sf_mat_aliases=normalize_aliases_param(params.get("sf_mat_aliases"), ("SF_mat",)),
        albedo_aliases=normalize_aliases_param(params.get("albedo_aliases"), ("Albedo", "ALBEDO")),
        b_aliases=normalize_aliases_param(params.get("b_aliases"), ("B", "b")),
        clay_fraction_aliases=normalize_aliases_param(params.get("clay_fraction_aliases"), ("CF",)),
        porosity_aliases=normalize_aliases_param(params.get("porosity_aliases"), ("porosity", "Porosity")),
        landcover_aliases=normalize_aliases_param(params.get("landcover_aliases"), ("LC", "IGBP_9km_12")),
        ndvi_v_max_aliases=normalize_aliases_param(params.get("ndvi_v_max_aliases"), ("NDVI_v_max",)),
        ndvi_v_min_aliases=normalize_aliases_param(params.get("ndvi_v_min_aliases"), ("NDVI_v_min",)),
        h_static_aliases=normalize_aliases_param(params.get("h_static_aliases"), ("H", "h")),
        dh_aliases=normalize_aliases_param(params.get("dh_aliases"), ("DH_mat", "DH", "dh_mat")),
    )


def normalize_date_keys(value: Any, fallback_count: int | None = None) -> list[str]:
    """将输入规范化为日期字符串列表。输入可为 None/标量/数组，返回 YYYYMMDD 字符串列表。"""
    import numpy as np

    if value is None:
        if fallback_count is None:
            return []
        return [f"day_{index + 1:04d}" for index in range(fallback_count)]

    array = np.asarray(value)
    if array.ndim == 0:
        return [str(array.item())]
    flat = array.reshape(-1)
    result: list[str] = []
    for item in flat:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _broadcast_matrix(value: Any, target_shape: tuple[int, int], *, name: str) -> Any:
    """将标量/1D/2D 数组广播到 (nt, npix) 目标形状。"""
    import numpy as np

    array = np.asarray(value, dtype=np.float64)
    if array.shape == target_shape:
        return array
    if array.ndim == 0:
        return np.full(target_shape, array.item(), dtype=np.float64)
    if array.ndim == 1:
        if array.size == target_shape[1]:
            return np.broadcast_to(array.reshape(1, target_shape[1]), target_shape).astype(np.float64, copy=False)
        if array.size == target_shape[0]:
            return np.broadcast_to(array.reshape(target_shape[0], 1), target_shape).astype(np.float64, copy=False)
        if array.size == target_shape[0] * target_shape[1]:
            return array.reshape(target_shape)
    if array.ndim == 2:
        try:
            return np.broadcast_to(array, target_shape).astype(np.float64, copy=False)
        except ValueError:
            pass
    raise ValueError(f"Cannot broadcast {name} from shape {array.shape} to {target_shape}")


def _as_time_pixel_matrix(value: Any, *, name: str, target_shape: tuple[int, int] | None = None) -> Any:
    """将输入规范化为 (nt, npix) 时间-像素矩阵。标量→(1,1)，1D→(1,N)，2D 直接使用。"""
    import numpy as np

    array = np.asarray(value, dtype=np.float64)
    if array.ndim == 0:
        array = array.reshape(1, 1)
    elif array.ndim == 1:
        array = array.reshape(1, -1)
    elif array.ndim != 2:
        raise ValueError(f"{name} must be a scalar, 1-D, or 2-D array; got shape {array.shape}")
    if target_shape is None:
        return array
    return _broadcast_matrix(array, target_shape, name=name)


def _as_static_vector(value: Any, pixel_count: int, *, name: str) -> Any:
    """将输入规范化为长度 pixel_count 的静态向量。标量广播为全 1 向量。"""
    import numpy as np

    array = np.asarray(value, dtype=np.float64).reshape(-1)
    if array.size == pixel_count:
        return array
    if array.size == 1:
        return np.full(pixel_count, float(array[0]), dtype=np.float64)
    raise ValueError(f"{name} must contain 1 or {pixel_count} values; got {array.size}")


def load_h_matrix(
    payload: dict[str, Any],
    field_config: BlockFieldConfig,
    *,
    dh_mat_path: str | Path | None = None,
    fallback_h: Any | None = None,
    nt: int | None = None,
) -> Any:
    """加载粗糙度参数 H 矩阵（无量纲）。

    优先级: dh_mat_path 指定的文件 > payload 中的 DH 字段 > fallback_h 静态值。
    若提供 fallback_h 且 nt 已指定，则将静态向量沿时间维度重复。
    """
    import numpy as np

    if dh_mat_path is not None:
        dh_payload = load_mat_file(dh_mat_path)
        return np.asarray(get_first_available(dh_payload, list(field_config.dh_aliases)), dtype=np.float64)

    try:
        return np.asarray(get_first_available(payload, list(field_config.dh_aliases)), dtype=np.float64)
    except KeyError:
        if fallback_h is None:
            raise
        base = np.asarray(fallback_h, dtype=np.float64).reshape(-1)
        if nt is None:
            return base
        return np.repeat(base[None, :], nt, axis=0)


# ─── 多进程并行化：chunk 级 worker 与分发函数 ────────────────────────────────
# Sprint 3.7: ThreadPoolExecutor 基准测试证实 GIL 争用导致负加速（0.52x-0.79x）。
# 改用 ProcessPoolExecutor + spawn 上下文绕过 GIL；以下函数全部模块级以支持 pickle。


def _process_chunk(
    start: int,
    end: int,
    *,
    mode: str,
    nt: int,
    ndvi_mat_chunk: Any,
    ndvi_v_max_chunk: Any,
    ndvi_v_min_chunk: Any,
    landcover_chunk: Any,
    b_param_chunk: Any,
    sf_mat_chunk: Any,
    ia_mat_chunk: Any,
    tbv_mat_chunk: Any,
    tbh_mat_chunk: Any,
    ts_mat_chunk: Any,
    clay_fraction_chunk: Any,
    albedo_chunk: Any,
    porosity_chunk: Any,
    h_mat_chunk: Any,
    freq_ghz: float,
) -> dict[str, Any]:
    """处理单个像素分块（模块级函数，可被 pickle 到子进程）。

    量纲: 输入 tbv_mat_chunk/tbh_mat_chunk/ts_mat_chunk 单位 K，freq_ghz 单位 GHz，
    ia_mat_chunk 单位度 (°)，其余无量纲。返回 dict 含 tau_ini/dh/sm/vod chunk 矩阵。
    """
    import numpy as np

    chunk_npix = end - start
    tau_chunk = tau_from_ndvi(
        ndvi=ndvi_mat_chunk,
        ndvi_max=ndvi_v_max_chunk,
        ndvi_min=ndvi_v_min_chunk,
        landcover=landcover_chunk,
        b_param=b_param_chunk,
        stem_factor=sf_mat_chunk,
        theta_deg=ia_mat_chunk,
    )

    out: dict[str, Any] = {"start": start, "end": end, "tau_ini": tau_chunk}

    if mode == "dh":
        dh_chunk = np.full((nt, chunk_npix), np.nan, dtype=np.float64)
        for day_index in range(nt):
            dh_chunk[day_index, :] = retrieve_dynamic_h_grid(
                tbv_mat_chunk[day_index, :],
                tbh_mat_chunk[day_index, :],
                ts_mat_chunk[day_index, :],
                tau_chunk[day_index, :],
                clay_fraction_chunk,
                albedo_chunk,
                porosity_chunk,
                freq_ghz,
                ia_mat_chunk[day_index, :],
            )
        out["dh"] = dh_chunk
    else:  # ddca
        sm_chunk = np.full((nt, chunk_npix), np.nan, dtype=np.float64)
        vod_chunk = np.full((nt, chunk_npix), np.nan, dtype=np.float64)
        for day_index in range(nt):
            sm_day, vod_day = ddca_retrieve_grid(
                tbv_mat_chunk[day_index, :],
                tbh_mat_chunk[day_index, :],
                ts_mat_chunk[day_index, :],
                tau_chunk[day_index, :],
                h_mat_chunk[day_index, :],
                clay_fraction_chunk,
                albedo_chunk,
                porosity_chunk,
                freq_ghz,
                ia_mat_chunk[day_index, :],
            )
            sm_chunk[day_index, :] = sm_day
            vod_chunk[day_index, :] = vod_day
        out["sm"] = sm_chunk
        out["vod"] = vod_chunk

    return out


def _prepare_chunk_kwargs(
    matrices: dict[str, Any],
    cols: slice,
    mode: str,
) -> dict[str, Any]:
    """从主矩阵切出一个 chunk 所需的全部参数字典。"""
    return {
        "ndvi_mat_chunk": matrices["ndvi_mat"][:, cols],
        "ndvi_v_max_chunk": matrices["ndvi_v_max"][cols],
        "ndvi_v_min_chunk": matrices["ndvi_v_min"][cols],
        "landcover_chunk": matrices["landcover"][cols],
        "b_param_chunk": matrices["b_param"][cols],
        "sf_mat_chunk": matrices["sf_mat"][:, cols],
        "ia_mat_chunk": matrices["ia_mat"][:, cols],
        "tbv_mat_chunk": matrices["tbv_mat"][:, cols],
        "tbh_mat_chunk": matrices["tbh_mat"][:, cols],
        "ts_mat_chunk": matrices["ts_mat"][:, cols],
        "clay_fraction_chunk": matrices["clay_fraction"][cols],
        "albedo_chunk": matrices["albedo"][cols],
        "porosity_chunk": matrices["porosity"][cols],
        "h_mat_chunk": (
            matrices["h_mat"][:, cols]
            if mode == "ddca" and matrices.get("h_mat") is not None
            else None
        ),
    }


def _run_chunks_serial(
    chunks: list[tuple[int, int]],
    *,
    mode: str,
    nt: int,
    matrices: dict[str, Any],
    freq_ghz: float,
) -> list[dict[str, Any]]:
    """串行执行所有 chunk（与原循环等价）。"""
    results: list[dict[str, Any]] = []
    for start, end in chunks:
        cols = slice(start, end)
        sub_kwargs = _prepare_chunk_kwargs(matrices, cols, mode)
        results.append(
            _process_chunk(start, end, mode=mode, nt=nt, freq_ghz=freq_ghz, **sub_kwargs)
        )
    return results


def _run_chunks_parallel(
    chunks: list[tuple[int, int]],
    *,
    mode: str,
    nt: int,
    matrices: dict[str, Any],
    freq_ghz: float,
    process_count: int,
    timeout_per_chunk: float | None = None,
) -> list[dict[str, Any]]:
    """使用 ProcessPoolExecutor 并行执行所有 chunk。

    任何异常向上抛出，由调用方 catch 后回退到串行。使用 spawn 上下文以兼容
    Celery prefork worker（避免 fork-after-thread 死锁）。

    Args:
        timeout_per_chunk: 每个 chunk 允许的最大耗时（秒）；None 表示通过环境变量
            ``CGDA_PARALLEL_TIMEOUT_PER_CHUNK`` 读取（默认 300s）。总超时为
            ``timeout_per_chunk * len(chunks)``。超时后取消未开始的 future 并抛出
            ``TimeoutError``，由调用方回退串行；运行中的子进程由 OS 回收。
            目的：防止子进程 scipy 死循环导致主进程永久阻塞。

    Celery time_limit 交互:
        Celery 默认 ``task_time_limit=360s``（硬超时 SIGKILL）、
        ``task_soft_time_limit=300s``（软超时抛 ``SoftTimeLimitExceeded``）。
        若 ``timeout_per_chunk * len(chunks)`` 超过 ``task_soft_time_limit``，
        Celery 会先触发软超时。建议部署时确保::

            timeout_per_chunk * chunk_count < task_soft_time_limit

        例如 chunk_count=4 时，``CGDA_PARALLEL_TIMEOUT_PER_CHUNK=60``（总 240s < 300s）。
        Celery 软超时异常继承 ``Exception``，会被本模块的串行回退捕获。
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

    # 按提交顺序构造 future 列表，保证结果顺序与 chunks 一致
    submissions = [
        (start, end, _prepare_chunk_kwargs(matrices, slice(start, end), mode))
        for start, end in chunks
    ]

    # 总超时：per_chunk × chunk 数（保守估计，假设最慢 chunk 耗时 per_chunk）
    total_timeout = max(1.0, timeout_per_chunk) * len(chunks)

    # 不用 with 语句：超时后需要 shutdown(wait=False) 避免阻塞在运行中的子进程
    ex = ProcessPoolExecutor(max_workers=process_count, mp_context=ctx)
    try:
        futures = [
            ex.submit(
                _process_chunk,
                start,
                end,
                mode=mode,
                nt=nt,
                freq_ghz=freq_ghz,
                **sub_kwargs,
            )
            for start, end, sub_kwargs in submissions
        ]
        done, not_done = wait(futures, timeout=total_timeout, return_when=ALL_COMPLETED)

        if not_done:
            # 取消未开始的 future；运行中的子进程由 shutdown(wait=False) 处理
            for fut in not_done:
                fut.cancel()
            raise TimeoutError(
                f"Parallel chunk execution timed out after {total_timeout:.0f}s "
                f"({len(not_done)}/{len(futures)} chunks unfinished)"
            )

        results: list[dict[str, Any]] = []
        for fut in futures:
            results.append(fut.result())  # 顺序与提交一致
        return results
    finally:
        # wait=False：不等待运行中的子进程；cancel_futures 取消队列中的
        # （Python 3.9+；旧版本忽略 cancel_futures 参数）
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            ex.shutdown(wait=False)


def execute_block_inversion(
    payload: dict[str, Any],
    *,
    mode: str,
    freq_ghz: float,
    pixel_chunk_size: int = 2000,
    dh_mat_path: str | Path | None = None,
    field_config: BlockFieldConfig | None = None,
    max_workers: int | None = None,
) -> dict[str, Any]:
    """批量反演主入口。

    量纲: payload 含 TBv_mat/TBh_mat（单位 K）、IA_mat（单位度）、Ts_mat（单位 K）、
    NDVI_mat（无量纲 0-1）、Albedo（无量纲）、B（无量纲经验系数）、CF（黏粒含量无量纲 0-1）、
    porosity（无量纲 0-1）、LC（IGBP 整数代码）。freq_ghz 单位 GHz。
    mode 为 "dh"（动态 H 反演）或 "ddca"（双通道反演）。
    返回字典含 SM_mat（单位 m³/m³）、VOD_mat（无量纲）、DH_mat/H_used_mat（无量纲）、
    Tau_ini_mat（无量纲）、date_keys（YYYYMMDD 字符串列表）。

    Args:
        max_workers: 并行进程数上限；None 表示根据 CPU 物理核数与可用内存自动计算
            （由 algorithms._parallel.auto_process_count 决定）。=1 或自动计算结果为 1
            时走串行路径。任何并行基础设施失败（pickle/spawn/memory）都回退到串行，
            不抛出给上层调用方。
    """
    import numpy as np

    if not (_FREQ_GHZ_MIN <= freq_ghz <= _FREQ_GHZ_MAX):
        raise ValueError(
            f"freq_ghz must be in [{_FREQ_GHZ_MIN}, {_FREQ_GHZ_MAX}] GHz, got {freq_ghz}"
        )

    field_config = field_config or BlockFieldConfig()

    tbv_mat = _as_time_pixel_matrix(
        get_first_available(payload, list(field_config.tbv_mat_aliases)),
        name="tbv_mat",
    )
    nt, npix = tbv_mat.shape
    target_shape = (nt, npix)
    tbh_mat = _as_time_pixel_matrix(
        get_first_available(payload, list(field_config.tbh_mat_aliases)),
        name="tbh_mat",
        target_shape=target_shape,
    )
    ia_mat = _as_time_pixel_matrix(
        get_first_available(payload, list(field_config.ia_mat_aliases)),
        name="ia_mat",
        target_shape=target_shape,
    )
    ts_mat = _as_time_pixel_matrix(
        get_first_available(payload, list(field_config.ts_mat_aliases)),
        name="ts_mat",
        target_shape=target_shape,
    )
    ndvi_mat = _as_time_pixel_matrix(
        get_first_available(payload, list(field_config.ndvi_mat_aliases)),
        name="ndvi_mat",
        target_shape=target_shape,
    )
    sf_mat = _as_time_pixel_matrix(
        get_first_available(payload, list(field_config.sf_mat_aliases)),
        name="sf_mat",
        target_shape=target_shape,
    )

    albedo = _as_static_vector(get_first_available(payload, list(field_config.albedo_aliases)), npix, name="albedo")
    b_param = _as_static_vector(get_first_available(payload, list(field_config.b_aliases)), npix, name="b_param")
    clay_fraction = _as_static_vector(
        get_first_available(payload, list(field_config.clay_fraction_aliases)),
        npix,
        name="clay_fraction",
    )
    porosity = _as_static_vector(get_first_available(payload, list(field_config.porosity_aliases)), npix, name="porosity")
    landcover = _as_static_vector(get_first_available(payload, list(field_config.landcover_aliases)), npix, name="landcover")
    ndvi_v_max = _as_static_vector(
        get_first_available(payload, list(field_config.ndvi_v_max_aliases)),
        npix,
        name="ndvi_v_max",
    )
    ndvi_v_min = _as_static_vector(
        get_first_available(payload, list(field_config.ndvi_v_min_aliases)),
        npix,
        name="ndvi_v_min",
    )
    static_h = _as_static_vector(get_first_available(payload, list(field_config.h_static_aliases)), npix, name="static_h")
    tau_ini_mat = np.full((nt, npix), np.nan, dtype=np.float64)
    results: dict[str, Any] = {
        "Tau_ini_mat": tau_ini_mat,
        "date_keys": normalize_date_keys(payload.get("date_keys"), fallback_count=nt),
        "missing_dates": normalize_date_keys(payload.get("missing_dates")),
    }

    if mode == "dh":
        dh_mat = np.full((nt, npix), np.nan, dtype=np.float64)
        results["DH_mat"] = dh_mat
    elif mode == "ddca":
        h_mat = load_h_matrix(payload, field_config, dh_mat_path=dh_mat_path, fallback_h=static_h, nt=nt)
        sm_mat = np.full((nt, npix), np.nan, dtype=np.float64)
        vod_mat = np.full((nt, npix), np.nan, dtype=np.float64)
        results["H_used_mat"] = h_mat
        results["SM_mat"] = sm_mat
        results["VOD_mat"] = vod_mat
    else:
        raise ValueError(f"Unsupported block inversion mode: {mode}")

    # ─── 并行化决策（Sprint 3.7）─────────────────────────────────
    # 估算 chunk 数并决定进程数；chunk_size 可能被自动缩小以产生足够 chunk 支持并行。
    from algorithms._parallel import (
        adjust_chunk_size_for_parallelism,
        auto_process_count,
    )

    matrices: dict[str, Any] = {
        "ndvi_mat": ndvi_mat,
        "ndvi_v_max": ndvi_v_max,
        "ndvi_v_min": ndvi_v_min,
        "landcover": landcover,
        "b_param": b_param,
        "sf_mat": sf_mat,
        "ia_mat": ia_mat,
        "tbv_mat": tbv_mat,
        "tbh_mat": tbh_mat,
        "ts_mat": ts_mat,
        "clay_fraction": clay_fraction,
        "albedo": albedo,
        "porosity": porosity,
        "h_mat": results.get("H_used_mat"),
    }

    initial_chunk_size = max(1, int(pixel_chunk_size))
    initial_chunk_count = (npix + initial_chunk_size - 1) // initial_chunk_size
    process_count = auto_process_count(
        chunk_count=initial_chunk_count,
        max_workers=max_workers,
    )

    chunk_size = adjust_chunk_size_for_parallelism(
        initial_chunk_size,
        npix,
        process_count,
    )
    chunks = [(s, min(s + chunk_size, npix)) for s in range(0, npix, chunk_size)]

    use_parallel = process_count > 1 and len(chunks) >= 2

    if use_parallel:
        try:
            chunk_results = _run_chunks_parallel(
                chunks,
                mode=mode,
                nt=nt,
                matrices=matrices,
                freq_ghz=freq_ghz,
                process_count=process_count,
            )
        except Exception as exc:
            # 关键降级：编程 bug（AttributeError/NameError/TypeError/ImportError/SyntaxError）
            # 必须向上传播避免被掩盖；其余运行时异常（pickle/spawn/memory/网络）回退串行。
            if isinstance(
                exc, (AttributeError, NameError, TypeError, ImportError, SyntaxError)
            ):
                raise
            logger.warning(
                "Parallel chunk execution failed (%s: %s); falling back to serial",
                type(exc).__name__,
                exc,
            )
            chunk_results = _run_chunks_serial(
                chunks,
                mode=mode,
                nt=nt,
                matrices=matrices,
                freq_ghz=freq_ghz,
            )
    else:
        chunk_results = _run_chunks_serial(
            chunks,
            mode=mode,
            nt=nt,
            matrices=matrices,
            freq_ghz=freq_ghz,
        )

    # ─── 合并 chunk 结果到 result 矩阵 ─────────────────────────────
    for cr in chunk_results:
        start = cr["start"]
        end = cr["end"]
        cols = slice(start, end)
        tau_ini_mat[:, cols] = cr["tau_ini"]
        if mode == "dh":
            results["DH_mat"][:, cols] = cr["dh"]
        else:
            results["SM_mat"][:, cols] = cr["sm"]
            results["VOD_mat"][:, cols] = cr["vod"]

    return results
