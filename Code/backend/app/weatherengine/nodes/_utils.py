"""天气节点共享工具函数。"""

from __future__ import annotations

from typing import Any

from shared.contracts.api_contracts import BoundingBox


def get_weather_engine_service():
    """m16 修复：返回 weather_engine_service 单例。

    节点通过此函数获取 service，而非直接 import 模块级单例。
    测试时可 patch 此函数注入 mock，避免修改模块全局变量。

    放在 _utils.py 而非 __init__.py 是为了避免循环导入
    （__init__.py 导入节点类，节点类反向导入 __init__.py 会循环）。
    """
    from app.weatherengine.service import weather_engine_service
    return weather_engine_service


def coerce_float(value: Any) -> float | None:
    """将输入值转换为 float，无法转换时返回 None。"""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def coerce_int(value: Any) -> int | None:
    """将输入值转换为 int，无法转换时返回 None。"""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def resolve_bbox(inputs: dict[str, Any], latitude: float, longitude: float) -> BoundingBox:
    """解析渲染范围，默认以中心点 ±0.5 度生成包围盒。"""
    bbox_param = inputs.get("bbox")
    if isinstance(bbox_param, dict):
        west = bbox_param.get("west")
        south = bbox_param.get("south")
        east = bbox_param.get("east")
        north = bbox_param.get("north")
        if all(isinstance(v, (int, float)) for v in (west, south, east, north)):
            return BoundingBox(west=float(west), south=float(south), east=float(east), north=float(north))
    return BoundingBox(
        west=longitude - 0.5,
        south=latitude - 0.5,
        east=longitude + 0.5,
        north=latitude + 0.5,
        crs="EPSG:4326",
    )
