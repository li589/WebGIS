"""行政区边界查找（Agent 侧）：省名 / 地级市名 → WGS84 多边形。

数据源：天地图「行政区域可视化」官方边界（用户 2026-10-29 手工下载，WGS84 经纬度）。
- ``data/provinces_wgs84.geojson``：34 个省级行政区（含港澳台）。
- ``data/cities_wgs84.geojson``：368 个地级市（23 省 + 5 自治区；4 个直辖市不重复收录，
  它们本身已是省级面）。原文件里的 ``name=='境界线'``（国界/未定界线要素，非面）
  以及直辖市条目已在落地时剔除。

用途：让 ``get_layer_statistics`` 支持「四川省」「广州市」这类**行政边界掩膜统计**，
而不是拿一个城市中心点画矩形——矩形会把邻省/邻市像元也算进来，口径失真。

市级文件为压进 git 单文件 1024KB 限制做过拓扑简化（容差 0.02°，约 2km，
实测各市面积变化中位数 0.23%），对 9km 栅格统计的影响小于 1 个像元。

本模块只读、只做「名字 → 几何」解析，绝不改栅格、绝不写回。
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent / "data"
_DATA_FILE_PROV = _DATA_DIR / "provinces_wgs84.geojson"
_DATA_FILE_CITY = _DATA_DIR / "cities_wgs84.geojson"

# 归一化时要从尾部剥掉的行政区划类型词。长的必须排在短的之前，
# 否则「自治州」会先被「州」这类短词切断。
_SUFFIXES = (
    "特别行政区",
    "维吾尔自治区",
    "壮族自治区",
    "回族自治区",
    "自治区",
    "自治州",
    "地区",
    "省",
    "市",
    "盟",
)


def _load_features(path: Path, label: str) -> list[dict[str, Any]]:
    if not path.exists():
        logger.warning("%s数据缺失: %s", label, path)
        return []
    try:
        with path.open(encoding="utf-8") as fh:
            doc = json.load(fh)
        return list(doc.get("features") or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s数据读取失败: %s", label, exc)
        return []


@lru_cache(maxsize=2)
def _features_cached(level: str) -> tuple[tuple[str, dict[str, Any]], ...]:
    if level == "city":
        feats = _load_features(_DATA_FILE_CITY, "市界")
    else:
        feats = _load_features(_DATA_FILE_PROV, "省界")
    return tuple((str(f.get("properties", {}).get("name") or ""), f) for f in feats)


def _normalize(name: str) -> str:
    """去掉行政区划尾词与空白，只留核心名（用于模糊匹配）。"""
    if not name:
        return ""
    s = str(name).strip()
    for suffix in _SUFFIXES:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s.strip()


def _hit(feat: dict[str, Any], level: str) -> dict[str, Any]:
    props = feat.get("properties", {}) or {}
    out: dict[str, Any] = {
        "name": str(props.get("name") or ""),
        "gb": str(props.get("gb") or ""),
        "geometry": feat.get("geometry"),
        "level": level,
    }
    if level == "city":
        out["province"] = str(props.get("province") or "")
    return out


def _lookup(
    name: str, level: str, *, allow_normalized: bool = True
) -> dict[str, Any] | None:
    """在指定层级里按「全名精确 → 去尾词核心名」查找。"""
    if not name:
        return None
    q = str(name).strip()
    feats = _features_cached(level)
    for full, feat in feats:
        if full == q:
            return _hit(feat, level)
    if not allow_normalized:
        return None
    qn = _normalize(q)
    if not qn:
        return None
    matches = [_hit(feat, level) for full, feat in feats if _normalize(full) == qn]
    # 核心名撞车时（极少见）宁可不答，也不猜错行政区
    if len(matches) == 1:
        return matches[0]
    # 前缀匹配：「凉山」→「凉山彝族自治州」。自治州/地区的民族名无法穷举剥离，
    # 用前缀兜住；但必须 >=2 字且**唯一命中**，否则「海」这类会撞上海口/海东。
    if len(qn) >= 2:
        prefix_hits = [
            _hit(feat, level) for full, feat in feats if _normalize(full).startswith(qn)
        ]
        if len(prefix_hits) == 1:
            return prefix_hits[0]
    # 口语习惯把「自治州」简称成「XX州」（凉山州 / 阿坝州 / 伊犁州 / 黔南州）。
    # 尾词表里只有整词「自治州」，剥不出尾巴那个「州」字，于是一路落空
    # （2026-10-29 实测：凉山州/阿坝州/甘孜州/黔东南州/伊犁州/海西州/延边州/
    # 湘西州/黔南州/大理州/巴音州 全部「未匹配」，而只写「凉山」反而能命中）。
    # 所以这里再剥一次尾「州」——**必须在精确匹配与前缀匹配之后**才做，
    # 否则「杭州市」（归一化后「杭州」）会被切成「杭」。剥完要求 >=2 字，
    # 且必须唯一命中，宁可查不到也不猜错行政区。
    if len(qn) >= 3 and qn.endswith("州"):
        core = qn[:-1]
        exact_hits = [
            _hit(feat, level) for full, feat in feats if _normalize(full) == core
        ]
        if len(exact_hits) == 1:
            return exact_hits[0]
        prefix_hits = [
            _hit(feat, level)
            for full, feat in feats
            if _normalize(full).startswith(core)
        ]
        if len(prefix_hits) == 1:
            return prefix_hits[0]
    return None


def resolve_province(name: str) -> dict[str, Any] | None:
    """按省名/直辖市名/自治区名查找边界（省级，含港澳台）。

    - 精确匹配优先（全名）；
    - 再按「去尾词后的核心名」匹配（支持「四川」「四川 」等简称）；
    - 查不到返回 None（绝不猜、绝不回落成别的省）。
    """
    return _lookup(name, "province")


def resolve_city(name: str) -> dict[str, Any] | None:
    """按地级市名查找边界（含自治州/地区/盟）。查不到返回 None。"""
    return _lookup(name, "city")


def resolve_region(name: str) -> dict[str, Any] | None:
    """统一入口：先认省级，再认地级市。

    匹配顺序刻意设计成「省精确 → 市精确 → 省归一化 → 市归一化」，
    这样「吉林市」会命中地级市吉林市，而「吉林」仍然命中吉林省
    （两者归一化后同为「吉林」，靠精确匹配先分流）。
    """
    if not name:
        return None
    prov = _lookup(name, "province", allow_normalized=False)
    if prov:
        return prov
    city = _lookup(name, "city", allow_normalized=False)
    if city:
        return city
    prov = _lookup(name, "province")
    if prov:
        return prov
    return _lookup(name, "city")


def list_provinces() -> list[str]:
    """所有可查询的省级行政区全名（按文件顺序）。"""
    return [full for full, _ in _features_cached("province")]


def list_cities() -> list[str]:
    """所有可查询的地级市全名（按文件顺序）。"""
    return [full for full, _ in _features_cached("city")]
