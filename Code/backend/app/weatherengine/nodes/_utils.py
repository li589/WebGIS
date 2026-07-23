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


def resolve_bbox(
    inputs: dict[str, Any], latitude: float, longitude: float
) -> BoundingBox:
    """解析渲染范围，优先使用 viewport_bbox，否则使用 bbox，最后兜底为默认范围。

    优先级：
    1. inputs["viewport_bbox"]（前端地图视口范围，允许全球浏览）
    2. inputs["bbox"]（工作流空间过滤器）
    3. 默认：以中心点经度 ±1.6、纬度 ±1.2 度生成包围盒

    兜底范围与 service.py 的 _resolve_render_bbox 保持一致，
    确保 workflow 节点路径与 service 路径生成相同密度的网格。
    """
    # 优先使用 viewport_bbox（前端地图视口范围）
    viewport_bbox = inputs.get("viewport_bbox")
    if isinstance(viewport_bbox, dict):
        west = viewport_bbox.get("west")
        south = viewport_bbox.get("south")
        east = viewport_bbox.get("east")
        north = viewport_bbox.get("north")
        if all(isinstance(v, (int, float)) for v in (west, south, east, north)):
            return BoundingBox(
                west=float(west),
                south=float(south),
                east=float(east),
                north=float(north),
            )

    # 回退到 bbox（工作流空间过滤器）
    bbox_param = inputs.get("bbox")
    if isinstance(bbox_param, dict):
        west = bbox_param.get("west")
        south = bbox_param.get("south")
        east = bbox_param.get("east")
        north = bbox_param.get("north")
        if all(isinstance(v, (int, float)) for v in (west, south, east, north)):
            return BoundingBox(
                west=float(west),
                south=float(south),
                east=float(east),
                north=float(north),
            )

    # 兜底：默认范围
    return BoundingBox(
        west=longitude - 1.6,
        south=latitude - 1.2,
        east=longitude + 1.6,
        north=latitude + 1.2,
        crs="EPSG:4326",
    )


def compute_dynamic_resolution(bbox: BoundingBox) -> float:
    """根据 bbox 范围动态计算网格分辨率，控制总网格点数在合理范围（150-3000）。

    与 service.py _build_map_layer_outputs 的分辨率梯度保持一致，
    确保 workflow 节点路径与 service 路径生成相同密度的网格。

    分辨率梯度：
      max_span ≤ 5°  → 0.25°（约 25km，精细局部）
      max_span ≤ 15° → 0.5°（约 50km，区域级）
      max_span ≤ 40° → 1.0°（约 100km，省级）
      max_span ≤ 90° → 2.0°（约 200km，大区级）
      max_span > 90° → 5.0°（约 500km，全球/半球级）
    """
    lat_span = max(0.1, bbox.north - bbox.south)
    lon_span = max(0.1, bbox.east - bbox.west)
    max_span = max(lat_span, lon_span)
    if max_span <= 5:
        return 0.25
    elif max_span <= 15:
        return 0.5
    elif max_span <= 40:
        return 1.0
    elif max_span <= 90:
        return 2.0
    else:
        return 5.0
