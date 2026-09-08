# 多进程并行化方案 — block_inversion 反演主循环

> **背景**: Sprint 3.6 基准测试（`bench_block_inversion_threads.py`）证实 `ThreadPoolExecutor` 比
> 串行慢 0.52x–0.79x。根因是 `retrieve_dynamic_h_grid` 内的 Python for 循环
> (`inversion.py:381-394`) 在 `scipy.optimize.least_squares` 调用之间持有 GIL，
> 线程越多 GIL 争用越严重。
>
> **本方案**: 改用 `ProcessPoolExecutor` + `spawn` 上下文，绕过 GIL；进程数根据
> CPU 物理核数 + 可用内存自动分配；保证任意并行基础设施失败回退到串行。

---

## 1. 现状分析

### 1.1 目标代码
**文件**: `Code/algorithms/providers/Python/algorithms/block_inversion.py:164-308`
**函数**: `execute_block_inversion(payload, *, mode, freq_ghz, pixel_chunk_size=2000, ...)`

关键循环（L263-307）按像素分块（默认 `chunk_size=2000`），每块：
1. `tau_from_ndvi(...)` 计算 tau 初值（向量化，本身很快）
2. 对每一天 (`for day_index in range(nt)`) 调用 `retrieve_dynamic_h_grid` 或
   `ddca_retrieve_grid`，内部对每个像素调用 `least_squares`

**性能瓶颈**: `least_squares` 是 C 实现（释放 GIL），但调用之间是 Python
for 循环（持有 GIL）→ 多线程无用。多进程可彻底绕过。

### 1.2 系统资源（实测 2026-07-18）
| 项目 | 值 |
|---|---|
| 物理核数 | 24 (`psutil.cpu_count(logical=False)`) |
| 逻辑核数 | 32 |
| 总内存 | 32461 MB |
| 当前可用内存 | 9864 MB |
| psutil 版本 | 7.2.2（已安装，但**未列入 requirements.txt**） |

### 1.3 Celery 部署约束
- `launch.py:98-106`: 7 个 Celery Worker，无 `--pool` / `--concurrency` 参数
- `celery_app.py:35`: `worker_pool="prefork"`（Linux/mac 默认 prefork；Windows 上 `worker.ps1` 用 `--pool=solo --concurrency=1`）
- 算法在 Celery task 中通过 `dispatch.py` 调用 `execute_block_inversion`
- **关键约束**: prefork worker 已是 fork 出的子进程；在 task 内再 `fork` 会引发
  fork-after-thread 死锁。必须使用 **spawn** 上下文启动进程池。

---

## 2. 设计总览

```
┌─────────────────────────────────────────────────────────────┐
│  execute_block_inversion(max_workers=None)                  │
│                                                             │
│  1. 读取 payload / 规范化矩阵（不变）                       │
│  2. chunk_size = adjust_chunk_size_for_parallelism(         │
│         pixel_chunk_size, npix, process_count)              │
│  3. chunks = [(start, end) for ...]                         │
│  4. if process_count <= 1 or len(chunks) < 2:               │
│         chunk_results = _run_chunks_serial(...)             │
│     else:                                                   │
│         try:                                                │
│             chunk_results = _run_chunks_parallel(...)       │
│         except Exception:                                   │
│             log warning + 回退 _run_chunks_serial           │
│  5. 合并 chunk 结果到 result 矩阵，返回                      │
└─────────────────────────────────────────────────────────────┘
```

**核心原则**:
1. **进程数自动分配** — 根据 CPU 物理核数 + 可用内存 + chunk 数取最小值
2. **chunk 数自适应** — 若 chunk 数 < `process_count * 2`，自动缩小 chunk_size
3. **串行回退** — 任何并行失败（导入、pickle、spawn 异常）都回退到串行，绝不失败主任务
4. **spawn 上下文** — 绕过 Celery prefork 的 fork-after-thread 风险
5. **模块级 worker 函数** — 满足 pickle 要求（不使用闭包/lambda）

---

## 3. 新文件 `algorithms/_parallel.py`

