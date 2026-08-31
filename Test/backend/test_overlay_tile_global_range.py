"""瓦片统一归一化基准回归（2026-08-24 三联报障问题 C）。

背景：_apply_palette 在 vmin/vmax=None 时曾按**单个瓦片自身**数据范围归一化
（overlay_tile_service.py 原 :81-94 的 per-tile percentile）——每个瓦片各自
拉伸不同色阶，拼接处数值不连续、接缝可见（用户报障"瓦片之间拼接可见，
细看是数据不连续，以前是正常的"）。

修复：_cached_tile 缺省范围回退 _source_value_range（全源 2/98 百分位，
按 path+band+mtime 缓存）——所有瓦片共享同一归一化基准。

本测试用两块数据分布差异巨大的相邻瓦片验证：修复后两瓦片的输出色阶
基于同一全局范围（相同数据值 → 相同 RGBA 颜色，跨瓦片一致）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.services.overlay_tile_service import (
    _source_value_range,
    render_overlay_tile,
)


def _write_global_tif(path: Path) -> None:
    """全球 GeoTIFF：左半球低值 0-10，右半球高值 90-100（z=1 时两瓦片分布悬殊）。"""
    import rasterio
    from rasterio.transform import from_bounds

    width, height = 720, 360
    data = np.zeros((height, width), dtype="float32")
    data[:, : width // 2] = np.linspace(0, 10, width // 2)[None, :]  # 低值区
    data[:, width // 2 :] = np.linspace(90, 100, width - width // 2)[None, :]  # 高值区
    transform = from_bounds(-180, -85.0511287798066, 180, 85.0511287798066, width, height)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=np.nan,
    ) as dst:
        dst.write(data, 1)


@pytest.fixture()
def global_tif(tmp_path: Path) -> Path:
    src = tmp_path / "global_split.tif"
    _write_global_tif(src)
    return src


def _tile_rgba(source: Path, z: int, x: int, y: int) -> np.ndarray:
    png = render_overlay_tile(str(source), z, x, y, palette="viridis")
    return np.asarray(Image.open(__import__("io").BytesIO(png)).convert("RGBA"))


def test_source_value_range_is_global(global_tif: Path) -> None:
    """全源范围应跨越低/高两个分区（约 1~99），而非单侧。"""
    vmin, vmax = _source_value_range(str(global_tif), 1, global_tif.stat().st_mtime_ns)
    assert vmin is not None and vmax is not None
    assert vmax > 80, f"全源 vmax 应含高值区，实际 {vmin}~{vmax}"
    assert vmin < 20, f"全源 vmin 应含低值区，实际 {vmin}~{vmax}"


def test_adjacent_tiles_share_global_normalization(global_tif: Path) -> None:
    """z=1 相邻两瓦片（低值区/高值区）修复后共享同一归一化基准。

    判据：同一数据值（如各瓦片中心的代表值）在不同瓦片中映射到不同颜色
    （修复前 per-tile 归一化会把两侧都拉伸到全色阶，颜色趋同）；更强判据：
    低值瓦片整体颜色明显暗于高值瓦片（修复后全局归一化的必然结果）。
    """
    _source_value_range.cache_clear()
    _tile_rgba.cache_clear() if hasattr(_tile_rgba, "cache_clear") else None
    from app.services.overlay_tile_service import _cached_tile

    _cached_tile.cache_clear()

    low_tile = _tile_rgba(global_tif, 1, 0, 0)  # 西半球（0-10）
    high_tile = _tile_rgba(global_tif, 1, 1, 0)  # 东半球（90-100）

    def _mean_brightness(rgba: np.ndarray) -> float:
        visible = rgba[..., 3] > 0
        if not visible.any():
            return -1.0
        return float(rgba[visible][:, :3].mean())

    low_b = _mean_brightness(low_tile)
    high_b = _mean_brightness(high_tile)
    assert low_b >= 0 and high_b >= 0, "两瓦片都应有可见像素"
    # viridis 低端暗（紫）高端亮（黄）：全局归一化下低值瓦片显著暗于高值瓦片
    assert high_b - low_b > 30, (
        f"相邻瓦片应共享全局归一化：低值瓦片亮度 {low_b:.1f} 应显著低于"
        f"高值瓦片 {high_b:.1f}（差>30）；若趋同说明回退到 per-tile 归一化"
    )


def test_explicit_min_max_bypasses_global_range(global_tif: Path) -> None:
    """显式 min/max（用户样式）仍按用户值归一化，不被全局范围覆盖。"""
    png = render_overlay_tile(
        str(global_tif), 1, 0, 0, palette="viridis", min_value=0.0, max_value=10.0
    )
    rgba = np.asarray(Image.open(__import__("io").BytesIO(png)).convert("RGBA"))
    assert (rgba[..., 3] > 0).any(), "显式范围内瓦片应有可见像素"


def _write_daily_event_tif(path: Path) -> None:
    """多波段逐日事件源：band1 全 255（nodata），band2 有局部事件 1。"""
    import rasterio
    from rasterio.transform import from_bounds

    width, height = 144, 72
    band1 = np.full((height, width), 255, dtype="uint8")
    band2 = np.full((height, width), 255, dtype="uint8")
    band2[24:48, 72:96] = 1  # 东北象限事件
    transform = from_bounds(-180, -85.0511287798066, 180, 85.0511287798066, width, height)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=2,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
        nodata=255,
    ) as dst:
        dst.write(band1, 1)
        dst.write(band2, 2)


@pytest.fixture()
def daily_event_tif(tmp_path: Path) -> Path:
    src = tmp_path / "daily_event.tif"
    _write_daily_event_tif(src)
    return src


def test_multiband_daily_event_tile_uses_selected_band(daily_event_tif: Path) -> None:
    """ERA5 366 波段源回归：不能用默认 band1（全 255）出全图数据。

    修复：OverlaySpec.source_band 传入瓦片/动态预览；多波段源显式把 255
    识别为 nodata。选中 band2 时瓦片应有局部事件像素，其余透明。
    """
    from app.services.overlay_tile_service import _cached_tile

    _cached_tile.cache_clear()
    png = render_overlay_tile(
        str(daily_event_tif),
        2,
        2,
        1,
        band=2,
        palette="viridis",
        min_value=0.0,
        max_value=2.0,
    )
    rgba = np.asarray(Image.open(__import__("io").BytesIO(png)).convert("RGBA"))
    visible = rgba[..., 3] > 0
    assert visible.any(), "选中事件波段应有可见像素"
    assert visible.mean() < 0.6, "事件像素不应铺满全图（255 必须按 nodata 过滤）"


def test_multiband_daily_event_default_band_filters_nodata(daily_event_tif: Path) -> None:
    """默认 band1 全 255 时必须输出全透明，而不是把 nodata 染成数据。"""
    from app.services.overlay_tile_service import _cached_tile

    _cached_tile.cache_clear()
    png = render_overlay_tile(
        str(daily_event_tif),
        2,
        2,
        1,
        palette="viridis",
        min_value=0.0,
        max_value=2.0,
    )
    rgba = np.asarray(Image.open(__import__("io").BytesIO(png)).convert("RGBA"))
    assert not (rgba[..., 3] > 0).any(), "band1 全 255 应全部按 nodata 透明"
