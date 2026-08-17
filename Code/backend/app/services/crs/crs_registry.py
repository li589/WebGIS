"""CRS 注册表 — 声明式目录 + 动态投影带生成。

Phase 2 已实现：
- 全 UTM 系列（EPSG:32601-32660 北半球、32701-32760 南半球）动态生成
- 全 Gauss-Krüger 3 度带（EPSG:4513-4533 CGCS2000）动态生成
- Web Mercator (EPSG:3857) bounds 启发式识别

Featured CRS（13 项静态定义）保留为前端下拉的精简集；
动态生成的投影带通过 ``get_crs()`` 可查、通过 ``to_api_payload_expanded()``
返回完整列表供高级用户选择。
"""

from __future__ import annotations

from typing import Any

from .crs_types import CRSCategory, CRSDef

# ── Phase 1 CRS 目录（13 项）─────────────────────────────────────────
_CRS_DEFS: list[CRSDef] = [
    # ── 地理坐标系 ──────────────────────────────────────────────────
    CRSDef(
        code="EPSG:4326",
        label="WGS84 经纬度",
        category=CRSCategory.GEOGRAPHIC,
        epsg=4326,
        proj4_def="+proj=longlat +datum=WGS84 +no_defs",
        area="Global",
    ),
    CRSDef(
        code="EPSG:4490",
        label="CGCS2000 国家大地坐标系",
        category=CRSCategory.GEOGRAPHIC,
        epsg=4490,
        proj4_def="+proj=longlat +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +no_defs",
        area="China",
    ),
    CRSDef(
        code="EPSG:4258",
        label="ETRS89 欧洲地理坐标系",
        category=CRSCategory.GEOGRAPHIC,
        epsg=4258,
        proj4_def="+proj=longlat +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +no_defs",
        area="Europe",
    ),
    # ── 加密坐标系（非 EPSG）──────────────────────────────────────
    CRSDef(
        code="GCJ02",
        label="GCJ-02 火星坐标系（国测局加密）",
        category=CRSCategory.ENCRYPTED,
        epsg=None,
        proj4_def=None,
        area="China",
    ),
    CRSDef(
        code="BD09",
        label="BD-09 百度坐标系",
        category=CRSCategory.ENCRYPTED,
        epsg=None,
        proj4_def=None,
        area="China",
    ),
    # ── 投影坐标系 ──────────────────────────────────────────────────
    CRSDef(
        code="EPSG:3857",
        label="Web Mercator（伪墨卡托）",
        category=CRSCategory.PROJECTED,
        epsg=3857,
        proj4_def="+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +k=1 +units=m +nadgrids=@null +wktext +no_defs",
        area="Global",
    ),
    CRSDef(
        code="EPSG:6933",
        label="EASE-Grid 2.0 全球等积圆柱投影",
        category=CRSCategory.PROJECTED,
        epsg=6933,
        proj4_def="+proj=cea +lon_0=0 +lat_ts=30 +x_0=0 +y_0=0 +ellps=WGS84 +datum=WGS84 +units=m +no_defs",
        area="Global",
    ),
    # ── EASE-Grid 家族扩展（proj4 串取自 pyproj CRS.from_epsg().to_proj4()）──
    # EASE-Grid 2.0 为 WGS84 椭球；EASE-Grid 1.0（NSIDC 原版）为球体 R=6371228。
    CRSDef(
        code="EPSG:6931",
        label="EASE-Grid 2.0 北半球（LAEA）",
        category=CRSCategory.PROJECTED,
        epsg=6931,
        proj4_def="+proj=laea +lat_0=90 +lon_0=0 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs +type=crs",
        area="North",
    ),
    CRSDef(
        code="EPSG:6932",
        label="EASE-Grid 2.0 南半球（LAEA）",
        category=CRSCategory.PROJECTED,
        epsg=6932,
        proj4_def="+proj=laea +lat_0=-90 +lon_0=0 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs +type=crs",
        area="South",
    ),
    CRSDef(
        code="EPSG:3408",
        label="NSIDC EASE-Grid 1.0 北半球（LAEA，球体）",
        category=CRSCategory.PROJECTED,
        epsg=3408,
        proj4_def="+proj=laea +lat_0=90 +lon_0=0 +x_0=0 +y_0=0 +R=6371228 +units=m +no_defs +type=crs",
        area="North",
    ),
    CRSDef(
        code="EPSG:3409",
        label="NSIDC EASE-Grid 1.0 南半球（LAEA，球体）",
        category=CRSCategory.PROJECTED,
        epsg=3409,
        proj4_def="+proj=laea +lat_0=-90 +lon_0=0 +x_0=0 +y_0=0 +R=6371228 +units=m +no_defs +type=crs",
        area="South",
    ),
    CRSDef(
        code="EPSG:3410",
        label="NSIDC EASE-Grid 1.0 全球（等积圆柱，球体）",
        category=CRSCategory.PROJECTED,
        epsg=3410,
        proj4_def="+proj=cea +lat_ts=30 +lon_0=0 +x_0=0 +y_0=0 +R=6371228 +units=m +no_defs +type=crs",
        area="Global",
    ),
    CRSDef(
        code="EPSG:32649",
        label="UTM Zone 49N（通用横轴墨卡托 49 带 北半球）",
        category=CRSCategory.PROJECTED,
        epsg=32649,
        proj4_def="+proj=utm +zone=49 +datum=WGS84 +units=m +no_defs",
        area="China",
    ),
    CRSDef(
        code="EPSG:32650",
        label="UTM Zone 50N（通用横轴墨卡托 50 带 北半球）",
        category=CRSCategory.PROJECTED,
        epsg=32650,
        proj4_def="+proj=utm +zone=50 +datum=WGS84 +units=m +no_defs",
        area="China",
    ),
    # ── 高斯-克吕格（CGCS2000 3 度带）──────────────────────────────
    CRSDef(
        code="EPSG:4527",
        label="CGCS2000 / 3度带 高斯-克吕格 zone 39（北京，CM 117E）",
        category=CRSCategory.PROJECTED,
        epsg=4527,
        proj4_def="+proj=tmerc +lat_0=0 +lon_0=117 +k=1 +x_0=39500000 +y_0=0 +ellps=GRS80 +units=m +no_defs",
        area="China",
    ),
    CRSDef(
        code="EPSG:4528",
        label="CGCS2000 / 3度带 高斯-克吕格 zone 40（上海，CM 120E）",
        category=CRSCategory.PROJECTED,
        epsg=4528,
        proj4_def="+proj=tmerc +lat_0=0 +lon_0=120 +k=1 +x_0=40500000 +y_0=0 +ellps=GRS80 +units=m +no_defs",
        area="China",
    ),
    CRSDef(
        code="EPSG:4529",
        label="CGCS2000 / 3度带 高斯-克吕格 zone 41（东北，CM 123E）",
        category=CRSCategory.PROJECTED,
        epsg=4529,
        proj4_def="+proj=tmerc +lat_0=0 +lon_0=123 +k=1 +x_0=41500000 +y_0=0 +ellps=GRS80 +units=m +no_defs",
        area="China",
    ),
    # ── 兰伯特等角圆锥投影（欧洲）──────────────────────────────────
    # 注意：EPSG:3035 实际是 LAEA（兰伯特方位等积），非 LCC。
    # 用户需求是"兰伯特等角圆锥"（Lambert Conformal Conic），
    # 对应的欧洲 CRS 是 EPSG:3034 (ETRS89 / LCC Europe)。
    CRSDef(
        code="EPSG:3034",
        label="ETRS89 / LCC Europe（欧洲兰伯特等角圆锥）",
        category=CRSCategory.PROJECTED,
        epsg=3034,
        proj4_def="+proj=lcc +lat_1=35 +lat_2=65 +lat_0=52 +lon_0=10 +x_0=4000000 +y_0=2800000 +ellps=GRS80 +units=m +no_defs",
        area="Europe",
    ),
]

