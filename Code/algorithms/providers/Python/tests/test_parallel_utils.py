"""单元测试：algorithms._parallel 工具函数。

验证 auto_process_count / adjust_chunk_size_for_parallelism / get_spawn_context
的边界条件与组合行为。所有用例不依赖具体硬件（用 monkeypatch 替换 psutil 调用）。
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from algorithms._parallel import (
    _MEM_PER_WORKER_MB,
    _MIN_CHUNKS_PER_WORKER,
    _SYSTEM_RESERVE_MB,
    adjust_chunk_size_for_parallelism,
    auto_process_count,
    get_spawn_context,
)


class TestAutoProcessCount(unittest.TestCase):
    """auto_process_count 边界与组合测试。"""

    def test_returns_1_when_max_workers_le_1(self) -> None:
        self.assertEqual(auto_process_count(chunk_count=10, max_workers=0), 1)
        self.assertEqual(auto_process_count(chunk_count=10, max_workers=1), 1)
        self.assertEqual(auto_process_count(chunk_count=10, max_workers=-5), 1)

    def test_capped_by_chunk_count(self) -> None:
        # 即使物理核 24，只有 3 个 chunk 就只开 3 进程
        with mock.patch("algorithms._parallel._get_psutil_safely", return_value=None):
            with mock.patch("os.cpu_count", return_value=24):
                result = auto_process_count(chunk_count=3, max_workers=None)
        self.assertLessEqual(result, 3)
        self.assertGreaterEqual(result, 1)

    def test_capped_by_max_workers(self) -> None:
        with mock.patch("algorithms._parallel._get_psutil_safely", return_value=None):
            with mock.patch("os.cpu_count", return_value=24):
                result = auto_process_count(chunk_count=100, max_workers=4)
        self.assertLessEqual(result, 4)

    def test_minimum_1_when_chunk_count_zero(self) -> None:
        with mock.patch("algorithms._parallel._get_psutil_safely", return_value=None):
            with mock.patch("os.cpu_count", return_value=24):
                result = auto_process_count(chunk_count=0, max_workers=None)
        self.assertEqual(result, 1)

    def test_env_cap_respected(self) -> None:
        # 设置环境变量硬上限 = 2
        with mock.patch.dict(os.environ, {"CGDA_MAX_PARALLEL_WORKERS": "2"}):
            with mock.patch("algorithms._parallel._get_psutil_safely", return_value=None):
                with mock.patch("os.cpu_count", return_value=24):
                    result = auto_process_count(chunk_count=100, max_workers=None)
        self.assertLessEqual(result, 2)

    def test_env_cap_invalid_value_ignored(self) -> None:
        # 非数字环境变量应被忽略，回退到 cpu_based
        with mock.patch.dict(os.environ, {"CGDA_MAX_PARALLEL_WORKERS": "not-a-number"}):
            with mock.patch("algorithms._parallel._get_psutil_safely", return_value=None):
                with mock.patch("os.cpu_count", return_value=8):
                    result = auto_process_count(chunk_count=100, max_workers=None)
        # cpu_based = max(1, 8-2) = 6
        self.assertEqual(result, 6)

    def test_psutil_based_memory_cap(self) -> None:
        """模拟 psutil 返回：physical=8, available=4096 MB。

        cpu_based = max(1, 8-2) = 6
        mem_based = floor((4096 - 2048) / 200) = floor(10.24) = 10
        env_cap = cpu_based = 6（无环境变量）
        final = min(6, 10, 6, chunk_cap) = 6
        """
        fake_psutil = mock.MagicMock()
        fake_psutil.cpu_count.return_value = 8
        fake_psutil.virtual_memory().available = 4096 * 1024 * 1024
        with mock.patch("algorithms._parallel._get_psutil_safely", return_value=fake_psutil):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("CGDA_MAX_PARALLEL_WORKERS", None)
                result = auto_process_count(chunk_count=100, max_workers=None)
        self.assertEqual(result, 6)

    def test_psutil_memory_is_binding_constraint(self) -> None:
        """模拟内存很少：physical=16, available=2300 MB。

        cpu_based = max(1, 16-2) = 14
        mem_based = floor((2300 - 2048) / 200) = floor(1.26) = 1
        final = min(14, 1, inf, chunk_cap) = 1
        """
        fake_psutil = mock.MagicMock()
        fake_psutil.cpu_count.return_value = 16
        fake_psutil.virtual_memory().available = 2300 * 1024 * 1024
        with mock.patch("algorithms._parallel._get_psutil_safely", return_value=fake_psutil):
            with mock.patch.dict(os.environ):
                os.environ.pop("CGDA_MAX_PARALLEL_WORKERS", None)
                result = auto_process_count(chunk_count=100, max_workers=None)
        self.assertEqual(result, 1)

    def test_psutil_virtual_memory_failure_falls_back_to_cpu(self) -> None:
        fake_psutil = mock.MagicMock()
        fake_psutil.cpu_count.return_value = 8
        fake_psutil.virtual_memory.side_effect = RuntimeError("access denied")
        with mock.patch("algorithms._parallel._get_psutil_safely", return_value=fake_psutil):
            with mock.patch.dict(os.environ):
                os.environ.pop("CGDA_MAX_PARALLEL_WORKERS", None)
                result = auto_process_count(chunk_count=100, max_workers=None)
        # cpu_based=6, mem_based=cpu_based=6, env_cap=inf, chunk_cap=100 → 6
        self.assertEqual(result, 6)

    def test_cpu_count_zero_falls_back_to_one(self) -> None:
        # os.cpu_count() 返回 None 时 fallback 1
        with mock.patch("algorithms._parallel._get_psutil_safely", return_value=None):
            with mock.patch("os.cpu_count", return_value=None):
                result = auto_process_count(chunk_count=10, max_workers=None)
        # physical=1, cpu_based=max(1,1-2)=1, mem_based=1, env_cap=1, chunk_cap=10 → 1
        self.assertEqual(result, 1)

    def test_cpu_reserve_argument_respected(self) -> None:
        fake_psutil = mock.MagicMock()
        fake_psutil.cpu_count.return_value = 16
        fake_psutil.virtual_memory().available = 32768 * 1024 * 1024
        with mock.patch("algorithms._parallel._get_psutil_safely", return_value=fake_psutil):
            with mock.patch.dict(os.environ):
                os.environ.pop("CGDA_MAX_PARALLEL_WORKERS", None)
                result = auto_process_count(chunk_count=100, max_workers=None, cpu_reserve=4)
        # cpu_based=max(1,16-4)=12, mem_based=floor((32768-2048)/200)=153, env_cap=inf → 12
        self.assertEqual(result, 12)


class TestAdjustChunkSize(unittest.TestCase):
    """adjust_chunk_size_for_parallelism 边界测试。"""

    def test_no_shrink_when_enough_chunks(self) -> None:
        # npix=10000, chunk=2000 → 5 chunks, process=2 → target=4 ≤ 5
        self.assertEqual(adjust_chunk_size_for_parallelism(2000, 10000, 2), 2000)

    def test_shrink_when_too_few_chunks(self) -> None:
        # npix=10000, chunk=2000 → 5 chunks, process=4 → target=8 > 5
        # new = ceil(10000/8) = 1250
        self.assertEqual(adjust_chunk_size_for_parallelism(2000, 10000, 4), 1250)

    def test_shrink_for_large_process_count(self) -> None:
        # npix=10000, chunk=2000, process=8 → target=16
        # new = ceil(10000/16) = 625
        self.assertEqual(adjust_chunk_size_for_parallelism(2000, 10000, 8), 625)

    def test_no_shrink_when_serial(self) -> None:
        # process_count=1 → 直接返回原值
        self.assertEqual(adjust_chunk_size_for_parallelism(2000, 10000, 1), 2000)

    def test_no_shrink_when_process_zero(self) -> None:
        self.assertEqual(adjust_chunk_size_for_parallelism(2000, 10000, 0), 2000)

    def test_zero_npix_returns_original_chunk_size(self) -> None:
        # npix=0 → 直接返回原值（防止除零）
        self.assertEqual(adjust_chunk_size_for_parallelism(2000, 0, 4), 2000)

    def test_negative_npix_returns_original_chunk_size(self) -> None:
        self.assertEqual(adjust_chunk_size_for_parallelism(2000, -100, 4), 2000)

    def test_minimum_1(self) -> None:
        # 极端情况：chunk_size=1, npix=1, process=10 → target=20
        # new = ceil(1/20) = 1
        self.assertEqual(adjust_chunk_size_for_parallelism(1, 1, 10), 1)

    def test_target_chunks_formula(self) -> None:
        """验证 target_chunks = process_count * _MIN_CHUNKS_PER_WORKER。"""
        # 若该常量被意外修改，测试会立即失败提醒
        self.assertEqual(_MIN_CHUNKS_PER_WORKER, 2)


class TestSpawnContext(unittest.TestCase):
    """get_spawn_context 测试。"""

    def test_returns_spawn_context(self) -> None:
        ctx = get_spawn_context()
        self.assertEqual(ctx.get_start_method(), "spawn")

    def test_returns_consistent_spawn_context(self) -> None:
        # multiprocessing.get_context("spawn") 内部缓存 context 对象，
        # 多次调用返回相同实例（这对性能有利）；我们只关心 start_method 一致。
        ctx1 = get_spawn_context()
        ctx2 = get_spawn_context()
        self.assertEqual(ctx1.get_start_method(), "spawn")
        self.assertEqual(ctx1.get_start_method(), ctx2.get_start_method())


class TestConstantsSanity(unittest.TestCase):
    """验证关键常量未被意外修改。"""

    def test_mem_per_worker_positive(self) -> None:
        self.assertGreater(_MEM_PER_WORKER_MB, 0)

    def test_system_reserve_positive(self) -> None:
        self.assertGreater(_SYSTEM_RESERVE_MB, 0)

    def test_min_chunks_per_worker_at_least_2(self) -> None:
        self.assertGreaterEqual(_MIN_CHUNKS_PER_WORKER, 2)


if __name__ == "__main__":
    unittest.main()
