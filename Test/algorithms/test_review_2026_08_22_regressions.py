"""完全审查 2026-08-22 批次3 回归锁定（E-1 / E-2）。

- E-1：0-360 经度网格（ERA5 风格）跨缝 bbox 必须完整返回两段数据，
  不得静默丢失 [0, east] 段；w==e 视为全球环绕。
- E-2：ProviderExecutionPayload 构造期 parameters 键数封顶（P0-5），
  不依赖 backend bridge 的校验独立成立。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("netCDF4")

from data_access.universal_reader import UniversalDataReader  # noqa: E402

# 8 列 0-360 网格（45° 分辨率），值 == 列索引，便于断言哪几列被读到
LON_0360 = np.array([0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0])
LAT = np.array([60.0, 0.0, -60.0])
GRID = np.arange(24, dtype=np.float64).reshape(3, 8) % 8  # 值 == 列号


def _make_0360_netcdf(path: Path) -> None:
    from netCDF4 import Dataset

    with Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("lat", 3)
        ds.createDimension("lon", 8)
        ds.createVariable("lat", "f8", ("lat",))[:] = LAT
        ds.createVariable("lon", "f8", ("lon",))[:] = LON_0360
        var = ds.createVariable("ts", "f8", ("lat", "lon"))
        var.set_auto_maskandscale(False)
        var[:] = GRID


def _read(tmp_path: Path, bbox):
    nc = tmp_path / "g0360.nc"
    if not nc.exists():
        _make_0360_netcdf(nc)
    return UniversalDataReader(nc).read_variable("ts", bbox=bbox)


def test_seam_crossing_bbox_returns_both_segments(tmp_path: Path) -> None:
    """bbox=(-100, *, 10, *) 跨缝：西段 [260,360)→{270,315} + 东段 [0,10)→{0}。

    修复前：东段 [0,10] 被静默丢弃（只得 {270,315}）。
    """
    data = _read(tmp_path, (-100.0, -60.0, 10.0, 60.0))
    lons = np.asarray(data.lon)
    assert 270.0 in lons and 315.0 in lons  # 西段
    assert 0.0 in lons  # 东段（修复前丢失）
    assert 45.0 not in lons and 225.0 not in lons  # 缝外不多取
    assert data.values is not None
    assert data.values.shape[-1] == len(lons)


def test_global_bbox_on_0360_returns_full_width(tmp_path: Path) -> None:
    """bbox=(-180, *, 180, *) 全球环绕：返回全部 8 列且不重复。"""
    data = _read(tmp_path, (-180.0, -60.0, 180.0, 60.0))
    lons = np.asarray(data.lon)
    assert len(lons) == 8
    assert len(set(lons.tolist())) == 8


def test_non_seam_bbox_0360_unchanged(tmp_path: Path) -> None:
    """不跨缝的 0-360 bbox 行为不变（40..100 → 45/90/135，东缘 +1 含下一列）。"""
    data = _read(tmp_path, (40.0, -60.0, 100.0, 60.0))
    lons = np.asarray(data.lon)
    assert 45.0 in lons and 90.0 in lons and 135.0 in lons
    assert 0.0 not in lons and 180.0 not in lons


def test_payload_parameter_key_cap() -> None:
    from algorithms.providers.base import MAX_PARAMETER_KEYS, ProviderExecutionPayload

    with pytest.raises(ValueError, match="Too many parameter keys"):
        ProviderExecutionPayload(
            layer_id="lab-output",
            requested_at=datetime.now(UTC),
            requested_hour=0.0,
            parameters={f"k{i}": i for i in range(MAX_PARAMETER_KEYS + 1)},
        )

    # 恰好上限可通过
    ProviderExecutionPayload(
        layer_id="lab-output",
        requested_at=datetime.now(UTC),
        requested_hour=0.0,
        parameters={f"k{i}": i for i in range(MAX_PARAMETER_KEYS)},
    )
