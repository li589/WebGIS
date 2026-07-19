"""[Deprecated] 旧坐标转换服务 — 已由 ``app.services.crs`` 取代。

.. deprecated::
    新代码应直接 ``from app.services.crs import crs_transformer``。
    本模块仅保留以兼容 ``layer_router.py`` 和 ``tile_proxy_service.py`` 旧调用，
    将在 Phase 3+ 完全移除。

策略：
- 保留所有旧函数签名（5 个加密函数 + ``wgs84_to_epsg3857`` + ``transform_point``
  + ``CoordinatePoint`` 类型 + ``CoordinateSystem`` Literal）
- 全部改为 re-export + 委托，加入 ``DeprecationWarning``
- ``transform_point`` 旧签名的 ``source``/``target`` 字面量（``'GCJ-02'``/``'BD-09'``）
  在垫片内归一化为新 code（``'GCJ02'``/``'BD09'``）
"""
from __future__ import annotations

import warnings
from typing import Literal

from app.services.crs import CoordinatePoint as _NewPoint
from app.services.crs._gcj_bd import (
    bd09_to_gcj02 as _bd09_to_gcj02,
    bd09_to_wgs84 as _bd09_to_wgs84,
    gcj02_to_wgs84 as _gcj02_to_wgs84,
    wgs84_to_bd09 as _wgs84_to_bd09,
    wgs84_to_gcj02 as _wgs84_to_gcj02,
)

# 旧 Literal 类型保留（tile_proxy_service.py 用 ``"GCJ-02"`` 字面量做比较）
CoordinateSystem = Literal['EPSG:3857', 'GCJ-02', 'BD-09']

# re-export 类型（二进制兼容：字段同为 lng/lat frozen dataclass）
CoordinatePoint = _NewPoint

_DEPRECATION_MSG = "coordinate_transform_service is deprecated; use app.services.crs"


def _warn() -> None:
    """发出 DeprecationWarning（stacklevel 由调用方调整）。"""
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=3)


def gcj02_to_wgs84(lng: float, lat: float) -> CoordinatePoint:
    """[Deprecated] 委托 ``app.services.crs._gcj_bd.gcj02_to_wgs84``。"""
    _warn()
    return _gcj02_to_wgs84(lng, lat)


def wgs84_to_gcj02(lng: float, lat: float) -> CoordinatePoint:
    """[Deprecated] 委托 ``app.services.crs._gcj_bd.wgs84_to_gcj02``。"""
    _warn()
    return _wgs84_to_gcj02(lng, lat)


def bd09_to_gcj02(lng: float, lat: float) -> CoordinatePoint:
    """[Deprecated] 委托 ``app.services.crs._gcj_bd.bd09_to_gcj02``。"""
    _warn()
    return _bd09_to_gcj02(lng, lat)


def bd09_to_wgs84(lng: float, lat: float) -> CoordinatePoint:
    """[Deprecated] 委托 ``app.services.crs._gcj_bd.bd09_to_wgs84``。"""
    _warn()
    return _bd09_to_wgs84(lng, lat)


def wgs84_to_bd09(lng: float, lat: float) -> CoordinatePoint:
    """[Deprecated] 委托 ``app.services.crs._gcj_bd.wgs84_to_bd09``。"""
    _warn()
    return _wgs84_to_bd09(lng, lat)


def wgs84_to_epsg3857(lng: float, lat: float) -> CoordinatePoint:
    """[Deprecated] 委托 ``crs_transformer.transform_point(lng, lat, 'EPSG:4326', 'EPSG:3857')``。"""
    _warn()
    from app.services.crs import crs_transformer

    return crs_transformer.transform_point(lng, lat, 'EPSG:4326', 'EPSG:3857')


def transform_point(
    lng: float,
    lat: float,
    source: CoordinateSystem,
    target: CoordinateSystem = 'EPSG:3857',
) -> CoordinatePoint:
    """[Deprecated] 旧签名兼容：``source``/``target`` 用 ``'GCJ-02'``/``'BD-09'``/``'EPSG:3857'`` 字面量。

    旧字面量在垫片内归一化为新 code（``'GCJ02'``/``'BD09'``），然后委托
    ``crs_transformer.transform_point``。新 transformer 支持更多 CRS 路径，
    超出旧实现的组合（如 ``GCJ-02 → BD-09``）现在也能正常工作。
    """
    _warn()
    from app.services.crs import crs_transformer

    # 旧字面量 → 新 code
    src = 'GCJ02' if source == 'GCJ-02' else source
    tgt = 'BD09' if target == 'BD-09' else target
    return crs_transformer.transform_point(lng, lat, src, tgt)
