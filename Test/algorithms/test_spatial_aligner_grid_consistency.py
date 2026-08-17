"""空间对齐格网一致性测试（数值专项 C3）。

锁定：``_coordinate_based_resample`` 的插值目标轴必须与 ``align_to_grid``
返回坐标轴（pixel_center_axis 像素中心）同轴。若插值用 ``linspace`` 边点
而返回中心坐标，二者系统性错开半像素（0.25° 网格 = 0.125°），多源融合
空间配准整体偏移。

用线性场（value = lon / value = lat）做恒等检验：源格网即目标格网时，
对齐结果应精确复现源值——任何半像素错位都会立即反映在线性场的平移上。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("netCDF4")

from data_access.geo_math import pixel_center_axis  # noqa: E402
from data_access.spatial_aligner import SpatialAligner  # noqa: E402

BBOX = (100.0, 40.0, 102.0, 42.0)
RES = 0.5
N = 4
LAT_CENTERS = np.asarray(pixel_center_axis(42.0, 40.0, N), dtype=np.float64)
LON_CENTERS = np.asarray(pixel_center_axis(100.0, 102.0, N), dtype=np.float64)


def _make_netcdf(path: Path, field: np.ndarray) -> None:
    from netCDF4 import Dataset

    with Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("lat", N)
        ds.createDimension("lon", N)
        lat = ds.createVariable("lat", "f8", ("lat",))
        lon = ds.createVariable("lon", "f8", ("lon",))
        var = ds.createVariable("ts", "f8", ("lat", "lon"))
        lat[:] = LAT_CENTERS  # 降序（北→南）
        lon[:] = LON_CENTERS
        var[:] = field


def test_aligned_lon_ramp_matches_returned_axis(tmp_path: Path) -> None:
    """源场 value=lon：对齐结果每列 == 返回的 lon 中心轴。"""
    nc = tmp_path / "lon_ramp.nc"
    _make_netcdf(nc, np.broadcast_to(LON_CENTERS, (N, N)).copy())
    aligned, lat_1d, lon_1d = SpatialAligner().align_to_grid(
        source_path=nc, variable="ts", target_resolution=RES, bbox=BBOX
    )
    assert aligned.shape == (N, N)
    # 返回轴确为像素中心
    np.testing.assert_allclose(lon_1d, LON_CENTERS, rtol=0, atol=1e-12)
    np.testing.assert_allclose(lat_1d, LAT_CENTERS, rtol=0, atol=1e-12)
    # 插值采样轴 == 返回坐标轴：线性场在采样点处值恒等
    expected = np.broadcast_to(np.asarray(lon_1d), (N, N))
    np.testing.assert_allclose(
        aligned, expected, rtol=0, atol=1e-9, err_msg="插值轴与返回坐标轴错位（半像素偏移）"
    )


def test_aligned_lat_ramp_matches_returned_axis(tmp_path: Path) -> None:
    """源场 value=lat：对齐结果每行 == 返回的 lat 中心轴。"""
    nc = tmp_path / "lat_ramp.nc"
    _make_netcdf(nc, np.broadcast_to(LAT_CENTERS[:, None], (N, N)).copy())
    aligned, lat_1d, _ = SpatialAligner().align_to_grid(
        source_path=nc, variable="ts", target_resolution=RES, bbox=BBOX
    )
    expected = np.broadcast_to(np.asarray(lat_1d)[:, None], (N, N))
    np.testing.assert_allclose(aligned, expected, rtol=0, atol=1e-9)


def test_half_pixel_shift_is_detectable_in_fixture(tmp_path: Path) -> None:
    """反证：linspace 边点轴与中心轴在 0.5° 网格上差 0.25°（半像素）。

    若有人把插值轴改回 linspace，上面两个恒等检验必然以
    ≥0.25° 的等效平移失败——本用例显式固定该差值，防止误判容差。
    """
    linspace_lon = np.linspace(BBOX[0], BBOX[2], N)
    assert np.max(np.abs(linspace_lon - LON_CENTERS)) == pytest.approx(
        RES / 2, abs=1e-12
    )
