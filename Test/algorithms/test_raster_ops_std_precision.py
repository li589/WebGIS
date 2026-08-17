"""分块栅格 std 数值精度测试（数值专项 W4）。

旧实现用一阶矩公式 ``E[X²]-E[X]²`` 跨块累加：大均值小方差场景
（TB~300K、σ~1，甚至 mean=1e6、σ=1e-3）两个同量级大数相减发生
灾难性相消，std 相对误差可达 1e-4 乃至 100%。新实现逐块
(count, mean, M2) + Chan 合并，精度回到两遍法水平。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")

import contracts.job  # noqa: F401, E402  (先行导入打破 modules 循环导入)
from modules._raster_ops import reduce_raster_blocks  # noqa: E402


def _write_tiled_tif(path: Path, data: np.ndarray, tile: int = 128) -> None:
    from rasterio.transform import from_bounds

    height, width = data.shape
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float64",
        "crs": "EPSG:4326",
        "transform": from_bounds(100, 30, 104, 34, width, height),
        "nodata": np.nan,
        "tiled": True,
        "blockxsize": tile,
        "blockysize": tile,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def test_std_matches_numpy_two_pass_tb_scale(tmp_path: Path) -> None:
    """TB 量级 mean=300、σ=1、N≈1e6：分块 std vs np.std rtol 1e-12。"""
    rng = np.random.default_rng(20260818)
    data = rng.normal(loc=300.0, scale=1.0, size=(1024, 1024))
    tif = tmp_path / "tb_scale.tif"
    _write_tiled_tif(tif, data, tile=128)  # 8×8=64 块，走 Chan 合并路径
    value, count = reduce_raster_blocks(tif, statistic="std")
    expected = float(np.std(data, ddof=0))
    assert count == data.size
    assert value == pytest.approx(expected, rel=1e-12)


def test_std_large_mean_tiny_sigma_no_cancellation(tmp_path: Path) -> None:
    """mean=1e6、σ=1e-3：旧一阶矩公式在此必错（相消吃掉全部方差位）。"""
    rng = np.random.default_rng(42)
    data = 1_000_000.0 + rng.normal(loc=0.0, scale=1e-3, size=(512, 512))
    tif = tmp_path / "extreme.tif"
    _write_tiled_tif(tif, data, tile=128)
    value, count = reduce_raster_blocks(tif, statistic="std")
    expected = float(np.std(data, ddof=0))
    assert value == pytest.approx(expected, rel=1e-6)
    assert value > 0.0  # 不得因相消出负方差被 max(·,0) 钳成 0


def test_std_with_nan_nodata_pixels(tmp_path: Path) -> None:
    """NaN 像元剔除后 std 正确（有限像元口径）。"""
    rng = np.random.default_rng(7)
    data = rng.normal(loc=280.0, scale=2.0, size=(256, 256))
    data[::3, ::5] = np.nan
    tif = tmp_path / "with_nan.tif"
    _write_tiled_tif(tif, data, tile=128)
    value, count = reduce_raster_blocks(tif, statistic="std")
    finite = data[np.isfinite(data)]
    assert count == finite.size
    assert value == pytest.approx(float(np.std(finite, ddof=0)), rel=1e-12)


def test_mean_sum_unchanged_semantics(tmp_path: Path) -> None:
    """mean/sum/min/max 语义不受重构影响。"""
    rng = np.random.default_rng(11)
    data = rng.normal(loc=300.0, scale=5.0, size=(256, 256))
    tif = tmp_path / "basic.tif"
    _write_tiled_tif(tif, data, tile=128)
    mean_v, _ = reduce_raster_blocks(tif, statistic="mean")
    sum_v, _ = reduce_raster_blocks(tif, statistic="sum")
    min_v, _ = reduce_raster_blocks(tif, statistic="min")
    max_v, _ = reduce_raster_blocks(tif, statistic="max")
    assert mean_v == pytest.approx(float(np.mean(data)), rel=1e-12)
    assert sum_v == pytest.approx(float(np.sum(data)), rel=1e-12)
    assert min_v == pytest.approx(float(np.min(data)))
    assert max_v == pytest.approx(float(np.max(data)))
