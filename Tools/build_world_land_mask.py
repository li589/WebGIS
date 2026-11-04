#!/usr/bin/env python3
"""生成「全球陆地」面数据，用于地图上的半透明陆地底衬。

为什么要单独做一份：
  灰底衬需要一整块「陆地」面。直接拿 world-admin-0（Natural Earth 10m 国家面）
  铺色可以，但 NE 的中国边界不是我国标准画法（藏南、阿克赛钦等），
  大面积填色会把错误边界显性化。故：
      陆地 = (NE 全球国家面并集 − 中国标准省界面) ∪ 中国标准省界面
  中国境内由 Data/_boundary_raw/中国_省.geojson（带 gb 国标编码）负责，
  境外仍用 NE，拼出来的是一张「中国合规、境外全球」的陆地掩膜。

输出：Code/frontend/public/data/boundaries/world-land.geojson
  - 单个 FeatureCollection，1 个 MultiPolygon feature
  - 坐标保留 3 位小数（≈100 m），足够半透明底衬用，体积可压到 1~2 MB

用法（项目虚拟环境）：
  Env/Python312/python.exe Tools/build_world_land_mask.py
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import shapely
from shapely.geometry import MultiPolygon, Polygon, mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "Code" / "frontend" / "public" / "data" / "boundaries" / "world-land.geojson"
WORLD_ADMIN0 = REPO_ROOT / "Code" / "frontend" / "public" / "data" / "boundaries" / "world-admin-0.geojson"
CHINA_PROV = Path(r"E:/Project/CGDA/Data/_boundary_raw/中国_省.geojson")

SIMPLIFY_DEG = 0.006   # 约 660 m；半透明底衬看不出，但顶点数降一个量级
ROUND_DEC = 4          # 约 11 m。必须配合 set_precision（先吸附网格再取整，拓扑不变）


def _round_ring(ring):
    if not ROUND_DEC:
        return [[float(x), float(y)] for x, y in ring]
    return [[round(float(x), ROUND_DEC), round(float(y), ROUND_DEC)] for x, y in ring]


def _round_geom(geom):
    if geom.is_empty:
        return None
    if isinstance(geom, Polygon):
        return {"type": "Polygon", "coordinates": [_round_ring(r.coords) for r in [geom.exterior, *geom.interiors]]}
    if isinstance(geom, MultiPolygon):
        polys = []
        for p in geom.geoms:
            polys.append([_round_ring(r.coords) for r in [p.exterior, *p.interiors]])
        return {"type": "MultiPolygon", "coordinates": polys}
    return None


def load_china() -> shapely.Geometry:
    """中国标准省界（只取面要素，文件里另含 8 条 MultiLineString 是境界线）。"""
    with open(CHINA_PROV, encoding="utf-8") as f:
        gj = json.load(f)
    polys = [
        shapely.geometry.shape(feat["geometry"])
        for feat in gj["features"]
        if feat.get("geometry", {}).get("type") in ("Polygon", "MultiPolygon")
    ]
    print(f"中国省界面要素 {len(polys)} 个")
    return shapely.union_all([shapely.make_valid(p) for p in polys])


def load_world() -> shapely.Geometry:
    world = gpd.read_file(WORLD_ADMIN0)
    print(f"NE 国家面 {len(world)} 个，crs={world.crs}")
    geoms = [shapely.make_valid(g) for g in world.geometry if g is not None]
    return shapely.union_all(geoms)


def main() -> None:
    world_land = load_world()
    china_land = load_china()
    print(f"NE 陆地面积(度²) {world_land.area:.1f}；中国面 {china_land.area:.2f}")

    # 关键一步：先把 NE 里的中国画法削掉，再补上标准中国
    trimmed = shapely.difference(world_land, china_land)
    land = shapely.union(trimmed, china_land)
    print(f"合成后面积(度²) {land.area:.1f}，几何类型 {land.geom_type}")

    # NE 原始面本身有自相交，并集后仍会残留 ⇒ 必须 make_valid，否则
    # maplibre 渲染 fill 时可能出现空隙或三角形毛刺
    land = shapely.make_valid(land)
    if land.geom_type == "GeometryCollection":
        parts = [g for g in land.geoms if isinstance(g, (Polygon, MultiPolygon))]
        land = MultiPolygon([p for g in parts for p in (g.geoms if g.geom_type == "MultiPolygon" else [g])])
    if not isinstance(land, (Polygon, MultiPolygon)):
        land = MultiPolygon([g for g in getattr(land, "geoms", []) if isinstance(g, (Polygon, MultiPolygon))])
    print(f"make_valid 后 {land.geom_type}，子面 {len(land.geoms) if hasattr(land, 'geoms') else 1}，valid={land.is_valid}")

    simplified = land.simplify(SIMPLIFY_DEG, preserve_topology=True)
    # set_precision：把坐标吸附到 1e-4° 网格，同时修拓扑。直接 round() 会破坏拓扑
    # （实测 round 到 3 位后读回 valid=False，maplibre 会出现填充空洞）
    simplified = shapely.set_precision(simplified, 10 ** (-ROUND_DEC))
    if not simplified.is_valid:
        simplified = shapely.make_valid(simplified)
        print("简化后又无效，已再修一次")
    if simplified.geom_type == "GeometryCollection":
        parts = [g for g in simplified.geoms if isinstance(g, (Polygon, MultiPolygon))]
        simplified = MultiPolygon([p for g in parts for p in (g.geoms if g.geom_type == "MultiPolygon" else [g])])
    print(f"简化后 {simplified.geom_type}，子面 {len(simplified.geoms) if hasattr(simplified, 'geoms') else 1}，valid={simplified.is_valid}")
    geom = _round_geom(simplified)
    if geom is None:
        raise SystemExit("简化后为空，调小 SIMPLIFY_DEG")

    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"layer": "world-land"}, "geometry": geom}]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))
    size = OUT.stat().st_size / 1024 / 1024
    print(f"写出 {OUT}  {size:.2f} MB")

    # ── 第二份产物：拆成「一个多边形一个要素」的 GeoJSON（前端实际用这份） ──
    # 之前的坑：整块陆地塞进**一个** MultiPolygon 要素（4487 个环）交给
    #   maplibre 的 geojson-vt 切瓦片，中国那一块渲染不出来。拆成独立要素后
    #   每个多边形单独切、单独三角化，不再受整体规模影响。
    # 矢量还有一个好处：投影由 maplibre 自己做，不存在"图片贴错位置"。
    _write_parts_geojson(simplified)

    # ── 第三份产物：栅格掩膜 PNG（备用，当前前端未使用） ────────────────────
    _write_mask_png(simplified)


def _write_parts_geojson(land) -> None:
    """把陆地拆成「一个 Polygon = 一个 Feature」，输出 world-land-parts.geojson。

    maplibre 的 fill 图层只会把落在视口内的多边形切瓦片；拆开后单次工作量小、
    且没有跨半球的超大连通域，避免"某块陆地（中国）整块渲染不出来"。
    面积小于 MIN_AREA 的碎岛直接丢弃——半透明底衬上看不见，还能把体积压下来。
    """
    MIN_AREA = 0.01  # 度²，赤道附近约 120 km²
    polys = [g for g in getattr(land, "geoms", [land]) if isinstance(g, Polygon)]
    keep = [p for p in polys if p.area >= MIN_AREA]
    dropped = len(polys) - len(keep)
    features = []
    for p in keep:
        geom = _round_geom(p)
        if geom is None:
            continue
        features.append({"type": "Feature", "properties": {}, "geometry": geom})
    out = OUT.with_name("world-land-parts.geojson")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"写出 {out.name}  {out.stat().st_size / 1024 / 1024:.2f} MB  要素 {len(features)} 个（丢弃碎岛 {dropped} 个）")


def _write_mask_png(land) -> None:
    """把陆地几何烤成 **Web Mercator（EPSG:3857）** 的 RGBA PNG。

    ⚠ 必须在 3857 平面光栅化，不能按经纬度线性烤（第一版就错在这）：
      maplibre 的 image source 把图片四角映射到地图平面上，中间做仿射插值。
      而地图本身是墨卡托（y 与 ln(tan(45°+φ/2)) 成正比，不是与 φ 成正比）。
      若 PNG 按 φ 线性排列，贴上去以后只有四角对得上、**中间纬度全错位**：
      高纬陆地被压向低纬，俄罗斯、加拿大整体下移，中国轮廓与底图对不齐。
      ⇒ 先 transform_geom 到 3857 再 rasterize，四角逐好落在墨卡托世界正方形的四角。

    输出范围 = 整个 Web Mercator 世界正方形 ±20037508.34 m（即 ±85.0511°）。
    """
    import numpy as np
    from PIL import Image
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds
    from rasterio.warp import transform_geom

    size = 8192
    half = 20037508.342789244  # Web Mercator 世界正方形半边长（米）

    merc = transform_geom("EPSG:4326", "EPSG:3857", mapping(land), precision=-1)

    for size in (8192, 4096):
        # 8192 等效 z=5 清晰度；4096 供 MAX_TEXTURE_SIZE 只有 4096 的显卡降级使用
        transform = from_bounds(-half, -half, half, half, size, size)
        # all_touched=True：贴边像元也算陆地，避免海岸线出现缺口
        alpha = rasterize(
            [merc],
            out_shape=(size, size),
            transform=transform,
            fill=0,
            default_value=255,
            dtype="uint8",
            all_touched=True,
        )
        rgba = np.zeros((size, size, 4), dtype="uint8")
        rgba[..., 0] = 0x0C
        rgba[..., 1] = 0x22
        rgba[..., 2] = 0x38
        rgba[..., 3] = alpha
        name = f"world-land-merc-{size}.png"
        png = OUT.with_name(name)
        Image.fromarray(rgba, "RGBA").save(png, optimize=True)
        print(f"写出 {png.name}  {png.stat().st_size / 1024 / 1024:.2f} MB  {size}x{size}  EPSG:3857")

    print(f"  ⇒ 前端 coordinates 必须用 ±{85.05112877980659}，不是 ±85")


if __name__ == "__main__":
    main()
