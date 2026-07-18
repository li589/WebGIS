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


class TestProcessChunkDirect(unittest.TestCase):
    """直接测试 _process_chunk 模块级 worker（不经过 execute_block_inversion）。

    验证 chunk 切片后的输入能被正确处理，以及 mode 分支返回字段正确。
    """

    @staticmethod
    def _make_chunk_inputs(nt: int, chunk_npix: int, seed: int = 42) -> dict:
        rng = np.random.default_rng(seed)
        return {
            "ndvi_mat_chunk": rng.uniform(0.1, 0.8, (nt, chunk_npix)),
            "ndvi_v_max_chunk": np.full(chunk_npix, 0.8),
            "ndvi_v_min_chunk": np.full(chunk_npix, 0.1),
            "landcover_chunk": np.full(chunk_npix, 6, dtype=int),
            "b_param_chunk": np.full(chunk_npix, 1.0),
            "sf_mat_chunk": rng.uniform(0.5, 3.0, (nt, chunk_npix)),
            "ia_mat_chunk": rng.uniform(35.0, 45.0, (nt, chunk_npix)),
            "tbv_mat_chunk": rng.uniform(220.0, 280.0, (nt, chunk_npix)),
            "tbh_mat_chunk": rng.uniform(200.0, 260.0, (nt, chunk_npix)),
            "ts_mat_chunk": rng.uniform(280.0, 305.0, (nt, chunk_npix)),
            "clay_fraction_chunk": rng.uniform(0.1, 0.5, chunk_npix),
            "albedo_chunk": rng.uniform(0.05, 0.15, chunk_npix),
            "porosity_chunk": rng.uniform(0.4, 0.5, chunk_npix),
        }

    def test_dh_mode_returns_dh_chunk(self) -> None:
        from algorithms.block_inversion import _process_chunk

        nt, chunk_npix = 2, 5
        inputs = self._make_chunk_inputs(nt, chunk_npix)
        result = _process_chunk(
            10, 15, mode="dh", nt=nt, freq_ghz=1.26,
            h_mat_chunk=None, **inputs,
        )
        self.assertEqual(result["start"], 10)
        self.assertEqual(result["end"], 15)
        self.assertEqual(result["tau_ini"].shape, (nt, chunk_npix))
        self.assertEqual(result["dh"].shape, (nt, chunk_npix))
        self.assertNotIn("sm", result)
        self.assertNotIn("vod", result)
        # tau_ini 应有有效值（非全 NaN）
        self.assertTrue(np.any(~np.isnan(result["tau_ini"])))

    def test_ddca_mode_returns_sm_vod_chunk(self) -> None:
        from algorithms.block_inversion import _process_chunk

        nt, chunk_npix = 2, 5
        inputs = self._make_chunk_inputs(nt, chunk_npix)
        result = _process_chunk(
            0, chunk_npix, mode="ddca", nt=nt, freq_ghz=1.26,
            h_mat_chunk=np.full((nt, chunk_npix), 0.3), **inputs,
        )
        self.assertEqual(result["sm"].shape, (nt, chunk_npix))
        self.assertEqual(result["vod"].shape, (nt, chunk_npix))
        self.assertNotIn("dh", result)

    def test_pickle_roundtrip(self) -> None:
        """_process_chunk 必须可 pickle（spawn 子进程要求）。"""
        import pickle

        from algorithms.block_inversion import _process_chunk

        data = pickle.dumps(_process_chunk)
        restored = pickle.loads(data)
        self.assertIs(restored, _process_chunk)


class TestPrepareChunkKwargsDirect(unittest.TestCase):
    """直接测试 _prepare_chunk_kwargs 切片逻辑。"""

    @staticmethod
    def _make_matrices(nt: int, npix: int) -> dict:
        return {
            "ndvi_mat": np.zeros((nt, npix)),
            "ndvi_v_max": np.ones(npix),
            "ndvi_v_min": np.zeros(npix),
            "landcover": np.full(npix, 6, dtype=int),
            "b_param": np.ones(npix),
            "sf_mat": np.ones((nt, npix)),
            "ia_mat": np.full((nt, npix), 40.0),
            "tbv_mat": np.full((nt, npix), 250.0),
            "tbh_mat": np.full((nt, npix), 230.0),
            "ts_mat": np.full((nt, npix), 290.0),
            "clay_fraction": np.full(npix, 0.3),
            "albedo": np.full(npix, 0.1),
            "porosity": np.full(npix, 0.45),
            "h_mat": None,
        }

    def test_dh_mode_h_mat_chunk_is_none(self) -> None:
        from algorithms.block_inversion import _prepare_chunk_kwargs

        matrices = self._make_matrices(nt=3, npix=10)
        kwargs = _prepare_chunk_kwargs(matrices, slice(2, 5), "dh")
        self.assertIsNone(kwargs["h_mat_chunk"])
        # 验证 2D 矩阵切片形状 (nt, 3)
        self.assertEqual(kwargs["ndvi_mat_chunk"].shape, (3, 3))
        self.assertEqual(kwargs["tbv_mat_chunk"].shape, (3, 3))
        # 验证 1D 向量切片形状 (3,)
        self.assertEqual(kwargs["ndvi_v_max_chunk"].shape, (3,))
        self.assertEqual(kwargs["clay_fraction_chunk"].shape, (3,))

    def test_ddca_mode_h_mat_chunk_sliced(self) -> None:
        from algorithms.block_inversion import _prepare_chunk_kwargs

        nt, npix = 3, 10
        matrices = self._make_matrices(nt, npix)
        matrices["h_mat"] = np.full((nt, npix), 0.3)
        kwargs = _prepare_chunk_kwargs(matrices, slice(2, 5), "ddca")
        self.assertEqual(kwargs["h_mat_chunk"].shape, (nt, 3))
        # 验证切片值正确
        np.testing.assert_array_equal(
            kwargs["h_mat_chunk"], np.full((nt, 3), 0.3)
        )

    def test_ddca_mode_h_mat_none_fallback(self) -> None:
        """ddca 模式但 h_mat 为 None 时，h_mat_chunk 应为 None（不崩）。"""
        from algorithms.block_inversion import _prepare_chunk_kwargs

        matrices = self._make_matrices(nt=2, npix=8)
        # h_mat 已为 None
        kwargs = _prepare_chunk_kwargs(matrices, slice(0, 4), "ddca")
        self.assertIsNone(kwargs["h_mat_chunk"])


if __name__ == "__main__":
    unittest.main()