```python
"""多进程并行化辅助工具。

专为 Celery prefork worker 内调用设计：使用 spawn 上下文避免 fork-after-thread 死锁。
所有函数都有合理的降级行为，确保主任务不会因并行基础设施失败而失败。
"""
from __future__ import annotations

import logging
import os
from math import floor
from typing import Any

logger = logging.getLogger(__name__)

# 内存预算：每个 worker 估算占用（MB）。粗略估计包含 numpy 数组、
# scipy least_squares 工作内存、Python 解释器开销。
_MEM_PER_WORKER_MB = 200

# 系统保留内存（MB）：留给主进程、Celery worker、Redis、FastAPI 等
_SYSTEM_RESERVE_MB = 2048

# 最小 chunk 数倍数：确保进程数 * 2 个 chunk 才有意义并行
_MIN_CHUNKS_PER_WORKER = 2


def _get_psutil_safely() -> Any:
    """安全导入 psutil；失败返回 None。"""
    try:
        import psutil  # type: ignore
        return psutil
    except ImportError:
        logger.debug("psutil not available; falling back to os.cpu_count()")
        return None


def auto_process_count(
    *,
    chunk_count: int,
    max_workers: int | None = None,
    cpu_reserve: int = 2,
) -> int:
    """根据 CPU 物理核数和可用内存自动计算进程数。

    Args:
        chunk_count: 当前 chunk 总数（进程数不会超过 chunk_count）
        max_workers: 用户指定的上限；None 表示自动计算
        cpu_reserve: 保留给系统的物理核数（默认 2，确保主进程/Celery/Redis 有 CPU）

    Returns:
        推荐进程数，最小为 1（1 表示走串行路径）

    算法:
        cpu_based    = max(1, physical_cores - cpu_reserve)
        mem_based    = max(1, floor((avail_mb - reserve) / per_worker))
        env_cap      = $CGDA_MAX_PARALLEL_WORKERS (若设置)
        final        = max(1, min(cpu_based, mem_based, env_cap, chunk_count, max_workers))
    """
    if max_workers is not None and max_workers <= 1:
        return 1

    psutil = _get_psutil_safely()

    # CPU 维度
    if psutil is not None:
        physical = psutil.cpu_count(logical=False) or os.cpu_count() or 1
    else:
        physical = os.cpu_count() or 1
    cpu_based = max(1, physical - cpu_reserve)

    # 内存维度
    if psutil is not None:
        try:
            avail_mb = psutil.virtual_memory().available // (1024 * 1024)
            mem_based = max(1, floor((avail_mb - _SYSTEM_RESERVE_MB) / _MEM_PER_WORKER_MB))
        except Exception:
            logger.debug("psutil.virtual_memory() failed; skipping memory cap")
            mem_based = cpu_based
    else:
        mem_based = cpu_based

    # 环境变量硬上限（运维逃生通道）
    env_cap_str = os.environ.get("CGDA_MAX_PARALLEL_WORKERS")
    env_cap = int(env_cap_str) if env_cap_str and env_cap_str.isdigit() else cpu_based

    # chunk 数约束：进程数不应超过 chunk 数（否则有 worker 闲置）
    chunk_cap = max(1, chunk_count)

    final = max(1, min(cpu_based, mem_based, env_cap, chunk_cap))
    if max_workers is not None:
        final = max(1, min(final, max_workers))

    logger.debug(
        "auto_process_count: physical=%d cpu_based=%d mem_based=%d env_cap=%d "
        "chunk_cap=%d max_workers=%s → final=%d",
        physical, cpu_based, mem_based, env_cap, chunk_cap, max_workers, final,
    )
    return final


def get_spawn_context() -> Any:
    """获取 spawn 多进程上下文。

    使用 spawn 而非 fork 的原因：
    1. Celery prefork worker 已经是 fork 出的子进程，task 内再 fork 可能
       触发 fork-after-thread 死锁（线程持锁状态被复制到子进程）。
    2. spawn 启动全新 Python 解释器，干净状态，跨平台一致。
    3. Windows 仅支持 spawn，保持行为一致。

    Returns:
        multiprocessing.BaseContext
    """
    import multiprocessing
    return multiprocessing.get_context("spawn")


def adjust_chunk_size_for_parallelism(
    pixel_chunk_size: int,
    npix: int,
    process_count: int,
) -> int:
    """调整 chunk_size 以产生足够的 chunk 支持并行。

    若当前 chunk 数 < process_count * _MIN_CHUNKS_PER_WORKER，
    自动缩小 chunk_size 直到满足或达到下限。

    Args:
        pixel_chunk_size: 用户/默认的 chunk_size（像素数）
        npix: 总像素数
        process_count: 进程数

    Returns:
        调整后的 chunk_size，最小为 1
    """
    if process_count <= 1 or npix <= 0:
        return max(1, int(pixel_chunk_size))

    target_chunks = process_count * _MIN_CHUNKS_PER_WORKER
    current_chunks = max(1, (npix + pixel_chunk_size - 1) // pixel_chunk_size)

    if current_chunks >= target_chunks:
        return max(1, int(pixel_chunk_size))

    # 反推：chunk_size = ceil(npix / target_chunks)
    new_chunk_size = max(1, (npix + target_chunks - 1) // target_chunks)
    new_chunk_size = min(new_chunk_size, pixel_chunk_size)
    return new_chunk_size
```

