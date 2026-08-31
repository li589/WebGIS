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

# NSIDC EASE-Grid 2.0 North/South（LAEA，EPSG:6931/6932）官方网格角点：
# UL = (-9,000,000, 9,000,000)，25km 为 720×720，其余分辨率整除 18,000,000 m。
# https://nsidc.org/data/user-resources/help-center/guide-ease-grids
_EASE2_HEMI_UL = -9_000_000.0

# NSIDC EASE-Grid 1.0 North/South 25km（EPSG:3408/3409）：
# 721×721 单元 × 25,067.525 m（球体 R=6,371,228 m 时代分辨率）。
_EASE1_HEMI_RES = 25067.525
_EASE1_HEMI_DIM = 721


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
        "cell_registration": "area",
    }


def _ease2_hemi(crs: str, hemisphere: str, res: float, dim: int) -> dict[str, Any]:
    """构建 EASE-Grid 2.0 半球 LAEA 预设（±9,000,000 网格域，dim×dim）。"""
    span = res * dim
    west = _EASE2_HEMI_UL
    north = -_EASE2_HEMI_UL
    east = west + span
    south = north - span
    geo = (
        [-180.0, 0.0, 180.0, 90.0]
        if hemisphere == "north"
        else [-180.0, -90.0, 180.0, 0.0]
    )
    return {
        "crs": crs,
        "cols": dim,
        "rows": dim,
        "resolution": res,
        "bounds": [west, south, east, north],
        "geographic_bounds": geo,
        "origin": "upper-left",
        "cell_registration": "area",
    }


