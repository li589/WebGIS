"""CLCD 报障回归：整型（uint8 分类）源的颜色化 dtype 安全。

2026-08-24：uint8 源上 MaskedArray.filled(nan) 抛 TypeError（NaN 无法转
int dtype）→ 注册 preview 渲染整链失败（imports 目录只剩源文件，无
bounds.json/preview.png = "工作流完成但图层不显示"）。
"""

from __future__ import annotations

import numpy as np

from app.services.raster_preview_service import (
    _colorize_masked_band,
    _mask_invalid_raster,
    get_palette_rgb_stops,
)


def test_mask_invalid_raster_uint8() -> None:
    band = np.ma.array(
        np.array([[1, 2], [3, 0]], dtype=np.uint8),
        mask=np.array([[False, False], [False, True]]),
    )
    out = _mask_invalid_raster(np, band, nodata=None)
    # 不抛 TypeError 即通过；masked 位置 NaN
    filled = np.ma.filled(out.astype("float64"), np.nan)
    assert np.isnan(filled[1, 1])
    assert filled[0, 0] == 1.0


def test_colorize_masked_band_uint8_autorange() -> None:
    data = np.arange(100, dtype=np.uint8).reshape(10, 10)
    masked = _mask_invalid_raster(np, data)
    palette = np.array(get_palette_rgb_stops("viridis"), dtype="float32")
    red, green, blue, alpha = _colorize_masked_band(
        np, masked, palette, min_value=None, max_value=None
    )
    assert red.shape == (10, 10)
    assert (alpha == 255).all()
