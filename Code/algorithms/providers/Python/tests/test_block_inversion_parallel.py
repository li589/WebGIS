"""Sprint 3.7: block_inversion 多进程并行化等价性与回退测试。

验证：
1. 串行 vs 并行输出在数值上完全一致（dh 与 ddca 两种模式）
2. 任何并行基础设施失败（如 ProcessPoolExecutor 不可用）都能回退到串行完成主任务
3. max_workers=None 时能自动选择进程数并成功完成
4. 编程 bug（AttributeError/NameError 等）不被并行回退掩盖

不直接断言性能加速比（性能由 bench_block_inversion_threads.py 单独验证）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

# 确保 algorithms 包在路径中
algo_root = Path(__file__).resolve().parent.parent
if str(algo_root) not in sys.path:
    sys.path.insert(0, str(algo_root))

from algorithms.block_inversion import execute_block_inversion  # noqa: E402


def _make_synthetic_payload(nt: int = 3, npix: int = 60, seed: int = 42) -> dict:
    """构造合成 .mat 风格 payload，物理量级接近真实 L-band SMAP 场景。"""
    rng = np.random.default_rng(seed)
    # TB ~ 200-280 K（亮温）
    tbv_mat = rng.uniform(220.0, 280.0, size=(nt, npix))
    tbh_mat = rng.uniform(200.0, 260.0, size=(nt, npix))
    # Ts ~ 280-305 K（地表温度）
    ts_mat = rng.uniform(280.0, 305.0, size=(nt, npix))
    # NDVI ~ 0.1-0.8（无量纲）
    ndvi_mat = rng.uniform(0.1, 0.8, size=(nt, npix))
    # SF ~ 0.5-3.0 kg/m²（茎干因子）
    sf_mat = rng.uniform(0.5, 3.0, size=(nt, npix))
    # IA ~ 35-45°（入射角）
    ia_mat = rng.uniform(35.0, 45.0, size=(nt, npix))
    # 静态向量
    albedo = rng.uniform(0.05, 0.15, size=npix)
    b_param = rng.uniform(0.8, 1.2, size=npix)
    clay_fraction = rng.uniform(0.1, 0.5, size=npix)
    porosity = rng.uniform(0.4, 0.5, size=npix)
    landcover = rng.integers(1, 17, size=npix)  # IGBP 1-16
    ndvi_v_max = rng.uniform(0.7, 0.9, size=npix)
    ndvi_v_min = rng.uniform(0.05, 0.2, size=npix)
    # 静态 H（粗糙度，无量纲）
    static_h = rng.uniform(0.1, 0.5, size=npix)
    return {
        "TBv_mat": tbv_mat,
        "TBh_mat": tbh_mat,
        "Ts_mat": ts_mat,
        "NDVI_mat": ndvi_mat,
        "SF_mat": sf_mat,
        "IA_mat": ia_mat,
        "Albedo": albedo,
        "B": b_param,
        "CF": clay_fraction,
        "porosity": porosity,
        "LC": landcover,
        "NDVI_v_max": ndvi_v_max,
        "NDVI_v_min": ndvi_v_min,
        "H": static_h,
    }


class TestSerialParallelEquivalence(unittest.TestCase):
    """验证串行与并行输出在数值上完全一致。"""

    def test_dh_mode_equivalence(self) -> None:
        """dh 模式：max_workers=1 vs max_workers=2 输出一致。"""
        payload = _make_synthetic_payload(nt=3, npix=80)

        serial = execute_block_inversion(
            payload, mode="dh", freq_ghz=1.26, pixel_chunk_size=20, max_workers=1
        )
        parallel = execute_block_inversion(
            payload, mode="dh", freq_ghz=1.26, pixel_chunk_size=20, max_workers=2
        )

        # tau_ini 应完全一致（向量化计算，无随机性）
        np.testing.assert_array_almost_equal(
            serial["Tau_ini_mat"], parallel["Tau_ini_mat"], decimal=12
        )
        # DH_mat 应完全一致（least_squares 是确定性的）
        np.testing.assert_array_almost_equal(
            serial["DH_mat"], parallel["DH_mat"], decimal=10
        )
        # 形状一致
        self.assertEqual(serial["DH_mat"].shape, parallel["DH_mat"].shape)
        self.assertEqual(serial["DH_mat"].shape, (3, 80))

    def test_ddca_mode_equivalence(self) -> None:
        """ddca 模式：max_workers=1 vs max_workers=2 输出一致。"""
        payload = _make_synthetic_payload(nt=3, npix=80)

        serial = execute_block_inversion(
            payload, mode="ddca", freq_ghz=1.26, pixel_chunk_size=20, max_workers=1
        )
        parallel = execute_block_inversion(
            payload, mode="ddca", freq_ghz=1.26, pixel_chunk_size=20, max_workers=2
        )

        np.testing.assert_array_almost_equal(
            serial["Tau_ini_mat"], parallel["Tau_ini_mat"], decimal=12
        )
        np.testing.assert_array_almost_equal(
            serial["SM_mat"], parallel["SM_mat"], decimal=10
        )
        np.testing.assert_array_almost_equal(
            serial["VOD_mat"], parallel["VOD_mat"], decimal=10
        )
        # H_used_mat 应完全一致（来自同一静态 H 输入）
        np.testing.assert_array_almost_equal(
            serial["H_used_mat"], parallel["H_used_mat"], decimal=12
        )

    def test_parallel_chunks_different_boundary(self) -> None:
        """不同 chunk_size 产生不同 chunk 边界，但最终结果应一致。"""
        payload = _make_synthetic_payload(nt=2, npix=70)

        # chunk_size=20 → 4 chunks；chunk_size=15 → 5 chunks（边界不对齐）
        r1 = execute_block_inversion(
            payload, mode="dh", freq_ghz=1.26, pixel_chunk_size=20, max_workers=1
        )
        r2 = execute_block_inversion(
            payload, mode="dh", freq_ghz=1.26, pixel_chunk_size=15, max_workers=1
        )
        np.testing.assert_array_almost_equal(r1["DH_mat"], r2["DH_mat"], decimal=10)


class TestFallbackBehavior(unittest.TestCase):
    """验证并行失败时的串行回退。"""

    def test_fallback_on_parallel_failure(self) -> None:
        """ProcessPoolExecutor 抛出 OSError 时应回退到串行，主任务仍成功。"""
        payload = _make_synthetic_payload(nt=2, npix=40)

        # Mock _run_chunks_parallel 抛出运行时异常（非编程 bug）
        with mock.patch(
            "algorithms.block_inversion._run_chunks_parallel",
            side_effect=OSError("simulated spawn failure"),
        ):
            result = execute_block_inversion(
                payload, mode="dh", freq_ghz=1.26, pixel_chunk_size=10, max_workers=4
            )

        # 主任务成功完成（走了串行回退）
        self.assertEqual(result["DH_mat"].shape, (2, 40))
        # 应该有有效结果（不是全 NaN）
        self.assertTrue(np.any(~np.isnan(result["DH_mat"])))

    def test_programming_bug_not_swallowed(self) -> None:
        """编程 bug（AttributeError 等）不应被串行回退掩盖，必须向上抛出。"""
        payload = _make_synthetic_payload(nt=2, npix=40)

        # Mock _run_chunks_parallel 抛 AttributeError（编程 bug）
        with mock.patch(
            "algorithms.block_inversion._run_chunks_parallel",
            side_effect=AttributeError("'NoneType' object has no attribute 'foo'"),
        ):
            with self.assertRaises(AttributeError):
                execute_block_inversion(
                    payload,
                    mode="dh",
                    freq_ghz=1.26,
                    pixel_chunk_size=10,
                    max_workers=4,
                )

    def test_fallback_on_broken_process_pool(self) -> None:
        """BrokenProcessPool（子进程异常退出）应触发回退。"""
        from concurrent.futures.process import BrokenProcessPool

        payload = _make_synthetic_payload(nt=2, npix=40)

        with mock.patch(
            "algorithms.block_inversion._run_chunks_parallel",
            side_effect=BrokenProcessPool("worker died"),
        ):
            result = execute_block_inversion(
                payload, mode="dh", freq_ghz=1.26, pixel_chunk_size=10, max_workers=4
            )

        self.assertEqual(result["DH_mat"].shape, (2, 40))
        self.assertTrue(np.any(~np.isnan(result["DH_mat"])))


class TestAutoWorkersDefault(unittest.TestCase):
    """max_workers=None 自动选择行为。"""

    def test_auto_workers_completes_successfully_dh(self) -> None:
        payload = _make_synthetic_payload(nt=3, npix=200)
        result = execute_block_inversion(
            payload, mode="dh", freq_ghz=1.26, pixel_chunk_size=50  # max_workers=None
        )
        self.assertEqual(result["DH_mat"].shape, (3, 200))
        # 应该有大量有效结果
        valid_ratio = np.sum(~np.isnan(result["DH_mat"])) / result["DH_mat"].size
        self.assertGreater(valid_ratio, 0.9)

    def test_auto_workers_completes_successfully_ddca(self) -> None:
        payload = _make_synthetic_payload(nt=3, npix=200)
        result = execute_block_inversion(
            payload, mode="ddca", freq_ghz=1.26, pixel_chunk_size=50
        )
        self.assertEqual(result["SM_mat"].shape, (3, 200))
        self.assertEqual(result["VOD_mat"].shape, (3, 200))
        valid_ratio = np.sum(~np.isnan(result["SM_mat"])) / result["SM_mat"].size
        self.assertGreater(valid_ratio, 0.9)

    def test_auto_workers_equivalent_to_serial(self) -> None:
        """max_workers=None 自动选择的结果应与 max_workers=1 一致。"""
        payload = _make_synthetic_payload(nt=3, npix=120)

        auto = execute_block_inversion(
            payload, mode="dh", freq_ghz=1.26, pixel_chunk_size=30
        )
        serial = execute_block_inversion(
            payload, mode="dh", freq_ghz=1.26, pixel_chunk_size=30, max_workers=1
        )
        np.testing.assert_array_almost_equal(auto["DH_mat"], serial["DH_mat"], decimal=10)


class TestEdgeCases(unittest.TestCase):
    """边界场景。"""

    def test_small_payload_runs_serial(self) -> None:
        """npix 很小时 chunk_count=1，自动走串行路径。"""
        payload = _make_synthetic_payload(nt=2, npix=5)
        result = execute_block_inversion(
            payload,
            mode="dh",
            freq_ghz=1.26,
            pixel_chunk_size=2000,  # 默认值，npix=5 < chunk_size → 1 chunk
            max_workers=8,
        )
        self.assertEqual(result["DH_mat"].shape, (2, 5))

    def test_explicit_max_workers_zero_runs_serial(self) -> None:
        payload = _make_synthetic_payload(nt=2, npix=20)
        result = execute_block_inversion(
            payload, mode="dh", freq_ghz=1.26, pixel_chunk_size=5, max_workers=0
        )
        self.assertEqual(result["DH_mat"].shape, (2, 20))

    def test_chunk_size_shrink_for_parallelism(self) -> None:
        """chunk_size 自动缩小以产生足够 chunk 支持并行。"""
        payload = _make_synthetic_payload(nt=2, npix=100)
        # pixel_chunk_size=200, npix=100 → 1 chunk → process_count=1
        # 但若 max_workers=4，adjust_chunk_size_for_parallelism 会缩小到 13 (ceil(100/8))
        result = execute_block_inversion(
            payload,
            mode="dh",
            freq_ghz=1.26,
            pixel_chunk_size=200,  # 大于 npix
            max_workers=4,
        )
        self.assertEqual(result["DH_mat"].shape, (2, 100))


if __name__ == "__main__":
    unittest.main()
