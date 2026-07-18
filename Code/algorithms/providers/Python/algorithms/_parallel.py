"""多进程并行化辅助工具。

专为 Celery prefork worker 内调用设计：使用 spawn 上下文避免 fork-after-thread 死锁。
所有函数都有合理的降级行为，确保主任务不会因并行基础设施失败而失败。

跨平台兼容性：
- Windows: spawn 是唯一可用的多进程启动方式，行为一致。
- Linux: 默认 fork，但本模块显式用 spawn 以兼容 Celery prefork worker
  （Celery worker 已是 fork 出的子进程，task 内再 fork 可能触发
  fork-after-thread 死锁）。spawn 启动较慢（需重新 import 模块），
  但功能正确且跨平台一致。
- macOS: 与 Linux 类似，默认 fork 但本模块用 spawn。

Celery 部署注意事项（进程爆炸防护）：
    Celery worker 默认 ``worker_concurrency = os.cpu_count()``（逻辑核数），
    ``worker_prefetch_multiplier = 4``。若每个 task 内 ``auto_process_count``
    返回较大值（如 22），32 个并发 task × 22 子进程 = 704 子进程，导致
    CPU 严重过订阅。

    推荐部署配置（任选其一）：
    1. 设置环境变量 ``CGDA_MAX_PARALLEL_WORKERS=2`` 或 ``3``，限制每个 task
       的子进程数（推荐：物理核数 / worker_concurrency）。
    2. 降低 Celery ``worker_concurrency`` 到物理核数的一半。
    3. 降低 ``worker_prefetch_multiplier=1`` 避免预取过多 task。

    示例 .env 配置：
        CGDA_MAX_PARALLEL_WORKERS=3
        CGDA_PARALLEL_TIMEOUT_PER_CHUNK=120
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
        env_cap      = $CGDA_MAX_PARALLEL_WORKERS (若设置，未设置时为 inf 不限制)
        final        = max(1, int(min(cpu_based, mem_based, env_cap, chunk_count)))
        若 max_workers 非 None，final 进一步 min(final, max_workers)

    Celery 部署警告:
        在 Celery prefork worker 内调用时，``worker_concurrency`` 个子进程可能
        同时执行本函数。若不设置 ``CGDA_MAX_PARALLEL_WORKERS``，每个 task 可能
        创建 ``physical_cores - 2`` 个子进程，导致 CPU 严重过订阅
        （32 task × 22 子进程 = 704 子进程）。

        推荐在 Celery worker 的 .env 中设置::
            CGDA_MAX_PARALLEL_WORKERS = max(1, physical_cores // worker_concurrency)

        例如 24 物理核 / 8 worker_concurrency → CGDA_MAX_PARALLEL_WORKERS=3。
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

    # 环境变量硬上限（运维逃生通道）；未设置时为 inf 表示不限制
    env_cap_str = os.environ.get("CGDA_MAX_PARALLEL_WORKERS")
    env_cap: float | int = (
        int(env_cap_str) if env_cap_str and env_cap_str.isdigit() else float("inf")
    )

    # chunk 数约束：进程数不应超过 chunk 数（否则有 worker 闲置）
    chunk_cap = max(1, chunk_count)

    final = max(1, int(min(cpu_based, mem_based, env_cap, chunk_cap)))
    if max_workers is not None:
        final = max(1, min(final, max_workers))

    logger.debug(
        "auto_process_count: physical=%d cpu_based=%d mem_based=%d env_cap=%s "
        "chunk_cap=%d max_workers=%s -> final=%d",
        physical,
        cpu_based,
        mem_based,
        env_cap,
        chunk_cap,
        max_workers,
        final,
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