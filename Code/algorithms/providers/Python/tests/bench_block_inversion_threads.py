"""Sprint 3.6 (D2): block_inversion ThreadPoolExecutor 基准测试。

评估将 execute_block_inversion 的 chunk 循环并行化（ThreadPoolExecutor）的收益。
背景：
- Celery worker 使用 prefork 模式（celery_app.py L35），ProcessPoolExecutor 有死锁风险。
- retrieve_dynamic_h_pixel 调用 scipy.optimize.least_squares（C/MINPACK），会释放 GIL。
- 因此 ThreadPoolExecutor 理论上可获得加速（线程在 least_squares 期间可并行）。

本脚本：
1. 构造合成输入数据（nt 天 × npix 像素）
2. 串行执行 chunk 循环（模拟当前 execute_block_inversion 行为）
3. 用 ThreadPoolExecutor 并行执行 chunk 循环
4. 对比耗时与数值一致性

运行：
    cd Code/algorithms/providers/Python
    python -m tests.bench_block_inversion_threads
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

# 确保 algorithms 包在路径中
algo_root = Path(__file__).resolve().parent.parent
if str(algo_root) not in sys.path:
    sys.path.insert(0, str(algo_root))

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
        "tbv": tbv, "tbh": tbh, "ts": ts, "tau": tau,
        "clay": clay, "albedo": albedo, "porosity": porosity,
        "theta": theta,
    }


def run_serial(data: dict, nt: int, npix: int, chunk_size: int, freq_ghz: float) -> np.ndarray:
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
    data: dict, nt: int, npix: int, chunk_size: int, freq_ghz: float,
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

    print(f"=== Sprint 3.6 block_inversion ThreadPoolExecutor 基准测试 ===")
    print(f"数据规模: nt={nt} 天, npix={npix} 像素, chunk_size={chunk_size}")
    print(f"chunk 数: {npix // chunk_size + (1 if npix % chunk_size else 0)}")
    print(f"freq_ghz={freq_ghz}, mode=dh (retrieve_dynamic_h_grid)")
    print()

    data = make_synthetic_data(nt, npix)

    # 预热（首次 import scipy 有开销）
    print("预热...", flush=True)
    _ = run_serial(data, nt, min(npix, 200), 200, freq_ghz)
    print(flush=True)

    # 串行基准
    print("【串行】")
    serial_time, serial_result = bench_once("serial", run_serial, data, nt, npix, chunk_size, freq_ghz)
    print()

    # 不同线程数对比
    results: dict[int, float] = {}
    for workers in (2, 4, 8):
        print(f"【ThreadPoolExecutor max_workers={workers}】")
        t, r = bench_once(f"threaded x{workers}", run_threaded, data, nt, npix, chunk_size, freq_ghz, workers)
        results[workers] = t
        # 数值一致性检查
        max_diff = np.nanmax(np.abs(r - serial_result))
        print(f"  数值一致性: max|diff| = {max_diff:.2e} (应 < 1e-10)")
        print()

    # 汇总
    print("=== 汇总 ===")
    print(f"  串行:          {serial_time:.3f}s (baseline)")
    for w, t in results.items():
        speedup = serial_time / t if t > 0 else 0
        print(f"  {w} 线程:       {t:.3f}s  (speedup: {speedup:.2f}x)")
    print()
    print("结论:")
    best_w = min(results, key=results.get)
    best_speedup = serial_time / results[best_w]
    if best_speedup > 1.5:
        print(f"  ✅ ThreadPoolExecutor 收益显著 (最佳 {best_w} 线程, {best_speedup:.2f}x 加速)")
        print(f"  建议: 在 execute_block_inversion 中引入 ThreadPoolExecutor 并行 chunk 循环")
        print(f"  约束: max_workers 应可配置（默认 min(4, os.cpu_count())），Celery prefork 下安全")
    elif best_speedup > 1.1:
        print(f"  ⚠️ ThreadPoolExecutor 收益有限 (最佳 {best_w} 线程, {best_speedup:.2f}x 加速)")
        print(f"  建议: 可选优化，需权衡复杂度与收益")
    else:
        print(f"  ❌ ThreadPoolExecutor 无收益 (最佳 {best_w} 线程, {best_speedup:.2f}x 加速)")
        print(f"  建议: 不引入并行化，保持串行实现")


if __name__ == "__main__":
    main()
