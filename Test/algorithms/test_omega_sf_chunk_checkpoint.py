"""P3 增量化（2026-08-23）：omega_sf chunk checkpoint 增量目录回归测试。

旧机制：每 chunk 完成全量重写单文件 JSON（O(N·chunks) 总 IO，全量超 500MB
即失效拒载）。新机制：``.omega_sf_chunks/`` 目录下每 chunk 一个文件
（O(N) 总 IO），meta.json 记日期窗口；旧单文件兼容读取（读后 rename .done）；
成功完成后清理全部检查点。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Code/algorithms/providers/Python"))

from algorithms.omega_sf import (  # noqa: E402
    PixelResult,
    _append_chunk_checkpoint,
    _checkpoint_path,
    _chunks_checkpoint_dir,
    _cleanup_chunk_checkpoint,
    _load_chunk_checkpoint,
)


def _pr(iy: int, ix: int, tag: float = 1.0) -> PixelResult:
    return PixelResult(
        iy=iy,
        ix=ix,
        class_id=2,
        omega=np.full(3, tag),
        sm=np.full(3, tag + 0.1),
        vod=np.full(3, tag + 0.2),
        h_star=0.5,
        alpha_star=0.25,
    )


class ChunkCheckpointIncrementalTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_then_load_roundtrip(self) -> None:
        """增量保存两个 chunk → load 聚合正确（P3 核心）。"""
        _append_chunk_checkpoint(
            self.out,
            start_date="2025-01-01",
            end_date="2025-01-31",
            chunk_index=0,
            chunk_results=[_pr(1, 1, 1.0), _pr(1, 2, 1.5)],
        )
        _append_chunk_checkpoint(
            self.out,
            start_date="2025-01-01",
            end_date="2025-01-31",
            chunk_index=1,
            chunk_results=[_pr(2, 1, 2.0)],
        )
        # 文件结构：meta + 两个 chunk 文件（非全量单文件）
        chunks_dir = _chunks_checkpoint_dir(self.out)
        self.assertTrue((chunks_dir / "meta.json").is_file())
        self.assertEqual(len(list(chunks_dir.glob("chunk_*.json"))), 2)
        self.assertFalse(_checkpoint_path(self.out).exists())

        loaded = _load_chunk_checkpoint(
            self.out, start_date="2025-01-01", end_date="2025-01-31"
        )
        assert loaded is not None
        done, results = loaded
        self.assertEqual(done, {0, 1})
        self.assertEqual(len(results), 3)
        self.assertTrue(np.allclose(results[0].omega, [1.0, 1.0, 1.0]))
        self.assertTrue(np.allclose(results[2].vod, [2.2, 2.2, 2.2]))

    def test_append_is_incremental_not_full_rewrite(self) -> None:
        """第二个 chunk 保存不重写第一个 chunk 的文件（增量证据）。"""
        _append_chunk_checkpoint(
            self.out,
            start_date="2025-01-01",
            end_date="2025-01-31",
            chunk_index=0,
            chunk_results=[_pr(1, 1)],
        )
        f0 = _chunks_checkpoint_dir(self.out) / "chunk_0000.json"
        mtime0 = f0.stat().st_mtime_ns
        _append_chunk_checkpoint(
            self.out,
            start_date="2025-01-01",
            end_date="2025-01-31",
            chunk_index=1,
            chunk_results=[_pr(2, 1)],
        )
        # chunk_0000 未被触碰（旧全量重写会重写整个单文件）
        self.assertEqual(f0.stat().st_mtime_ns, mtime0)

    def test_legacy_single_file_compat_and_migration(self) -> None:
        """旧单文件格式可读，读后 rename .done 防重复消费。"""
        legacy = _checkpoint_path(self.out)
        payload = {
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "completed_chunks": [0, 3],
            "all_results": [
                {
                    "iy": 1,
                    "ix": 1,
                    "class_id": 1,
                    "omega": [0.5, 0.5],
                    "sm": [0.6, 0.6],
                    "vod": [0.7, 0.7],
                    "h_star": 0.1,
                    "alpha_star": 0.2,
                }
            ],
        }
        legacy.write_text(json.dumps(payload), encoding="utf-8")

        loaded = _load_chunk_checkpoint(
            self.out, start_date="2025-01-01", end_date="2025-01-31"
        )
        assert loaded is not None
        done, results = loaded
        self.assertEqual(done, {0, 3})
        self.assertEqual(len(results), 1)
        self.assertTrue(np.allclose(results[0].omega, [0.5, 0.5]))
        # 旧文件已迁移为 .done，原路径不存在
        self.assertFalse(legacy.exists())
        self.assertTrue(legacy.with_suffix(legacy.suffix + ".done").exists())

        # 第二次 load：旧文件不再重复读（.done 不被读）
        loaded2 = _load_chunk_checkpoint(
            self.out, start_date="2025-01-01", end_date="2025-01-31"
        )
        self.assertIsNone(loaded2)

    def test_date_mismatch_ignored(self) -> None:
        """日期窗口不一致 → 增量目录与旧文件都忽略。"""
        _append_chunk_checkpoint(
            self.out,
            start_date="2025-01-01",
            end_date="2025-01-31",
            chunk_index=0,
            chunk_results=[_pr(1, 1)],
        )
        loaded = _load_chunk_checkpoint(
            self.out, start_date="2025-02-01", end_date="2025-02-28"
        )
        self.assertIsNone(loaded)

    def test_cleanup_removes_all_checkpoint_artifacts(self) -> None:
        """成功清理：增量目录 + 旧单文件 + .done 残留全删。"""
        _append_chunk_checkpoint(
            self.out,
            start_date="2025-01-01",
            end_date="2025-01-31",
            chunk_index=0,
            chunk_results=[_pr(1, 1)],
        )
        legacy = _checkpoint_path(self.out)
        legacy.write_text("{}", encoding="utf-8")
        legacy.with_suffix(legacy.suffix + ".done").write_text("{}", encoding="utf-8")

        _cleanup_chunk_checkpoint(self.out)

        self.assertFalse(_chunks_checkpoint_dir(self.out).exists())
        self.assertFalse(legacy.exists())
        self.assertFalse(legacy.with_suffix(legacy.suffix + ".done").exists())

    def test_empty_chunk_list_roundtrip(self) -> None:
        """空结果的 chunk（如 0 像元 chunk）保存/加载不炸。"""
        _append_chunk_checkpoint(
            self.out,
            start_date="2025-01-01",
            end_date="2025-01-31",
            chunk_index=7,
            chunk_results=[],
        )
        loaded = _load_chunk_checkpoint(
            self.out, start_date="2025-01-01", end_date="2025-01-31"
        )
        assert loaded is not None
        done, results = loaded
        self.assertEqual(done, {7})
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
