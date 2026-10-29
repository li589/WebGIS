"""省级行政区边界查找（Agent 侧）：省名 → WGS84 多边形。

数据源：天地图「行政区域可视化」官方省界（用户 2026-10-29 手工下载，
``data/provinces_wgs84.geojson``，34 个省级行政区，WGS84 经纬度，含港澳台）。
原文件里的 ``name=='境界线'``（国界/未定界线要素，非面）已在落地时剔除。

用途：让 ``get_layer_statistics`` 支持「四川省」这类**省界掩膜统计**，
而不是拿一个城市中心点画矩形——矩形会把邻省像元也算进来，口径失真。

本模块只读、只做「名字 → 几何」解析，绝不改栅格、绝不写回。
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).parent / "data" / "provinces_wgs84.geojson"


def _load_features() -> list[dict[str, Any]]:
    if not _DATA_FILE.exists():
        logger.warning("省界数据缺失: %s", _DATA_FILE)
        return []
    try:
        with _DATA_FILE.open(encoding="utf-8") as fh:
            doc = json.load(fh)
        return list(doc.get("features") or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("省界数据读取失败: %s", exc)
        return []


@lru_cache(maxsize=1)
def _features_cached() -> tuple[tuple[str, dict[str, Any]], ...]:
    return tuple(
        (str(f.get("properties", {}).get("name") or ""), f) for f in _load_features()
    )


def _normalize(name: str) -> str:
    """去掉行政区划尾词与空白，只留核心名（用于模糊匹配）。"""
    if not name:
        return ""
    s = str(name).strip()
    for suffix in (
        "特别行政区",
        "维吾尔自治区",
        "壮族自治区",
        "回族自治区",
        "自治区",
        "省",
        "市",
    ):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s.strip()


def resolve_province(name: str) -> dict[str, Any] | None:
    """按省名/直辖市名/自治区名查找边界，返回 ``{"name", "gb", "geometry"}``。

    - 精确匹配优先（全名）；
    - 再按「去尾词后的核心名」匹配（支持「四川」「四川 」等简称）；
    - 查不到返回 None（绝不猜、绝不回落成别的省）。
    """
    if not name:
        return None
    q = str(name).strip()
    qn = _normalize(q)
    if not qn:
        return None
    feats = _features_cached()
    # ① 全名精确
    for full, feat in feats:
        if full == q:
            return {
                "name": full,
                "gb": str(feat.get("properties", {}).get("gb") or ""),
                "geometry": feat.get("geometry"),
            }
    # ② 去尾词核心名
    for full, feat in feats:
        if _normalize(full) == qn:
            return {
                "name": full,
                "gb": str(feat.get("properties", {}).get("gb") or ""),
                "geometry": feat.get("geometry"),
            }
    return None


def list_provinces() -> list[str]:
    """所有可查询的省级行政区全名（按文件顺序）。"""
    return [full for full, _ in _features_cached()]
