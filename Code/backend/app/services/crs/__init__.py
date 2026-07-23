"""统一坐标系统（CRS）支持模块。

三层架构：
    Layer 1: ``crs_registry``    — 声明式 CRS 目录（含分类、EPSG、proj4）
    Layer 2: ``crs_transformer`` — pyproj 包装 + GCJ-02/BD-09 委托 + 偏移应用
    Layer 3: ``crs_detector``    — 从 rasterio/GeoJSON/.mat 自动检测

公共 API：
    - 类型：``CRSCategory``、``CRSDef``、``CoordinatePoint``
    - 注册表：``CRS_REGISTRY``、``get_crs``、``list_crs``、``to_api_payload``
    - 转换器：``crs_transformer``（``CRSTransformer`` 单例）
    - 检测器：``crs_detector``（``CRSDetector`` 单例）

注意：旧 ``app.services.coordinate_transform_service`` 已转为 deprecated 垫片，
新代码应直接 ``from app.services.crs import crs_transformer`` 使用。
"""

from __future__ import annotations

from .crs_registry import CRS_REGISTRY, get_crs, list_crs, to_api_payload
from .crs_types import CRSCategory, CRSDef, CoordinatePoint

# 延迟导入 transformer/detector 以避免循环依赖与启动期开销
# （它们内部依赖 pyproj、rasterio）

__all__ = [
    "CRSCategory",
    "CRSDef",
    "CoordinatePoint",
    "CRS_REGISTRY",
    "get_crs",
    "list_crs",
    "to_api_payload",
    "crs_transformer",
    "crs_detector",
]


def __getattr__(name: str):
    """PEP 562 延迟属性：首次访问 crs_transformer / crs_detector 时才导入。

    注意：实现模块用下划线前缀（``_crs_transformer``/``_crs_detector``），
    避免 ``from app.services.crs import crs_transformer`` 因同名子模块
    而返回模块对象而非单例。下划线前缀使子模块与公共属性名解耦。
    """
    if name == "crs_transformer":
        from ._crs_transformer import crs_transformer

        return crs_transformer
    if name == "crs_detector":
        from ._crs_detector import crs_detector

        return crs_detector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
