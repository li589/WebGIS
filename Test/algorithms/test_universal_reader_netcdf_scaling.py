"""NetCDF 缩放/填充语义探针（数值专项 C2）。

构造 int16 + scale_factor/add_offset/_FillValue 的合成 NetCDF，经
UniversalDataReader 读取，锁定三条硬语义：

1. 物理值 == raw × scale_factor + add_offset（**恰好一次**缩放）
2. _FillValue → NaN（不泄漏为物理值/缩放后的残值）
3. 输出为普通 float64 ndarray（无掩码语义泄漏）

背景：netCDF4 ``var[...]`` 默认 auto maskandscale（读出已缩放 + 掩码数组），
若读取端再手工 ``*scale+offset`` 即双重缩放。本测试为 TDD 红灯载体，
修复后永久锁死"手工清洗/缩放管线是唯一真源"的行为。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("netCDF4")

from data_access.universal_reader import UniversalDataReader  # noqa: E402

SCALE = 0.01
OFFSET = 273.15
# 降序 lat（GLDAS/ERA5 常见北极→南极排列），raw 值避开 fill
RAW = np.array([[0, 100, 200], [300, 400, 500]], dtype=np.int16)
FILL_RAW = np.int16(-32768)
FILL_POS = (0, 1)


def _make_scaled_netcdf(path: Path) -> None:
    """写 raw int16 + 缩放属性 + fill 的最小 NetCDF。

    写入端显式关闭 auto maskandscale，保证 raw 整数原样落盘
    （否则 netCDF4 会按物理值打包，raw 不可控）。
    """
    from netCDF4 import Dataset

    ny, nx = RAW.shape
    with Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("lat", ny)
        ds.createDimension("lon", nx)
        lat = ds.createVariable("lat", "f8", ("lat",))
        lon = ds.createVariable("lon", "f8", ("lon",))
        lat[:] = np.array([50.0, 49.0])
        lon[:] = np.array([100.0, 101.0, 102.0])
        var = ds.createVariable("ts", "i2", ("lat", "lon"), fill_value=FILL_RAW)
        var.set_auto_maskandscale(False)
        var.scale_factor = SCALE
        var.add_offset = OFFSET
        raw = RAW.copy()
        raw[FILL_POS] = FILL_RAW
        var[:] = raw


def _read_values(tmp_path: Path) -> np.ndarray:
    nc = tmp_path / "scaled.nc"
    _make_scaled_netcdf(nc)
    reader = UniversalDataReader(nc)
    assert reader.format == "netcdf"
    data = reader.read_variable("ts")
    assert data.values is not None
    return np.asarray(data.values)


def test_single_scaling_physical_values(tmp_path: Path) -> None:
    """每个有效像元物理值 == raw×scale+offset，恰好一次缩放。"""
    values = _read_values(tmp_path)
    assert values.dtype == np.float64
    assert values.shape == RAW.shape
    for (i, j), raw in np.ndenumerate(RAW):
        if (i, j) == FILL_POS:
            continue
        expected = float(raw) * SCALE + OFFSET
        assert values[i, j] == pytest.approx(expected, rel=1e-12, abs=1e-12), (i, j)


def test_fill_value_maps_to_nan(tmp_path: Path) -> None:
    """_FillValue 像元读出为 NaN，而非缩放后的物理残值。"""
    values = _read_values(tmp_path)
    assert bool(np.isnan(values[FILL_POS])), (
        f"fill 像元泄漏为物理值 {values[FILL_POS]!r}（双重缩放/掩码丢失症状）"
    )


def test_no_mask_semantics_leak(tmp_path: Path) -> None:
    """输出为普通 ndarray；有效像元不因掩码处理被误伤。"""
    from numpy.ma import MaskedArray

    values = _read_values(tmp_path)
    assert not isinstance(values, MaskedArray)
    valid_mask = np.ones(RAW.shape, dtype=bool)
    valid_mask[FILL_POS] = False
    assert np.isfinite(values[valid_mask]).all()


def test_list_variables_and_attrs_roundtrip(tmp_path: Path) -> None:
    nc = tmp_path / "scaled.nc"
    _make_scaled_netcdf(nc)
    reader = UniversalDataReader(nc)
    assert "ts" in reader.list_variables()
    data = reader.read_variable("ts")
    assert data.attrs.get("scale_factor") == pytest.approx(SCALE)
    assert data.attrs.get("add_offset") == pytest.approx(OFFSET)