def _ease1_hemi_25km(crs: str, hemisphere: str) -> dict[str, Any]:
    """构建 EASE-Grid 1.0 半球 25km 预设（721×721，NSIDC 原版球体网格）。"""
    span = _EASE1_HEMI_RES * _EASE1_HEMI_DIM
    west = _EASE2_HEMI_UL
    north = -_EASE2_HEMI_UL
    east = west + span
    south = north - span
    geo = (
        [-180.0, 0.0, 180.0, 90.0]
        if hemisphere == "north"
        else [-180.0, -90.0, 180.0, 0.0]
    )
    return {
        "crs": crs,
        "cols": _EASE1_HEMI_DIM,
        "rows": _EASE1_HEMI_DIM,
        "resolution": _EASE1_HEMI_RES,
        "bounds": [west, south, east, north],
        "geographic_bounds": geo,
        "origin": "upper-left",
        "cell_registration": "area",
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
        "cell_registration": "area",
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
    # ── EASE-Grid 2.0 半球（LAEA，±9,000,000 网格域）─────────────────
    "ease2-north-36km": {
        "id": "ease2-north-36km",
        "label": "EASE-Grid 2.0 北半球 36km（500×500）",
        "category": "ease2",
        **_ease2_hemi("EPSG:6931", "north", 36000.0, 500),
    },
    "ease2-north-25km": {
        "id": "ease2-north-25km",
        "label": "EASE-Grid 2.0 北半球 25km（720×720）",
        "category": "ease2",
        **_ease2_hemi("EPSG:6931", "north", 25000.0, 720),
    },
    "ease2-north-9km": {
        "id": "ease2-north-9km",
        "label": "EASE-Grid 2.0 北半球 9km（2000×2000）",
        "category": "ease2",
        **_ease2_hemi("EPSG:6931", "north", 9000.0, 2000),
    },
    "ease2-north-3km": {
        "id": "ease2-north-3km",
        "label": "EASE-Grid 2.0 北半球 3km（6000×6000）",
        "category": "ease2",
        **_ease2_hemi("EPSG:6931", "north", 3000.0, 6000),
    },
    "ease2-south-36km": {
        "id": "ease2-south-36km",
        "label": "EASE-Grid 2.0 南半球 36km（500×500）",
        "category": "ease2",
        **_ease2_hemi("EPSG:6932", "south", 36000.0, 500),
    },
    "ease2-south-25km": {
        "id": "ease2-south-25km",
        "label": "EASE-Grid 2.0 南半球 25km（720×720）",
        "category": "ease2",
        **_ease2_hemi("EPSG:6932", "south", 25000.0, 720),
    },
    "ease2-south-9km": {
        "id": "ease2-south-9km",
        "label": "EASE-Grid 2.0 南半球 9km（2000×2000）",
        "category": "ease2",
        **_ease2_hemi("EPSG:6932", "south", 9000.0, 2000),
    },
    "ease2-south-3km": {
        "id": "ease2-south-3km",
        "label": "EASE-Grid 2.0 南半球 3km（6000×6000）",
        "category": "ease2",
        **_ease2_hemi("EPSG:6932", "south", 3000.0, 6000),
    },
    # ── EASE-Grid 1.0（NSIDC 原版球体网格）─────────────────────────
    "ease1-north-25km": {
        "id": "ease1-north-25km",
        "label": "EASE-Grid 1.0 北半球 25km（721×721，球体）",
        "category": "ease1",
        **_ease1_hemi_25km("EPSG:3408", "north"),
    },
    "ease1-south-25km": {
        "id": "ease1-south-25km",
        "label": "EASE-Grid 1.0 南半球 25km（721×721，球体）",
        "category": "ease1",
        **_ease1_hemi_25km("EPSG:3409", "south"),
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


# ── EASE 网格上左角（UL）权威表（2026-08-24 自 Tools/export_overlay_assets.py 下沉）──
# 同一 CRS 各分辨率共享角点（500m 基准网格对齐）。
# 出处：NSIDC EASE-Grid 2.0 https://nsidc.org/data/ease/ease_grid2.html
# 半球 LAEA（6931/6932）官方角点 (-9,000,000, 9,000,000)；
# EASE-Grid 1.0（3408/3409/3410）为球体 R=6371228 网格，角点不可与 2.0 混用：
#   - 1.0 半球 25km：721×721 × 25067.525 m，UL 同 (-9,000,000, 9,000,000)
#   - 1.0 全球：x ∈ ±17,334,194（lon=±180），y 由分辨率对齐（约 ±7,356,861）
# 消费方（overlay_recolor / overlay_registry / Tools 导出脚本）一律引用本表，
# 禁止再各自硬编码 EASE 常数。
EASE_UL_BY_CRS: dict[str, tuple[float, float]] = {
    "EPSG:6933": (_EASE2_ULX, _EASE2_ULY),
    "EPSG:6931": (_EASE2_HEMI_UL, -_EASE2_HEMI_UL),
    "EPSG:6932": (_EASE2_HEMI_UL, -_EASE2_HEMI_UL),
    "EPSG:3408": (_EASE2_HEMI_UL, -_EASE2_HEMI_UL),
    "EPSG:3409": (_EASE2_HEMI_UL, -_EASE2_HEMI_UL),
    "EPSG:3410": (-17334193.94, 7356860.29),
}

# 像元配准语义（PixelIsArea / PixelIsPoint，GDAL AREA_OR_POINT 约定）：
# - "area"：坐标/transform 描述像元**边缘**（rasterio from_bounds/from_origin 默认）；
# - "point"：坐标为像元**中心**（CF 坐标变量约定、SMAP L3/GLDAS 等格点产品），
#   转 area 需在四边外扩半步长（见 cell_registration.coords_to_area_bounds）。
CELL_REGISTRATION_AREA = "area"
CELL_REGISTRATION_POINT = "point"


def ease_grid_transform(src_crs: str, resolution_m: float) -> Any:
    """按 (CRS, 分辨率) 返回 EASE-Grid 仿射变换（rasterio 约定，north-up）。

    覆盖 EASE-Grid 2.0 全球（6933）与半球 LAEA（6931/6932），以及 NSIDC
    EASE-Grid 1.0（3408/3409/3410，球体 R=6371228）。角点查
    :data:`EASE_UL_BY_CRS`；1.0 与 2.0 角点不同，不可混用。
    """
    from rasterio.transform import from_origin

    ul = EASE_UL_BY_CRS.get(src_crs)
    if ul is None:
        raise ValueError(
            f"No EASE-Grid preset for {src_crs}; known: {sorted(EASE_UL_BY_CRS)}"
        )
    return from_origin(ul[0], ul[1], resolution_m, resolution_m)


def ease_grid_from_shape(
    shape: list[int] | tuple[int, ...] | None,
) -> tuple[str, str, Any] | None:
    """按二维 shape 匹配任意 EASE 网格 preset 并构建其 Affine 变换。

    与 :func:`match_grid_preset` 同源匹配（含转置检测——转置只影响数组
    对齐方式，不改变网格几何），但只接受 EASE（ease1/ease2）类别，
    返回可直接喂给 ``grid_reproject.reproject_to_mercator_linear`` 的三元组。

    Returns:
        (preset_id, crs, src_transform) — 非 EASE 形状返回 None。
    """
    preset_id, _ = match_grid_preset(shape)
    if not preset_id:
        return None
    preset = GRID_PRESETS.get(preset_id)
    if not preset or preset.get("category") not in {"ease1", "ease2"}:
        return None
    west, _south, _east, north = preset["bounds"]
    res = float(preset["resolution"])
    from rasterio.transform import from_origin

    return (
        preset_id,
        str(preset["crs"]),
        from_origin(west, north, res, res),
    )


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
            "cell_registration": p.get("cell_registration"),
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


# 投影域钳位表（值经 pyproj 边界采样核验）：
# - 6933：NSIDC 2.0 Global CEA 官方角点
# - 6931/6932：赤道边界 |x|,|y| ≈ 9,009,965，取整 9,010,000
# - 3408/3409：1.0 球体 LAEA 网格东南角 ≈ 9,073,689.5（25km 721×721 角点）
# - 3410：1.0 球体 CEA，lon=±180 → x ≈ 17,334,194；lat→±90 → y ≈ 7,356,861
_PROJECTED_DOMAIN_BY_CRS: dict[str, tuple[float, float]] = {
    "EPSG:6933": (abs(_EASE2_ULX), abs(_EASE2_ULY)),
    "EPSG:6931": (9_010_000.0, 9_010_000.0),
    "EPSG:6932": (9_010_000.0, 9_010_000.0),
    "EPSG:3408": (9_073_690.0, 9_073_690.0),
    "EPSG:3409": (9_073_690.0, 9_073_690.0),
    "EPSG:3410": (17_334_194.0, 7_356_861.0),
}


def clamp_projected_bounds_to_crs_domain(
    west: float,
    south: float,
    east: float,
    north: float,
    crs_code: str,
) -> tuple[float, float, float, float]:
    """将投影 bounds 钳到 CRS 有效域，避免浮点越界导致经度折返。"""
    domain = _PROJECTED_DOMAIN_BY_CRS.get(crs_code)
    if domain is None:
        return (west, south, east, north)
    # 略向内收 1e-6 m，避免刚好落在域边界时 proj 数值抖动
    eps = 1e-6
    xmax, ymax = domain[0] - eps, domain[1] - eps
    return (
        max(-xmax, min(xmax, west)),
        max(-ymax, min(ymax, south)),
        max(-xmax, min(xmax, east)),
        max(-ymax, min(ymax, north)),
    )


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
