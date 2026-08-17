"""FY 预处理 NetCDF 输出 _FillValue 标准化测试（数值专项 W5）。

旧实现：数据体写 NaN、写后赋非标准属性 ``FillValue=-32767``——
按 CF 标准自动掩膜的消费端查 ``_FillValue`` 掩不住任何点，且属性
名不合规。修复后：创建期 ``fill_value=np.nan`` 设标准 ``_FillValue``，
数据体维持 NaN——掩膜语义与数据语义自洽。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("netCDF4")
pytest.importorskip("rasterio")

from ingest.fy_preprocess import (  # noqa: E402
    _TB_BAND_NAMES,
    FyPreprocessOptions,
    FyPreprocessor,
    FySatelliteConfig,
)


def _make_preprocessor() -> FyPreprocessor:
    # 跳过 __init__ 的 GDAL 可执行文件解析——单测只覆盖 _write_netcdf
    proc = object.__new__(FyPreprocessor)
    proc.config = FySatelliteConfig.for_fy3d()
    proc._band_names = _TB_BAND_NAMES
    return proc


def _make_two_band_tif(path: Path) -> None:
    import rasterio
    from rasterio.transform import from_bounds

    size = 8
    tb = np.full((size, size), 250.0, dtype=np.float32)
    tb[0, 0] = np.nan
    zen = np.full((size, size), 100.0, dtype=np.float32)
    zen[-1, -1] = np.nan
    profile = {
        "driver": "GTiff",
        "height": size,
        "width": size,
        "count": 2,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_bounds(100, 30, 101, 31, size, size),
        "nodata": np.nan,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(tb, 1)
        dst.write(zen, 2)


def test_write_netcdf_standard_fillvalue(tmp_path: Path) -> None:
    from netCDF4 import Dataset

    proc = _make_preprocessor()
    tif = tmp_path / "merged.tif"
    _make_two_band_tif(tif)
    proc._write_netcdf(
        str(tif),
        str(tmp_path),
        "10V",
        "20250101",
        FyPreprocessOptions(),
        ["10V", "Sensor_Zenith"],
        tb_slope=0.01,
        tb_intercept=327.68,
        zen_slope=0.01,
        zen_intercept=0.0,
    )
    nc_path = tmp_path / "FY3D_GBAL_L1_10V_20250101_MWRID.nc"
    assert nc_path.is_file()
    with Dataset(nc_path) as ds:
        assert len(ds.variables) == 2
        for name, var in ds.variables.items():
            attrs = set(var.ncattrs())
            # 标准 _FillValue 必须存在且为 NaN（与数据体一致）
            assert "_FillValue" in attrs, f"{name} 缺标准 _FillValue"
            assert np.isnan(float(var.getncattr("_FillValue")))
            # 非标准属性名必须移除
            assert "FillValue" not in attrs, f"{name} 残留非标准 FillValue 属性"
            # 标准自动掩膜：NaN 点被掩住
            auto = var[:]
            assert np.ma.isMaskedArray(auto)
            assert auto.mask.any()
            # 关闭掩膜读取：数据体为 NaN（物理语义）
            var.set_auto_maskandscale(False)
            raw = np.asarray(var[:], dtype=np.float64)
            assert np.isnan(raw).any()
            valid = np.isfinite(raw)
            assert valid.any()
            expected_fill = 100.0 if name == "Sensor_Zenith" else 250.0
            np.testing.assert_allclose(
                raw[valid], expected_fill, rtol=0, atol=1e-5
            )
