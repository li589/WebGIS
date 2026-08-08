"""科学栅格网格预设：EASE-Grid 2.0 / WGS84 等常用范围。

EASE-Grid 2.0 Global（EPSG:6933）角点使用 NSIDC 文档给定的对称值，
**禁止**用 ``west + cols * resolution`` 推算 east——浮点累加会越出投影
有效域（约 1e-5 m），导致 6933→WGS84 时东缘经度从 +180° 折到 -180°，
bounds 塌缩为 ``west≈east≈-180``。
"""

from __future__ import annotations

import math
from typing import Any

# NSIDC EASE-Grid 2.0 Global cylindrical equal-area (EPSG:6933) 官方角点
# https://nsidc.org/data/user-resources/help-center/guide-ease-grids
_EASE2_ULX = -17367530.445161516
_EASE2_ULY = 7314540.830865865

# 全球 EASE 投影域在 WGS84 下的地理覆盖（CEA 不到极点）
_EASE2_WGS84_BOUNDS: list[float] = [
    -180.0,
    -85.04456642797585,
    180.0,
    85.04456642797585,
]


def _ease2(res: float, cols: int, rows: int) -> dict[str, Any]:
    """构建 EASE-Grid 2.0 Global 预设（对称角点 + 标称分辨率/行列）。"""
    west = _EASE2_ULX
    north = _EASE2_ULY
    # 对称角点，避免浮点累加越界
    east = -_EASE2_ULX
    south = -_EASE2_ULY
    return {
        "crs": "EPSG:6933",
        "cols": cols,
        "rows": rows,
        "resolution": res,
        "bounds": [west, south, east, north],
        "geographic_bounds": list(_EASE2_WGS84_BOUNDS),
        "origin": "upper-left",
    }


GRID_PRESETS: dict[str, dict[str, Any]] = {
    "wgs84-world": {
        "id": "wgs84-world",
        "label": "WGS84 全球经纬度 (-180~180, -90~90)",
        "crs": "EPSG:4326",
        "cols": None,
        "rows": None,
        "resolution": None,
        "bounds": [-180.0, -90.0, 180.0, 90.0],
        "geographic_bounds": [-180.0, -90.0, 180.0, 90.0],
        "origin": "upper-left",
        "category": "geographic",
    },
    "ease2-global-9km": {
        "id": "ease2-global-9km",
        "label": "EASE-Grid 2.0 全球 9km（1624×3856，SMAP）",
        "category": "ease2",
        **_ease2(9008.05521014913, 3856, 1624),
    },
    "ease2-global-36km": {
        "id": "ease2-global-36km",
        "label": "EASE-Grid 2.0 全球 36km（406×964）",
        "category": "ease2",
        **_ease2(36032.22084059652, 964, 406),
    },
    "ease2-global-25km": {
        "id": "ease2-global-25km",
        "label": "EASE-Grid 2.0 全球 25km（584×1388）",
        "category": "ease2",
        **_ease2(25025.15336152536, 1388, 584),
    },
    "ease2-global-3km": {
        "id": "ease2-global-3km",
        "label": "EASE-Grid 2.0 全球 3km（4872×11568）",
        "category": "ease2",
        **_ease2(3002.68507004971, 11568, 4872),
    },
    "custom": {
        "id": "custom",
        "label": "自定义范围（手动填写 bounds）",
        "crs": "EPSG:4326",
        "cols": None,
        "rows": None,
        "resolution": None,
        "bounds": None,
        "geographic_bounds": None,
        "origin": "upper-left",
        "category": "custom",
    },
}


def list_grid_presets() -> list[dict[str, Any]]:
    return [
        {
            "id": p["id"],
            "label": p["label"],
            "crs": p.get("crs"),
            "cols": p.get("cols"),
            "rows": p.get("rows"),
            "resolution": p.get("resolution"),
            "bounds": p.get("bounds"),
            "geographic_bounds": p.get("geographic_bounds"),
            "category": p.get("category"),
        }
        for p in GRID_PRESETS.values()
    ]


def get_grid_preset(preset_id: str | None) -> dict[str, Any] | None:
    if not preset_id:
        return None
    return GRID_PRESETS.get(preset_id)


def match_grid_preset(
    shape: list[int] | tuple[int, ...] | None,
) -> tuple[str | None, bool]:
    """按二维 shape (rows, cols) 匹配常用网格。

    Returns:
        (preset_id, needs_transpose) — 若 shape 相对预设行列颠倒则为 True。
        MATLAB v7.3/HDF5 常把 ``[rows, cols]`` 存成 ``(cols, rows)``，此时需转置。
    """
    if not shape or len(shape) < 2:
        return None, False
    rows, cols = int(shape[-2]), int(shape[-1])
    for pid, preset in GRID_PRESETS.items():
        if pid == "custom" or preset.get("rows") is None:
            continue
        pr, pc = int(preset["rows"]), int(preset["cols"])
        if pr == rows and pc == cols:
            return pid, False
        if pr == cols and pc == rows:
            return pid, True
    return None, False


def suggest_grid_preset(shape: list[int] | tuple[int, ...] | None) -> str | None:
    """按二维 shape (rows, cols) 匹配常用网格（忽略是否需转置）。"""
    preset_id, _ = match_grid_preset(shape)
    return preset_id