### 3.1 关键参数说明

| 参数 | 值 | 理由 |
|---|---|---|
| `_MEM_PER_WORKER_MB` | 200 | 每进程 numpy 数组 + scipy 工作内存 + 解释器 |
| `_SYSTEM_RESERVE_MB` | 2048 | 主进程/Celery worker/Redis/FastAPI 等系统占用 |
| `cpu_reserve` | 2 | 主进程和 Celery worker 各保留 1 核 |
| `_MIN_CHUNKS_PER_WORKER` | 2 | 避免长尾效应：最后一个 chunk 拖慢整体 |

### 3.2 当前系统的实际计算

- `physical = 24` → `cpu_based = 24 - 2 = 22`
- `avail_mb = 9864` → `mem_based = floor((9864 - 2048) / 200) = floor(39.08) = 39`
- `env_cap = 22`（未设置环境变量）
- `final = min(22, 39, 22, chunk_count)`

若 `npix=10000, pixel_chunk_size=2000` → `chunk_count=5` → `final=5`，
`adjust_chunk_size_for_parallelism(2000, 10000, 5)` → `target_chunks=10` →
`new_chunk_size = ceil(10000/10) = 1000`（缩小一倍以产生 10 个 chunk）。

---

## 4. 重构 `block_inversion.py`

### 4.1 新增模块级 worker 函数

```python
def _process_chunk(
    start: int,
    end: int,
    *,
    mode: str,
    nt: int,
    ndvi_mat_chunk: Any,        # (nt, chunk_npix)
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
    h_mat_chunk: Any,           # ddca 模式专用，dh 模式可为 None
    freq_ghz: float,
) -> dict[str, Any]:
    """处理单个像素分块（模块级函数，可被 pickle 到子进程）。

    返回 dict:
        {"start": start, "end": end,
         "tau_ini": (nt, chunk_npix),
         "dh"/"sm"/"vod": (nt, chunk_npix)}
    """
    import numpy as np
    from algorithms.inversion import ddca_retrieve_grid, retrieve_dynamic_h_grid
    from algorithms.physics import tau_from_ndvi

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
```

### 4.2 串行/并行分发函数

```python
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
    results = []
    for start, end in chunks:
        cols = slice(start, end)
        sub_kwargs = _prepare_chunk_kwargs(matrices, cols, mode)
        results.append(_process_chunk(
            start, end, mode=mode, nt=nt, freq_ghz=freq_ghz, **sub_kwargs,
        ))
    return results


def _run_chunks_parallel(
    chunks: list[tuple[int, int]],
    *,
    mode: str,
    nt: int,
    matrices: dict[str, Any],
    freq_ghz: float,
    process_count: int,
) -> list[dict[str, Any]]:
    """使用 ProcessPoolExecutor 并行执行所有 chunk。

    任何异常向上抛出，由调用方 catch 后回退到串行。
    """
    from concurrent.futures import ProcessPoolExecutor
    from algorithms._parallel import get_spawn_context

    ctx = get_spawn_context()

    # 按提交顺序构造 future 列表，保证结果顺序与 chunks 一致
    submissions = [
        (start, end, _prepare_chunk_kwargs(matrices, slice(start, end), mode))
        for start, end in chunks
    ]

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=process_count, mp_context=ctx) as ex:
        futures = [
            ex.submit(
                _process_chunk, start, end,
                mode=mode, nt=nt, freq_ghz=freq_ghz, **sub_kwargs,
            )
            for start, end, sub_kwargs in submissions
        ]
        for fut in futures:
            results.append(fut.result())  # 顺序与提交一致
    return results
```

