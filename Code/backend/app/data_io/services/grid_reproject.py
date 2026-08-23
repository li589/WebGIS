"""EASE / 任意投影栅格 → Web Mercator 线性网格共享重投影。

2026-08-24 自 Tools/export_overlay_assets.py::_reproject_to_mercator_linear 与
app/services/overlay_recolor.py::_reproject_ease_to_mercator_linear 两份重复
实现下沉合并（架构审查 P2）。

设计约束：
- **纯依赖模块**（仅 numpy / rasterio / pyproj），不 import 任何 ``app.*``
  内部模块——以便 Tools 独立脚本通过 ``importlib.util.spec_from_file_location``
  直接加载复用（避免触发 app 包初始化链）。
- 源几何（transform/crs/preset）由调用方提供；EASE preset 匹配见
  :func:`app.data_io.services.grid_presets.ease_grid_from_shape`。
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Web Mercator（EPSG:3857）纬度极限：MapLibre ImageSource 四角无法表示 ±90°，
# 超出即渲染失败 —— 因此重投影目标统一用 ±85.0511° 全幅。
MERCATOR_MAX_LAT = 85.0511287798066
MERCATOR_MAX_Y = 20037508.342789244
METERS_PER_DEGREE_EQUATOR = 111319.49079327358


def reproject_to_mercator_linear(
    data: Any,
    src_transform: Any,
    src_crs: str,
    target_resolution: float = 0.25,
    clip_bounds: tuple[float, float, float, float] | None = None,
    resampling: str = "nearest",
) -> tuple[Any, tuple[float, float, float, float]]:
    """重投影任意投影栅格到 Web Mercator 线性网格（行/列在 3857 平面均匀）。

    为什么目标不是等经纬（EPSG:4326）：MapLibre ``ImageSource`` 以 4 角坐标
    在 Mercator 平面做双线性插值渲染。等经纬图像的行按纬度均匀分布，而
    Mercator y 对纬度非线性 → 中高纬渲染偏移可达十几度；±90° 角点甚至
    无法表示。把行重采样为 Mercator y 均匀后，四角线性插值即地理精确，
    南北极边界自动收敛到 ±85.0511°（Mercator 全幅）。

    Args:
        data: (n_lat, n_lon) 2D 源数组。
        src_transform / src_crs: 源栅格仿射变换与 CRS。
        target_resolution: 输出分辨率（度，赤道处；1 度 = 111319.49 米）。
        clip_bounds: (west, south, east, north) WGS84 裁剪窗口；
            None = 全球全幅（-180 ~ 180, ±85.0511）。
        resampling: ``"nearest"``（分类数据/预览）或 ``"bilinear"``（连续量）。

    Returns:
        (out_data, (west, south, east, north)) — bounds 为角点精确反算的经纬度。
    """
    from pyproj import Transformer
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.warp import reproject

    res_m = target_resolution * METERS_PER_DEGREE_EQUATOR
    if clip_bounds is None:
        west_m = south_m = -MERCATOR_MAX_Y
        east_m = north_m = MERCATOR_MAX_Y
    else:
        west, south, east, north = clip_bounds
        fwd = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        west_m, south_m = fwd.transform(west, max(south, -MERCATOR_MAX_LAT))
        east_m, north_m = fwd.transform(east, min(north, MERCATOR_MAX_LAT))

    width = max(1, int(round((east_m - west_m) / res_m)))
    height = max(1, int(round((north_m - south_m) / res_m)))
    dst_transform = from_origin(west_m, north_m, res_m, res_m)

    dst_data = np.full((height, width), np.nan, dtype=np.float64)
    reproject(
        source=data,
        destination=dst_data,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs="EPSG:3857",
        resampling=(
            Resampling.bilinear
            if resampling == "bilinear"
            else Resampling.nearest  # 分类数据最近邻；连续量可传 "bilinear"
        ),
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )

    inv = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    w, s = inv.transform(west_m, south_m)
    e, n = inv.transform(east_m, north_m)
    return dst_data, (float(w), float(s), float(e), float(n))