# ── 动态投影带生成（Phase 2）─────────────────────────────────────────


def _generate_utm_zones() -> list[CRSDef]:
    """动态生成全 UTM 带（北半球 32601-32660，南半球 32701-32760）。

    UTM 带号 1-60，每带跨经度 6°，从 180°W 开始。
    北半球 EPSG:326xx，南半球 EPSG:327xx。
    跳过已在静态定义中的 32649/32650（避免重复，保留其定制标签）。
    """
    featured = {c.code for c in _CRS_DEFS}
    zones: list[CRSDef] = []
    for zone in range(1, 61):
        for hemisphere, epsg_prefix, label_prefix in (
            ("N", 32600, "北半球"),
            ("S", 32700, "南半球"),
        ):
            code = f"EPSG:{epsg_prefix + zone}"
            if code in featured:
                continue
            central_meridian = -180 + zone * 6 - 3
            zones.append(
                CRSDef(
                    code=code,
                    label=f"UTM Zone {zone}{hemisphere}（CM {central_meridian}°E）",
                    category=CRSCategory.PROJECTED,
                    epsg=epsg_prefix + zone,
                    proj4_def=(
                        f"+proj=utm +zone={zone} +datum=WGS84 +units=m +no_defs"
                    ),
                    area="Global",
                )
            )
    return zones


def _generate_gk_3deg_zones() -> list[CRSDef]:
    """动态生成全 CGCS2000 高斯-克吕格 3 度带（EPSG:4513-4533）。

    3 度带 zone 25-45，覆盖中央子午线 75°E-135°E（中国全域）。
    EPSG:4513 = zone 25 (CM 75°E) ... EPSG:4533 = zone 45 (CM 135°E)。
    false_easting = zone × 1000000 + 500000。
    跳过已在静态定义中的 4527/4528/4529（保留定制标签）。
    """
    featured = {c.code for c in _CRS_DEFS}
    zones: list[CRSDef] = []
    for zone in range(25, 46):
        code = f"EPSG:{4513 + (zone - 25)}"
        if code in featured:
            continue
        central_meridian = zone * 3  # zone 25 → 75°E, zone 45 → 135°E
        false_easting = zone * 1_000_000 + 500_000
        zones.append(
            CRSDef(
                code=code,
                label=(
                    f"CGCS2000 / 3度带 GK zone {zone}" f"（CM {central_meridian}°E）"
                ),
                category=CRSCategory.PROJECTED,
                epsg=4513 + (zone - 25),
                proj4_def=(
                    f"+proj=tmerc +lat_0=0 +lon_0={central_meridian} "
                    f"+k=1 +x_0={false_easting} +y_0=0 "
                    f"+ellps=GRS80 +units=m +no_defs"
                ),
                area="China",
            )
        )
    return zones