### 4.3 修改 `execute_block_inversion` 主入口

在原签名基础上新增 `max_workers` 参数；用 `matrices` dict 装载所有主矩阵，
简化分发逻辑：

```python
def execute_block_inversion(
    payload: dict[str, Any],
    *,
    mode: str,
    freq_ghz: float,
    pixel_chunk_size: int = 2000,
    dh_mat_path: str | Path | None = None,
    field_config: BlockFieldConfig | None = None,
    max_workers: int | None = None,   # ← 新增；None=自动
) -> dict[str, Any]:
    # ...（前面 payload 规范化、矩阵广播、results 初始化逻辑不变）...

    # ─── 并行化决策 ─────────────────────────────────────────
    from algorithms._parallel import (
        auto_process_count,
        adjust_chunk_size_for_parallelism,
    )

    matrices = {
        "ndvi_mat": ndvi_mat, "ndvi_v_max": ndvi_v_max, "ndvi_v_min": ndvi_v_min,
        "landcover": landcover, "b_param": b_param, "sf_mat": sf_mat,
        "ia_mat": ia_mat, "tbv_mat": tbv_mat, "tbh_mat": tbh_mat, "ts_mat": ts_mat,
        "clay_fraction": clay_fraction, "albedo": albedo, "porosity": porosity,
        "h_mat": results.get("H_used_mat"),
    }

    # 估算 chunk 数并决定进程数
    initial_chunk_size = max(1, int(pixel_chunk_size))
    initial_chunk_count = (npix + initial_chunk_size - 1) // initial_chunk_size
    process_count = auto_process_count(
        chunk_count=initial_chunk_count, max_workers=max_workers,
    )

    # 调整 chunk_size 产生足够 chunk 支持并行
    chunk_size = adjust_chunk_size_for_parallelism(
        initial_chunk_size, npix, process_count,
    )
    chunks = [(s, min(s + chunk_size, npix)) for s in range(0, npix, chunk_size)]

    use_parallel = process_count > 1 and len(chunks) >= 2

    if use_parallel:
        try:
            chunk_results = _run_chunks_parallel(
                chunks, mode=mode, nt=nt, matrices=matrices,
                freq_ghz=freq_ghz, process_count=process_count,
            )
        except Exception as exc:
            # 关键降级：编程 bug 不掩盖，其余回退串行
            if isinstance(exc, (AttributeError, NameError, TypeError,
                                 ImportError, SyntaxError)):
                raise
            import logging
            logging.getLogger(__name__).warning(
                "Parallel chunk execution failed (%s: %s); falling back to serial",
                type(exc).__name__, exc,
            )
            chunk_results = _run_chunks_serial(
                chunks, mode=mode, nt=nt, matrices=matrices, freq_ghz=freq_ghz,
            )
    else:
        chunk_results = _run_chunks_serial(
            chunks, mode=mode, nt=nt, matrices=matrices, freq_ghz=freq_ghz,
        )

    # ─── 合并 chunk 结果到 result 矩阵 ─────────────────────
    for cr in chunk_results:
        start, end = cr["start"], cr["end"]
        cols = slice(start, end)
        tau_ini_mat[:, cols] = cr["tau_ini"]
        if mode == "dh":
            results["DH_mat"][:, cols] = cr["dh"]
        else:
            results["SM_mat"][:, cols] = cr["sm"]
            results["VOD_mat"][:, cols] = cr["vod"]

    return results
```

### 4.4 向后兼容性

