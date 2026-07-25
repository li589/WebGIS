"""浮点安全的地理/数值工具（bounds、经度展开、网格尺寸）。

用于避免：
- 投影域浮点越界导致经度 ±180 折返塌缩
- 日界线两侧算术平均得到错误中点
- ``int(span/res)`` 截断丢掉整行/列
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence


def is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def require_finite(*values: float, label: str = "value") -> None:
    for v in values:
        if not math.isfinite(v):
            raise ValueError(f"{label} 含非有限值: {values!r}")


def wrap_longitude(lng: float) -> float:
    """将经度归一到 (-180, 180]。"""
    if not math.isfinite(lng):
        return lng
    x = ((lng + 180.0) % 360.0 + 360.0) % 360.0 - 180.0
    if abs(x + 180.0) < 1e-15:
        return 180.0 if lng > 0 else -180.0
    return x


def unwrap_delta_longitude(lng1: float, lng2: float) -> float:
    """从 lng1 到 lng2 的最短经度差，范围 (-180, 180]。"""
    return ((lng2 - lng1 + 180.0) % 360.0) - 180.0


def geographic_midpoint(
    lng1: float, lat1: float, lng2: float, lat2: float
) -> tuple[float, float]:
    """球面近似中点（经度展开），避免跨日界线时落到本初子午线。"""
    require_finite(lng1, lat1, lng2, lat2, label="midpoint")
    dlon = unwrap_delta_longitude(lng1, lng2)
    return wrap_longitude(lng1 + 0.5 * dlon), (lat1 + lat2) * 0.5


def normalize_lng_lat_bbox(
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    allow_dateline_unwrap: bool = True,
) -> tuple[float, float, float, float]:
    """规范化地理 bbox：有限性、纬度钳位、日界线（east 可 >180 以保持 west<east）。"""
    require_finite(west, south, east, north, label="bbox")
    south = max(-90.0, min(90.0, south))
    north = max(-90.0, min(90.0, north))
    if south > north:
        south, north = north, south

    # 已是 west<east 的常规情况
    if west < east and east - west <= 360.0:
        if east - west >= 359.999:
            return -180.0, south, 180.0, north
        return west, south, east, north

    if allow_dateline_unwrap and west > east:
        # 跨日界线：把 east 推到 (180, 360] 区间以保持 west < east
        east_unwrapped = east + 360.0
        if east_unwrapped - west >= 359.999:
            return -180.0, south, 180.0, north
        return west, south, east_unwrapped, north

    if west == east:
        # 零宽度：扩一点避免 from_bounds/fit 失败
        pad = 1e-6
        return west - pad, south, east + pad, north

    raise ValueError(f"无法规范化 bbox: {[west, south, east, north]}")


def lng_span_from_list(lngs: Iterable[float]) -> tuple[float, float] | None:
    """相对展开后取经度包围 [west, east]（east 可能 >180）。"""
    finite = [float(x) for x in lngs if is_finite_number(x)]
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
    """由跨度/分辨率计算网格数：四舍五入，至少 1，拒绝非正分辨率。"""
    if not math.isfinite(span) or not math.isfinite(resolution):
        raise ValueError(f"非有限 span/resolution: {span}, {resolution}")
    if resolution <= 0:
        raise ValueError(f"resolution 必须 > 0，收到 {resolution}")
    n = int(round(abs(span) / resolution))
    return max(1, n)


def pixel_center_axis(
    start: float,
    stop: float,
    count: int,
    *,
    descending: bool = False,
) -> list[float]:
    """边缘对齐网格的像素中心坐标（与 ``from_bounds`` Affine 一致）。

    ``start/stop`` 为外边缘；中心为 ``start + (i+0.5)*res``。
    """
    if count < 1:
        raise ValueError("count 必须 >= 1")
    require_finite(start, stop, label="axis")
    res = (stop - start) / count
    if descending:
        # start=north, stop=south, res 为负
        return [start + (i + 0.5) * res for i in range(count)]
    return [start + (i + 0.5) * res for i in range(count)]


def nearly_equal(a: float, b: float, *, atol: float = 1e-9, rtol: float = 1e-9) -> bool:
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    return abs(a - b) <= max(atol, rtol * max(abs(a), abs(b)))


def overlay_safe_wgs84_bounds(
    west: float,
    south: float,
    east: float,
    north: float,
) -> tuple[float, float, float, float]:
    """供 MapLibre image overlay 使用的 WGS84 bounds。

    - 近全球 → 严格 ``[-180, s, 180, n]``
    - 跨日界线区域 → ``east`` 可落到 ``(180, 360]`` 且保持 ``west < east``
      （与天气引擎约定一致；前端 validateOverlayBounds 需同步接受）
    - 常规区域 → ``east <= 180``
    """
    w, s, e, n = normalize_lng_lat_bbox(
        west, south, east, north, allow_dateline_unwrap=True
    )
    span = e - w
    if span >= 359.999 or (w <= -179.999 and e >= 179.999):
        return -180.0, s, 180.0, n
    if e > 180.0 and span > 180.0:
        # 展开后跨度过大，当作全球
        return -180.0, s, 180.0, n
    return w, s, e, n


def filter_finite_pairs(
    pairs: Iterable[Sequence[float]],
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in pairs:
        if len(p) < 2:
            continue
        x, y = float(p[0]), float(p[1])
        if math.isfinite(x) and math.isfinite(y):
            out.append((x, y))
    return out
