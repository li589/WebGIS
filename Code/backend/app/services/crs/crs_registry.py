"""CRS 注册表 — 声明式目录，含 13 个常用 CRS（Phase 1 扩展版）。

Phase 2 待扩展：
- 全 UTM 系列（EPSG:32601-32660 北半球、32701-32760 南半球）动态生成
- 全 Gauss-Krüger 3 度带（EPSG:4513-4533 CGCS2000）+ 6 度带
- EASE-Grid 2.0 变体：3km/25km/36km
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

# 按 code 索引的不可变字典
CRS_REGISTRY: dict[str, CRSDef] = {c.code: c for c in _CRS_DEFS}


def get_crs(code: str) -> CRSDef | None:
    """按 code 获取 CRSDef。未注册返回 None。

    兼容旧码连字符写法：``'GCJ-02'`` / ``'BD-09'`` 自动映射为
    ``'GCJ02'`` / ``'BD09'``。
    """
    if not code:
        return None
    normalized = _normalize_legacy_code(code)
    return CRS_REGISTRY.get(normalized)


def list_crs(category: CRSCategory | None = None) -> list[CRSDef]:
    """列出所有（或指定大类）已注册 CRS。"""
    if category is None:
        return list(_CRS_DEFS)
    return [c for c in _CRS_DEFS if c.category == category]


def to_api_payload() -> list[dict[str, Any]]:
    """序列化为前端下拉用 payload（按 category 分组前的平铺列表）。

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