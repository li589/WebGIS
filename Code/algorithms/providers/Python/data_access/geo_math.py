"""算法侧浮点安全网格工具（与 backend ``app.services.geo_math`` 语义对齐）。

避免 ``int(span/res)`` 截断丢行/列，以及 ``linspace`` 边点与 ``from_bounds``
像素中心不一致。
"""

from __future__ import annotations

import math


def lng_span_from_list(lngs: list[float]) -> tuple[float, float] | None:
    """相对展开后取经度包围 [west, east]（east 可能 >180）。"""
    finite = [float(x) for x in lngs if math.isfinite(float(x))]
    if not finite:
        return None
    unwrapped = [finite[0]]
    for lon0 in finite[1:]:
        lon = lon0
        prev = unwrapped[-1]
        while lon - prev > 180.0:
            lon -= 360.0
        while lon - prev < -180.0:
            lon += 360.0
        unwrapped.append(lon)
    west = min(unwrapped)
    east = max(unwrapped)
    if east - west >= 359.999:
        return -180.0, 180.0
    return west, east


def grid_size_from_span(span: float, resolution: float) -> int:
    if not math.isfinite(span) or not math.isfinite(resolution):
        raise ValueError(f"非有限 span/resolution: {span}, {resolution}")
    if resolution <= 0:
        raise ValueError(f"resolution 必须 > 0，收到 {resolution}")
    return max(1, int(round(abs(span) / resolution)))


def pixel_center_axis(
    start: float,
    stop: float,
    count: int,
) -> list[float]:
    """边缘对齐网格的像素中心（与 rasterio ``from_bounds`` Affine 一致）。"""
    if count < 1:
        raise ValueError("count 必须 >= 1")
    if not (math.isfinite(start) and math.isfinite(stop)):
        raise ValueError(f"非有限 axis: {start}, {stop}")
    res = (stop - start) / count
    return [start + (i + 0.5) * res for i in range(count)]