- `max_workers=None` 默认值：旧调用者无需修改
- 旧 `pixel_chunk_size` 参数保留语义，但可能被 `adjust_chunk_size_for_parallelism` 缩小
- 调用方 `modules/block_inversion.py` 和 `pipelines/block_inversion_products.py`
  无需修改（除非想显式传入 `max_workers`）
- 可通过 `algorithm_params` 中新增 `max_workers` 字段透传（可选增强，本次不做）

---

## 5. 依赖更新

### 5.1 `Code/algorithms/providers/Python/requirements.txt`

```diff
 numpy
 scipy
+psutil>=5.9.0
```

> `psutil>=5.9.0` 是经过验证的最低版本（当前系统 7.2.2），支持
> `cpu_count(logical=False)` 和 `virtual_memory()`。

### 5.2 后端依赖

无需修改 `Code/backend/requirements.txt`：算法在子进程内通过算法包
`requirements.txt` 安装 psutil；后端主进程不直接依赖。

---

## 6. 调用方影响评估

| 调用方 | 文件:行 | 影响 | 需要修改？ |
|---|---|---|---|
| 算法 module | `modules/block_inversion.py:96-103` | 仅透传 `pixel_chunk_size` | 否 |
| Pipeline | `pipelines/block_inversion_products.py:60-67` | 仅透传 `pixel_chunk_size` | 否 |
| 基准测试 | `tests/bench_block_inversion_threads.py` | 需新增 ProcessPoolExecutor 对比 | **是** |

---

## 7. 基准测试脚本更新

更新 `bench_block_inversion_threads.py` 增加 ProcessPoolExecutor 对比：

```python
def run_process_pool(npix, nt, chunk_size, max_workers):
    """ProcessPoolExecutor 版本，复用 _process_chunk。"""
    from algorithms.block_inversion import _process_chunk
    from algorithms._parallel import get_spawn_context
    from concurrent.futures import ProcessPoolExecutor

    data = make_synthetic_data(npix, nt)
    matrices = build_matrices_dict(data)  # 与 serial/threaded 共享构造
    chunks = [(s, min(s + chunk_size, npix)) for s in range(0, npix, chunk_size)]

    ctx = get_spawn_context()
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as ex:
        futures = [
            ex.submit(_process_chunk, s, e, mode="dh", nt=nt,
                      freq_ghz=10.7, **prepare_chunk_kwargs(matrices, slice(s, e), "dh"))
            for s, e in chunks
        ]
        results = [f.result() for f in futures]
    return results

def main():
    # 串行 baseline
    t_serial = timeit(...)
    # ThreadPoolExecutor（已知失败，保留对照）
    t_thread_4 = timeit(...)
    # ProcessPoolExecutor 新增
    t_proc_2  = timeit(lambda: run_process_pool(npix, nt, chunk_size, 2))
    t_proc_4  = timeit(lambda: run_process_pool(npix, nt, chunk_size, 4))
    t_proc_8  = timeit(lambda: run_process_pool(npix, nt, chunk_size, 8))
    t_proc_16 = timeit(lambda: run_process_pool(npix, nt, chunk_size, 16))
    ...
```

**预期结果**（参考）:
- 串行 13.72s（baseline）
- ProcessPool 2 进程 ≈ 7-8s（理论 0.5x，含 spawn + pickle 开销）
- ProcessPool 4 进程 ≈ 4-5s
- ProcessPool 8 进程 ≈ 3-4s（接近最优）
- ProcessPool 16 进程 ≈ 3-4s（边际收益递减，受内存带宽限制）

---

## 8. 错误处理策略

| 异常类型 | 处理 |
|---|---|
| `AttributeError` / `NameError` / `TypeError` / `ImportError` / `SyntaxError` | **编程 bug，向上抛出**（不掩盖） |
| `pickle.PicklingError` / `BrokenProcessPool` | 回退串行 + warning log |
| `MemoryError` | 回退串行 + warning log |
| `OSError`（spawn 失败） | 回退串行 + warning log |
| 其他 `Exception` | 回退串行 + warning log |

**关键原则**: 与项目 memory 中 Sprint 3.5 已确立的「specific exception → propagate bug,
broad runtime → degrade」策略一致。

---

## 9. mode 参数处理

