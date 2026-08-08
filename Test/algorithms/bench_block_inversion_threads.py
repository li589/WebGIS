"""Sprint 3.6/3.7: block_inversion 并行化基准测试。

Sprint 3.6 (D2): ThreadPoolExecutor 评估
- 结论：0.52x-0.79x（更慢），不引入并行化。
- 根因：retrieve_dynamic_h_grid 内 Python for 循环在 least_squares 调用间持有 GIL。

Sprint 3.7: ProcessPoolExecutor 评估（多进程绕过 GIL）
- 使用 spawn 上下文（兼容 Celery prefork）
- 进程数根据 CPU 物理核数 + 可用内存自动分配

本脚本：
1. 构造合成输入数据（nt 天 × npix 像素）
2. 串行执行 chunk 循环（baseline）
3. 用 ThreadPoolExecutor 并行执行（对照）
4. 用 ProcessPoolExecutor 并行执行（新增）
5. 用 execute_block_inversion(max_workers=N) 端到端测试
6. 对比耗时与数值一致性

运行：
    cd Code/algorithms/providers/Python
    python -m tests.bench_block_inversion_threads
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np

# 确保 algorithms 包在路径中
algo_root = Path(__file__).resolve().parent.parent
if str(algo_root) not in sys.path:
    sys.path.insert(0, str(algo_root))

from algorithms._parallel import get_spawn_context  # noqa: E402
from algorithms.inversion import retrieve_dynamic_h_grid  # noqa: E402


def make_synthetic_data(nt: int, npix: int, seed: int = 42) -> dict:
    """构造合成反演输入数据（物理量级接近真实 L-band SMAP 场景）。"""
    rng = np.random.default_rng(seed)
    # TB ~ 200-280 K（地表亮度温度典型范围）
    tbv = rng.uniform(220.0, 280.0, size=(nt, npix))
    tbh = rng.uniform(200.0, 260.0, size=(nt, npix))
    # Ts ~ 280-305 K（地表温度）
    ts = rng.uniform(280.0, 305.0, size=(nt, npix))
    # tau ~ 0.1-0.6（植被光学厚度）
    tau = rng.uniform(0.1, 0.6, size=(nt, npix))
    # clay_fraction ~ 0.1-0.5（黏粒含量）
    clay = rng.uniform(0.1, 0.5, size=npix)
    # albedo ~ 0.05-0.15（反照率）
    albedo = rng.uniform(0.05, 0.15, size=npix)
    # porosity ~ 0.4-0.5（孔隙度）
    porosity = rng.uniform(0.4, 0.5, size=npix)
    # theta_deg ~ 35-45（入射角，SMAP ~ 40°）
    theta = rng.uniform(35.0, 45.0, size=(nt, npix))
    return {
        "tbv": tbv,
        "tbh": tbh,
        "ts": ts,
        "tau": tau,
        "clay": clay,
        "albedo": albedo,
        "porosity": porosity,
        "theta": theta,
    }


def run_serial(
    data: dict, nt: int, npix: int, chunk_size: int, freq_ghz: float
) -> np.ndarray:
    """串行 chunk 循环（与 execute_block_inversion 内部逻辑一致）。

    结构：外层 chunk 循环 → 内层 day 循环 → retrieve_dynamic_h_grid(1D per day)。
    """
    output = np.full((nt, npix), np.nan, dtype=np.float64)
    for start in range(0, npix, chunk_size):
        end = min(start + chunk_size, npix)
        cols = slice(start, end)
        for day_index in range(nt):
            output[day_index, start:end] = retrieve_dynamic_h_grid(
                data["tbv"][day_index, start:end],
                data["tbh"][day_index, start:end],
                data["ts"][day_index, start:end],
                data["tau"][day_index, start:end],
                data["clay"][cols],
                data["albedo"][cols],
                data["porosity"][cols],
                freq_ghz,
                data["theta"][day_index, start:end],
            )
    return output


def run_threaded(
    data: dict,
    nt: int,
    npix: int,
    chunk_size: int,
    freq_ghz: float,
    max_workers: int,
) -> np.ndarray:
    """ThreadPoolExecutor 并行 chunk 循环。

    每个 chunk 独立处理（内含 day 循环），chunk 间用线程池并行。
    """
    output = np.full((nt, npix), np.nan, dtype=np.float64)

    def process_chunk(start: int) -> tuple[int, np.ndarray]:
        end = min(start + chunk_size, npix)
        cols = slice(start, end)
        chunk_out = np.full((nt, end - start), np.nan, dtype=np.float64)
        for day_index in range(nt):
            chunk_out[day_index, :] = retrieve_dynamic_h_grid(
                data["tbv"][day_index, start:end],
                data["tbh"][day_index, start:end],
                data["ts"][day_index, start:end],
                data["tau"][day_index, start:end],
                data["clay"][cols],
                data["albedo"][cols],
                data["porosity"][cols],
                freq_ghz,
                data["theta"][day_index, start:end],
            )
        return start, chunk_out

    chunks = list(range(0, npix, chunk_size))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for start, chunk_out in pool.map(process_chunk, chunks):
            end = min(start + chunk_size, npix)
            output[:, start:end] = chunk_out
    return output


def _bench_process_chunk_worker(
    start: int,
    end: int,
    data: dict,
    nt: int,
    freq_ghz: float,
) -> tuple[int, int, np.ndarray]:
    """ProcessPoolExecutor worker：处理单个 chunk（模块级，可 pickle）。

    复用 retrieve_dynamic_h_grid 的 dh 模式逻辑。
    """
    cols = slice(start, end)
    chunk_out = np.full((nt, end - start), np.nan, dtype=np.float64)
    for day_index in range(nt):
        chunk_out[day_index, :] = retrieve_dynamic_h_grid(
            data["tbv"][day_index, start:end],
            data["tbh"][day_index, start:end],
            data["ts"][day_index, start:end],
            data["tau"][day_index, start:end],
            data["clay"][cols],
            data["albedo"][cols],
            data["porosity"][cols],
            freq_ghz,
            data["theta"][day_index, start:end],
        )
    return start, end, chunk_out


def run_process_pool(
    data: dict,
    nt: int,
    npix: int,
    chunk_size: int,
    freq_ghz: float,
    max_workers: int,
) -> np.ndarray:
    """ProcessPoolExecutor + spawn 上下文并行 chunk 循环。

    绕过 GIL；每个 chunk 在独立进程内执行。
    """
    output = np.full((nt, npix), np.nan, dtype=np.float64)
    chunks = [(s, min(s + chunk_size, npix)) for s in range(0, npix, chunk_size)]
    ctx = get_spawn_context()

    with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as pool:
        futures = [
            pool.submit(_bench_process_chunk_worker, s, e, data, nt, freq_ghz)
            for s, e in chunks
        ]
        for fut in futures:
            start, end, chunk_out = fut.result()
            output[:, start:end] = chunk_out
    return output


def run_via_execute_block_inversion(
    data: dict,
    nt: int,
    npix: int,
    chunk_size: int,
    freq_ghz: float,
    max_workers: int | None,
) -> np.ndarray:
    """端到端通过 execute_block_inversion(max_workers=...) 运行。

    验证实际生产路径的性能（包含 chunk_size 自动调整 + dispatch 开销）。
    """
    from algorithms.block_inversion import execute_block_inversion

    payload = {
        "TBv_mat": data["tbv"],
        "TBh_mat": data["tbh"],
        "Ts_mat": data["ts"],
        "NDVI_mat": np.full((nt, npix), 0.3),  # 占位，tau_from_ndvi 内部计算
        "SF_mat": np.full((nt, npix), 1.0),
        "IA_mat": data["theta"],
        "Albedo": data["albedo"],
        "B": np.full(npix, 1.0),
        "CF": data["clay"],
        "porosity": data["porosity"],
        "LC": np.full(npix, 6, dtype=int),
        "NDVI_v_max": np.full(npix, 0.8),
        "NDVI_v_min": np.full(npix, 0.1),
        "H": np.full(npix, 0.3),
    }
    result = execute_block_inversion(
        payload,
        mode="dh",
        freq_ghz=freq_ghz,
        pixel_chunk_size=chunk_size,
        max_workers=max_workers,
    )
    return result["DH_mat"]


def bench_once(label: str, func, *args, **kwargs) -> tuple[float, np.ndarray]:
    t0 = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed = time.perf_counter() - t0
    print(f"  {label}: {elapsed:.3f}s")
    return elapsed, result


def main() -> None:
    # 数据规模：平衡基准测试意义与运行时间。
    # nt=5 天 × npix=2000 像素 × chunk_size=500 → 4 个 chunk，每 chunk 5×500=2500 次 least_squares
    nt = 5
    npix = 2000
    chunk_size = 500
    freq_ghz = 1.26  # L-band

    print("=== Sprint 3.6/3.7 block_inversion 并行化基准测试 ===")
    print("  ThreadPoolExecutor（已知失败）vs ProcessPoolExecutor（Sprint 3.7 新增）")
    print(f"数据规模: nt={nt} 天, npix={npix} 像素, chunk_size={chunk_size}")
    chunk_count = (npix + chunk_size - 1) // chunk_size
    print(f"chunk 数: {chunk_count}")
    print(f"freq_ghz={freq_ghz}, mode=dh (retrieve_dynamic_h_grid)")
    print()

    data = make_synthetic_data(nt, npix)

    # 预热（首次 import scipy 有开销；spawn 子进程首次启动也需 import）
    print("预热（serial + 1 进程 ProcessPool 启动）...", flush=True)
    _ = run_serial(data, nt, min(npix, 200), 200, freq_ghz)
    _ = run_process_pool(data, nt, min(npix, 200), 200, freq_ghz, 1)
    print(flush=True)

    # 串行基准
    print("【串行 baseline】")
    serial_time, serial_result = bench_once(
        "serial", run_serial, data, nt, npix, chunk_size, freq_ghz
    )
    print()

    # ThreadPoolExecutor 对照（Sprint 3.6 已证明负加速）
    thread_results: dict[int, float] = {}
    for workers in (2, 4, 8):
        print(f"【ThreadPoolExecutor max_workers={workers}】（Sprint 3.6 对照）")
        t, r = bench_once(
            f"threaded x{workers}",
            run_threaded,
            data,
            nt,
            npix,
            chunk_size,
            freq_ghz,
            workers,
        )
        thread_results[workers] = t
        max_diff = np.nanmax(np.abs(r - serial_result))
        print(f"  数值一致性: max|diff| = {max_diff:.2e} (应 < 1e-10)")
        print()

    # ProcessPoolExecutor 新增对比（Sprint 3.7）
    proc_results: dict[int, float] = {}
    for workers in (2, 4, 8):
        print(f"【ProcessPoolExecutor max_workers={workers}】（Sprint 3.7 新增）")
        t, r = bench_once(
            f"process x{workers}",
            run_process_pool,
            data,
            nt,
            npix,
            chunk_size,
            freq_ghz,
            workers,
        )
        proc_results[workers] = t
        max_diff = np.nanmax(np.abs(r - serial_result))
        print(f"  数值一致性: max|diff| = {max_diff:.2e} (应 < 1e-10)")
        print()

    # 端到端通过 execute_block_inversion（验证生产路径开销）
    e2e_results: dict[str, float] = {}
    print("【execute_block_inversion 端到端】")
    t, _ = bench_once(
        "execute_block_inversion(max_workers=1)",
        run_via_execute_block_inversion,
        data,
        nt,
        npix,
        chunk_size,
        freq_ghz,
        1,
    )
    e2e_results["serial"] = t
    for w in (2, 4, 8):
        t, _ = bench_once(
            f"execute_block_inversion(max_workers={w})",
            run_via_execute_block_inversion,
            data,
            nt,
            npix,
            chunk_size,
            freq_ghz,
            w,
        )
        e2e_results[f"parallel_{w}"] = t
    # 自动模式
    t, _ = bench_once(
        "execute_block_inversion(max_workers=None 自动)",
        run_via_execute_block_inversion,
        data,
        nt,
        npix,
        chunk_size,
        freq_ghz,
        None,
    )
    e2e_results["auto"] = t
    print()

    # 汇总
    print("=== 汇总 ===")
    print(f"  串行 baseline:               {serial_time:.3f}s")
    print()
    print("  ThreadPoolExecutor（Sprint 3.6，已知负加速）:")
    for w, t in thread_results.items():
        speedup = serial_time / t if t > 0 else 0
        print(f"    {w} 线程: {t:.3f}s  (speedup: {speedup:.2f}x)")
    print()
    print("  ProcessPoolExecutor（Sprint 3.7 新增）:")
    for w, t in proc_results.items():
        speedup = serial_time / t if t > 0 else 0
        print(f"    {w} 进程: {t:.3f}s  (speedup: {speedup:.2f}x)")
    print()
    print("  execute_block_inversion 端到端:")
    for label, t in e2e_results.items():
        speedup = serial_time / t if t > 0 else 0
        print(f"    {label}: {t:.3f}s  (speedup: {speedup:.2f}x)")
    print()

    # 结论
    print("结论:")
    best_w = min(proc_results, key=proc_results.get)
    best_speedup = serial_time / proc_results[best_w]
    if best_speedup > 1.5:
        print(
            f"  ✅ ProcessPoolExecutor 收益显著 (最佳 {best_w} 进程, {best_speedup:.2f}x 加速)"
        )
        print("  建议: execute_block_inversion 默认启用 max_workers=None 自动分配")
        print("  约束: spawn 上下文 + 串行回退保证已在 Sprint 3.7 实现")
    elif best_speedup > 1.1:
        print(
            f"  ⚠️ ProcessPoolExecutor 收益有限 (最佳 {best_w} 进程, {best_speedup:.2f}x 加速)"
        )
        print("  建议: 可选优化，需权衡 spawn/pickle 开销与计算量")
    else:
        print(
            f"  ❌ ProcessPoolExecutor 无收益 (最佳 {best_w} 进程, {best_speedup:.2f}x 加速)"
        )
        print("  建议: spawn/pickle 开销大于 GIL 绕过收益，保持串行")


if __name__ == "__main__":
    main()