def align_array_to_grid_preset(
    array: Any,
    grid_preset: str | None,
    *,
    axis_order: str = "auto",
) -> tuple[Any, bool]:
    """将二维数组对齐到预设的 (rows, cols)。

    Args:
        axis_order: ``auto`` 按预设检测转置；``transpose`` 强制转置；``as_is`` 保持。

    Returns:
        (aligned_array, did_transpose)
    """
    import numpy as np

    a = np.asarray(array)
    order = (axis_order or "auto").strip().lower()
    if order in {"transpose", "xy_swap", "swap", "t"}:
        return a.T, True
    if order in {"as_is", "none", "keep"}:
        return a, False

    preset = get_grid_preset(grid_preset)
    if a.ndim < 2 or not preset or preset.get("rows") is None:
        return a, False
    height, width = int(a.shape[-2]), int(a.shape[-1])
    rows, cols = int(preset["rows"]), int(preset["cols"])
    if height == rows and width == cols:
        return a, False
    if height == cols and width == rows:
        return a.T, True
    return a, False


def clamp_projected_bounds_to_crs_domain(
    west: float,
    south: float,
    east: float,
    north: float,
    crs_code: str,
) -> tuple[float, float, float, float]:
    """将投影 bounds 钳到 CRS 有效域，避免浮点越界导致经度折返。"""
    if crs_code == "EPSG:6933":
        # 略向内收 1e-6 m，避免刚好落在域边界时 proj 数值抖动
        eps = 1e-6
        xmax = abs(_EASE2_ULX) - eps
        ymax = abs(_EASE2_ULY) - eps
        return (
            max(-xmax, min(xmax, west)),
            max(-ymax, min(ymax, south)),
            max(-xmax, min(xmax, east)),
            max(-ymax, min(ymax, north)),
        )
    return (west, south, east, north)


def normalize_geographic_bounds(
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    source_span_hint: float | None = None,
) -> tuple[float, float, float, float]:
    """规范化 WGS84 bounds：处理日界线折返、浮点溢出与近全球覆盖。

    Args:
        source_span_hint: 源投影东西跨度（米）。若接近 EASE 全球跨度且
            转换后经度塌缩，则恢复为 [-180, 180]。
    """
    if not all(math.isfinite(v) for v in (west, south, east, north)):
        raise ValueError(f"非有限 bounds: {[west, south, east, north]}")

    # 纬度钳位
    south = max(-90.0, min(90.0, south))
    north = max(-90.0, min(90.0, north))
    if south > north:
        south, north = north, south

    # 经度：检测塌缩（浮点越界折到同一侧）
    lon_span = abs(east - west)
    ease_span = 2.0 * abs(_EASE2_ULX)
    looks_global_src = (
        source_span_hint is not None
        and abs(source_span_hint - ease_span) / ease_span < 1e-6
    )
    collapsed = lon_span < 1e-6 or (looks_global_src and lon_span < 1.0)

    if collapsed and (
        looks_global_src or (abs(south + 85.04) < 0.1 and abs(north - 85.04) < 0.1)
    ):
        return (
            -180.0,
            max(south, -85.04456642797585),
            180.0,
            min(north, 85.04456642797585),
        )

    # 将近 ±180 的值吸附，避免 -180.000000000001 之类展示/校验失败
    def _snap_lon(v: float) -> float:
        if abs(v - 180.0) < 1e-9 or abs(v + 180.0) < 1e-9:
            return 180.0 if v > 0 else -180.0
        if v > 180.0:
            # 归一到 (-180, 180]
            v = ((v + 180.0) % 360.0) - 180.0
        if v < -180.0:
            v = ((v + 180.0) % 360.0) - 180.0
        return v

    west = _snap_lon(west)
    east = _snap_lon(east)

    # 近全球：跨度接近 360°
    if abs(abs(east - west) - 360.0) < 1e-6 or (west <= -179.999 and east >= 179.999):
        return (-180.0, south, 180.0, north)

    if west > east:
        # 跨日界线：对 MapLibre image overlay 仍需单段；取较大连续段会丢信息，
        # 全球/准全球场景上面已处理。区域跨日界线保留原值并交换无意义——这里展开为全经度。
        if looks_global_src:
            return (-180.0, south, 180.0, north)
        # 否则保持 west<east 的最小包围（将东界 +360 后再判断跨度）
        if (east + 360.0) - west < 180.0:
            east = east + 360.0
            # 再归一展示：若仍超界，退回全球
            if east > 180.0 and west < -180.0:
                return (-180.0, south, 180.0, north)

    if west >= east:
        raise ValueError(f"规范化后仍无效: west={west}, east={east}")

    return (west, south, east, north)


def resolve_geo_reference(
    *,
    height: int,
    width: int,
    grid_preset: str | None = None,
    source_crs: str | None = None,
    bounds: list[float] | tuple[float, ...] | None = None,
) -> tuple[Any, str, list[float]]:
    """根据预设 / 显式 bounds 计算 Affine transform + CRS + bounds。

    Returns:
        (transform, crs_code, bounds_wsen)
    """
    from rasterio.transform import from_bounds

    preset = get_grid_preset(grid_preset)
    crs = (source_crs or (preset or {}).get("crs") or "EPSG:4326").strip()

    use_bounds: list[float] | None = None
    if bounds is not None and len(bounds) == 4:
        use_bounds = [
            float(bounds[0]),
            float(bounds[1]),
            float(bounds[2]),
            float(bounds[3]),
        ]
    elif preset and preset.get("bounds"):
        use_bounds = [float(x) for x in preset["bounds"]]
        crs = source_crs or preset.get("crs") or crs

    if use_bounds is None:
        from rasterio.transform import from_origin

        return (
            from_origin(0, height, 1, 1),
            crs,
            [0.0, 0.0, float(width), float(height)],
        )

    west, south, east, north = use_bounds
    west, south, east, north = clamp_projected_bounds_to_crs_domain(
        west, south, east, north, crs
    )
    if west >= east or south >= north:
        raise ValueError(f"无效 bounds: [{west}, {south}, {east}, {north}]")
    transform = from_bounds(west, south, east, north, width, height)
    return transform, crs, [west, south, east, north]