`mode == "dh"` 和 `mode == "ddca"` 的差异已经在 `_process_chunk` 中通过分支处理。
两模式都返回 `tau_ini`，`dh` 模式额外返回 `dh`，`ddca` 模式额外返回 `sm`+`vod`。
主入口在合并时按 mode 取对应字段。

`mode` 字符串不可 pickle 的问题：不存在，Python str 是 pickle 原生支持的。

---

## 10. 测试策略

### 10.1 `tests/test_parallel_utils.py`（新增）

```python
class TestAutoProcessCount:
    def test_returns_1_when_max_workers_le_1(self):
        assert auto_process_count(chunk_count=10, max_workers=0) == 1
        assert auto_process_count(chunk_count=10, max_workers=1) == 1

    def test_capped_by_chunk_count(self):
        # 即使有 24 核，只有 3 个 chunk 就只开 3 进程
        assert auto_process_count(chunk_count=3, max_workers=None) <= 3

    def test_capped_by_max_workers(self):
        assert auto_process_count(chunk_count=100, max_workers=4) <= 4

    def test_env_cap_respected(self, monkeypatch):
        monkeypatch.setenv("CGDA_MAX_PARALLEL_WORKERS", "2")
        assert auto_process_count(chunk_count=100, max_workers=None) <= 2

    def test_minimum_1(self):
        assert auto_process_count(chunk_count=0, max_workers=None) == 1


class TestAdjustChunkSize:
    def test_no_shrink_when_enough_chunks(self):
        # npix=10000, chunk=2000 → 5 chunks, process=2 → target=4 ≤ 5
        assert adjust_chunk_size_for_parallelism(2000, 10000, 2) == 2000

    def test_shrink_when_too_few_chunks(self):
        # npix=10000, chunk=2000 → 5 chunks, process=4 → target=8 > 5
        # new = ceil(10000/8) = 1250
        assert adjust_chunk_size_for_parallelism(2000, 10000, 4) == 1250

    def test_no_shrink_when_serial(self):
        assert adjust_chunk_size_for_parallelism(2000, 10000, 1) == 2000


class TestSpawnContext:
    def test_returns_spawn_context(self):
        import multiprocessing
        ctx = get_spawn_context()
        assert ctx.get_start_method() == "spawn"
```

### 10.2 `tests/test_block_inversion_parallel.py`（新增）

```python
class TestSerialParallelEquivalence:
    """验证串行和并行输出完全一致。"""

    def _make_synthetic_payload(self, nt=3, npix=50):
        # 构造合成 .mat 风格 payload
        ...

    def test_dh_mode_equivalence(self):
        payload = self._make_synthetic_payload()
        serial = execute_block_inversion(payload, mode="dh", freq_ghz=10.7,
                                          max_workers=1)
        parallel = execute_block_inversion(payload, mode="dh", freq_ghz=10.7,
                                            max_workers=2)
        np.testing.assert_array_almost_equal(
            serial["DH_mat"], parallel["DH_mat"], decimal=10,
        )
        np.testing.assert_array_almost_equal(
            serial["Tau_ini_mat"], parallel["Tau_ini_mat"], decimal=10,
        )

    def test_ddca_mode_equivalence(self):
        ...  # 同上，验证 SM_mat 和 VOD_mat

    def test_fallback_on_failure(self, monkeypatch):
        # 故意破坏 ProcessPoolExecutor → 验证回退串行
        def broken_executor(*args, **kwargs):
            raise OSError("simulated spawn failure")
        monkeypatch.setattr("algorithms.block_inversion.ProcessPoolExecutor", broken_executor)
        payload = self._make_synthetic_payload()
        result = execute_block_inversion(payload, mode="dh", freq_ghz=10.7,
                                          max_workers=4)
        # 应该成功完成（走了串行回退）
        assert not np.all(np.isnan(result["DH_mat"]))

    def test_auto_workers_default(self):
        # max_workers=None 应该自动选择并成功
        payload = self._make_synthetic_payload(nt=3, npix=200)
        result = execute_block_inversion(payload, mode="dh", freq_ghz=10.7)
        assert result["DH_mat"].shape == (3, 200)
```

### 10.3 回归测试

