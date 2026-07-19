"""CRS 核心类型定义：分类枚举、CRSDef 数据类、CoordinatePoint。

设计要点：
- ``CRSCategory`` 继承 ``str, Enum`` 以便 JSON 序列化为纯字符串
- ``CRSDef`` 使用 ``frozen=True`` 保证注册项可安全共享
- ``CoordinatePoint`` 字段与旧 ``coordinate_transform_service.CoordinatePoint``
  完全一致（lng/lat），保证二进制兼容的 re-export
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CRSCategory(str, Enum):
    """CRS 大类，决定转换路径。"""

    GEOGRAPHIC = "geographic"
    """地理坐标系（经纬度），如 EPSG:4326/4490/4258。"""

    PROJECTED = "projected"
    """投影坐标系（米/英尺），如 EPSG:3857/6933/UTM/Gauss-Krüger。"""

    ENCRYPTED = "encrypted"
    """加密坐标系（非标准 EPSG），如 GCJ-02/BD-09。仅中国境内使用。"""


@dataclass(frozen=True)
class CRSDef:
    """单个 CRS 定义。

    Attributes:
        code: 规范标识符。EPSG 系列为 ``'EPSG:XXXX'``；加密系为 ``'GCJ02'``/``'BD09'``（无前缀）。
        label: 中文显示名（用于前端下拉）。
        category: CRS 大类。
        epsg: 数值 EPSG 代码；加密系为 ``None``。
        proj4_def: proj4 定义字符串；加密系为 ``None``（由 ``_gcj_bd`` 模块处理）。
        area: 常用区域（如 ``'China'``/``'Europe'``/``'Global'``）。
        deprecated: 是否计划在 Phase 3+ 弃用。
    """

    code: str
    label: str
    category: CRSCategory
    epsg: int | None
    proj4_def: str | None
    area: str
    deprecated: bool = False


@dataclass(frozen=True)
class CoordinatePoint:
    """不可变 (lng, lat) 对。

    与旧 ``coordinate_transform_service.CoordinatePoint`` 字段一致，
    保证 deprecated 垫片的 re-export 二进制兼容。
    """

    lng: float
    lat: float