# 动态生成的投影带
_DYNAMIC_CRS: list[CRSDef] = _generate_utm_zones() + _generate_gk_3deg_zones()

# 按 code 索引的不可变字典（静态 + 动态）
CRS_REGISTRY: dict[str, CRSDef] = {c.code: c for c in (_CRS_DEFS + _DYNAMIC_CRS)}

# 静态 featured CRS 的 code 集合（用于区分精简列表与完整列表）
_FEATURED_CODES: frozenset[str] = frozenset(c.code for c in _CRS_DEFS)


def get_crs(code: str) -> CRSDef | None:
    """按 code 获取 CRSDef。未注册返回 None。

    兼容旧码连字符写法：``'GCJ-02'`` / ``'BD-09'`` 自动映射为
    ``'GCJ02'`` / ``'BD09'``。
    """
    if not code:
        return None
    normalized = _normalize_legacy_code(code)
    return CRS_REGISTRY.get(normalized)


def list_crs(
    category: CRSCategory | None = None,
    *,
    featured_only: bool = False,
) -> list[CRSDef]:
    """列出所有（或指定大类）已注册 CRS。

    Args:
        category: 可选大类过滤
        featured_only: True 时仅返回 13 项精简集（前端下拉用）；
            False 时返回全部（含动态 UTM/GK 带）。
    """
    source = _CRS_DEFS if featured_only else (_CRS_DEFS + _DYNAMIC_CRS)
    if category is None:
        return list(source)
    return [c for c in source if c.category == category]


def to_api_payload() -> list[dict[str, Any]]:
    """序列化为前端下拉用 payload（精简集，13 项 featured CRS）。

    Returns:
        ``[{code, label, category, area, deprecated}, ...]``
    """
    return [
        {
            "code": c.code,
            "label": c.label,
            "category": c.category.value,
            "area": c.area,
            "deprecated": c.deprecated,
        }
        for c in _CRS_DEFS
    ]


def to_api_payload_expanded() -> list[dict[str, Any]]:
    """序列化为完整 CRS 列表（含动态 UTM/GK 带，供高级选择）。

    动态项额外携带 ``featured: False`` 标记，前端可折叠展示。
    """
    result: list[dict[str, Any]] = [
        {
            "code": c.code,
            "label": c.label,
            "category": c.category.value,
            "area": c.area,
            "deprecated": c.deprecated,
            "featured": True,
        }
        for c in _CRS_DEFS
    ]
    result.extend(
        {
            "code": c.code,
            "label": c.label,
            "category": c.category.value,
            "area": c.area,
            "deprecated": c.deprecated,
            "featured": False,
        }
        for c in _DYNAMIC_CRS
    )
    return result


def suggest_utm_zone(lng: float, lat: float) -> str:
    """根据经纬度推断最合适的 UTM 带 EPSG code。

    UTM 带号 = floor((lng + 180) / 6) + 1，范围 1-60。
    北/南半球由纬度正负决定。
    """
    zone = int((lng + 180.0) / 6.0) + 1
    zone = max(1, min(60, zone))
    if lat >= 0:
        return f"EPSG:{32600 + zone}"
    return f"EPSG:{32700 + zone}"


def suggest_gk_zone(lng: float) -> str | None:
    """根据经度推断最合适的 CGCS2000 3 度带 EPSG code。

    3 度带 zone = round(lng / 3)，范围 25-45（覆盖中国 75°E-135°E）。
    超出范围返回 None。
    """
    zone = round(lng / 3.0)
    if zone < 25 or zone > 45:
        return None
    return f"EPSG:{4513 + (zone - 25)}"


def normalize_crs_code(code: str) -> str:
    """归一化 CRS code（公共 API）。

    - ``'GCJ-02'`` → ``'GCJ02'``
    - ``'BD-09'`` → ``'BD09'``
    - 其他原样返回

    供路由层/调用方在传入 ``crs_transformer`` 前归一化旧码连字符写法，
    避免 transformer 内部硬编码字符串比较失败。
    """
    legacy_map = {"GCJ-02": "GCJ02", "BD-09": "BD09"}
    return legacy_map.get(code, code)


def _normalize_legacy_code(code: str) -> str:
    """[Deprecated] 内部别名，保留以兼容旧调用方。新代码请用 ``normalize_crs_code``。"""
    return normalize_crs_code(code)