跑现有算法测试套件确保不破坏：
```bash
cd Code/algorithms/providers/Python
python -m pytest tests/ -x -q
```

---

## 11. 实施顺序

1. **新建 `algorithms/_parallel.py`**（核心工具，独立可测）
2. **新增 `tests/test_parallel_utils.py`** 并跑通
3. **重构 `block_inversion.py`**：新增 `_process_chunk`、`_prepare_chunk_kwargs`、
   `_run_chunks_serial`、`_run_chunks_parallel`，修改 `execute_block_inversion`
4. **新增 `tests/test_block_inversion_parallel.py`** 并跑通等价测试
5. **更新 `requirements.txt`** 添加 `psutil>=5.9.0`
6. **更新基准测试脚本** 增加 ProcessPoolExecutor 对比
7. **手动运行基准测试** 确认实际加速比
8. **提交 commit**（commit message 遵循项目规范）

---

## 12. 风险与缓解

### 12.1 Pickle 兼容性
- **风险**: `BlockFieldConfig` 是 frozen dataclass，但 `_process_chunk` 不接收它，只接收
  已经切片好的 numpy 数组和标量 → 所有参数都是 pickle 原生支持的类型。
- **缓解**: worker 函数（`_process_chunk`）是模块级函数，不使用闭包/lambda。

### 12.2 内存爆炸
- **风险**: 每个进程都拷贝输入数组。若 npix=100k，单 chunk 2000 像素 × nt=100 天 ×
  10 个数组 × 8 字节 = 1.6 GB/chunk。24 进程并行 = 38 GB（超出！）
- **缓解**:
  - `auto_process_count` 已经按 `(avail_mb - 2048) / 200` 限制进程数
  - chunk 数随进程数自动增加（`adjust_chunk_size_for_parallelism`），但**单 chunk 大小
    不会增加**，因此单进程峰值内存可控
  - 必要时用户可通过 `CGDA_MAX_PARALLEL_WORKERS` 环境变量硬限

### 12.3 Celery prefork + spawn 嵌套
- **风险**: 理论上 spawn 子进程内若再 import celery 可能死锁
- **缓解**: `_process_chunk` 只 import numpy/scipy/algorithms 子模块，不触碰 celery；
  spawn 启动全新解释器，状态干净。

### 12.4 Windows 兼容性
- **风险**: Windows 只支持 spawn，主模块必须有 `if __name__ == "__main__":` 守护
- **缓解**: `_process_chunk` 是模块级函数，不是主模块入口；spawn 会重新 import
  `block_inversion` 模块，不会触发 `__main__`。验证：测试套件在 Windows 上跑通。

### 12.5 子进程日志丢失
- **风险**: 子进程的 logger 输出可能不写文件
- **缓解**: `_process_chunk` 不主动 log；异常通过 `fut.result()` 抛回主进程由主进程 log。

### 12.6 回退路径的正确性
- **风险**: 并行失败后回退串行，但 chunks 已经调整过（更小），可能比原始 chunk_size 慢
- **缓解**: 串行路径用同样的 chunks 即可，慢一点但保证正确；回退是异常路径，
  可接受轻微性能损失。

---

## 13. 后续可选优化（不在本次范围）

1. **共享内存**: 用 `multiprocessing.shared_memory` 避免数组拷贝（numpy ≥ 1.20）
2. **Worker 预热**: 启动时预 import scipy 以减少首任务延迟
3. **进度回调**: 用 `concurrent.futures.as_completed` 实现进度上报到 WorkflowResultReference
4. **chunk 级别超时**: 单 chunk 超过 N 分钟自动 cancel 重试

---

## 14. 验收标准

- [ ] `tests/test_parallel_utils.py` 全部通过
- [ ] `tests/test_block_inversion_parallel.py` 全部通过（等价性 + 回退）
- [ ] 现有算法测试套件无回归
- [ ] 基准测试显示 ProcessPoolExecutor 比 serial 至少快 2x（4 进程）
- [ ] `requirements.txt` 包含 `psutil>=5.9.0`
- [ ] commit 在 dev 分支，遵循 conventional commit 规范
- [ ] 任何并行异常都回退到串行，不抛出给上层 Celery task
