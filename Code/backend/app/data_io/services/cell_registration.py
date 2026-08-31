"""像元配准（PixelIsArea / PixelIsPoint）归一化。

2026-08-24 架构审查 P1.5：全仓此前零 AREA_OR_POINT 处理——栅格内部链路
（preset/from_bounds）隐式 PixelIsArea，GRIB bounds 隐式 PixelIsPoint（无条件
外扩半格），MAT bounds 则直接 min/max（无外扩）——同一"坐标向量 → bounds"
问题三种隐式假设。本模块把该判定收敛为一处：

- 判定规则（结合坐标向量长度与数据维度）：
  - ``len(coord) == data_size + 1`` → **area**（坐标为像元边缘，N 个像元
    N+1 条边；bounds 即 min/max，不再外扩）；
  - ``len(coord) == data_size`` → **point**（CF 坐标变量约定：坐标为像元
    中心；bounds 四边各外扩半步长）；
  - 其他（无法对齐维度）→ **unknown**：按调用方指定的默认假设处理。
- 无数据维度信息时默认 **point**（CF/netCDF 坐标变量几乎总为中心坐标；
  GRIB/MAT 经验同）。
- 内部 preset 几何（grid_presets）恒为 area（from_bounds/from_origin 语义）。

下游统一写 ``cell_registration`` 元数据字段传递（bounds.json / import meta），
导出 GeoTIFF 时可映射为 GDAL ``AREA_OR_POINT``。
"""

from __future__ import annotations

from typing import Any

import numpy as np

CELL_REGISTRATION_AREA = "area"
CELL_REGISTRATION_POINT = "point"
CELL_REGISTRATION_UNKNOWN = "unknown"


def infer_cell_registration(coord_size: int, data_size: int | None) -> str:
    """按坐标向量长度 vs 数据维度推断像元配准。

    Args:
        coord_size: 坐标向量长度。
        data_size: 对应数据维度长度（None 时无法判定，返回 unknown）。

    Returns:
        "area"（N+1 边缘坐标）| "point"（N 中心坐标）| "unknown"。
    """
    if data_size is None or data_size < 1:
        return CELL_REGISTRATION_UNKNOWN
    if coord_size == data_size + 1:
        return CELL_REGISTRATION_AREA
    if coord_size == data_size:
        return CELL_REGISTRATION_POINT
    return CELL_REGISTRATION_UNKNOWN


def coords_to_area_bounds(
    lat: Any,
    lon: Any,
    data_shape: tuple[int, ...] | list[int] | None = None,
    *,
    default_registration: str = CELL_REGISTRATION_POINT,
) -> tuple[list[float], str] | None:
    """把（可能为中心坐标的）lat/lon 向量归一化为 PixelIsArea bounds。

    Args:
        lat / lon: 一维坐标向量（可乱序/降序，自动排序）。
        data_shape: 数据二维形状 (rows, cols)；提供时按维度精确判定
            area/point，否则按 ``default_registration`` 假设。
        default_registration: 维度无法判定时的假设（默认 point——CF 坐标
            变量约定；GRIB/MAT 经验一致）。

    Returns:
        ([west, south, east, north], registration) — 归一化后的像元边缘
        bounds 与所用配准判定；坐标无效（<2 点、非有限、跨 ±90/±180）
        返回 None。
    """
    try:
        lat_arr = np.atleast_1d(np.asarray(lat, dtype=np.float64))
        lon_arr = np.atleast_1d(np.asarray(lon, dtype=np.float64))
    except Exception:
        return None
    if lat_arr.size < 2 or lon_arr.size < 2:
        return None
    if not (np.isfinite(lat_arr).all() and np.isfinite(lon_arr).all()):
        return None

    lat_sorted = np.sort(lat_arr)
    lon_sorted = np.sort(lon_arr)
    south, north = float(lat_sorted[0]), float(lat_sorted[-1])
    west, east = float(lon_sorted[0]), float(lon_sorted[-1])

    # 步长：中位数抗个别异常间距（近均匀网格）
    dlat = (
        float(np.median(np.abs(np.diff(lat_sorted))))
        if lat_sorted.size > 1
        else 0.0
    )
    dlon = (
        float(np.median(np.abs(np.diff(lon_sorted))))
        if lon_sorted.size > 1
        else 0.0
    )

    registration = CELL_REGISTRATION_UNKNOWN
    if data_shape is not None and len(data_shape) >= 2:
        registration = infer_cell_registration(lat_arr.size, int(data_shape[-2]))
        lon_reg = infer_cell_registration(lon_arr.size, int(data_shape[-1]))
        # 经纬判定不一致时（罕见）取保守 point（外扩半格）
        if registration != lon_reg:
            registration = CELL_REGISTRATION_POINT
    if registration == CELL_REGISTRATION_UNKNOWN:
        registration = default_registration

    if registration == CELL_REGISTRATION_AREA:
        # 坐标即像元边缘：min/max 即 bounds
        pass
    else:
        # point：像元中心 → 四边各外扩半步长
        south -= dlat / 2.0
        north += dlat / 2.0
        west -= dlon / 2.0
        east += dlon / 2.0

    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        return None
    return [west, south, east, north], registration
