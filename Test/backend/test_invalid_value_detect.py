"""无效值自动检测：哨兵频率、Inf、FillValue 建议。"""

from __future__ import annotations

import numpy as np

from app.data_io.services.raster_science import detect_sentinel_values


def test_detect_sentinel_frequency_and_fill():
    arr = np.full((100, 100), 1.0, dtype=np.float32)
    arr[0:10, :] = -9999.0
    arr[10:12, :] = np.inf
    result = detect_sentinel_values(arr, fill_value=-9999.0, missing_value=-999.0)
    assert result["inf_count"] > 0
    values = {s["value"] for s in result["sentinels"]}
    assert -9999.0 in values
    assert -9999.0 in result["suggested_invalid_values"]
    assert -999.0 in result["metadata_fill_values"]
    assert -999.0 in result["suggested_invalid_values"]


def test_detect_sentinel_empty():
    result = detect_sentinel_values(np.array([], dtype=np.float32))
    assert result["suggested_invalid_values"] == []
    assert result["inf_count"] == 0
