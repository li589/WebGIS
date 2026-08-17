"""CRS 扩展注册表：UTM 120 + GK 21 计数；suggest_utm_zone 样例。"""

from __future__ import annotations

from app.services.crs.crs_registry import (
    list_crs,
    suggest_gk_zone,
    suggest_utm_zone,
    to_api_payload,
    to_api_payload_expanded,
)


def test_expanded_count_utm_and_gk():
    featured = to_api_payload()
    expanded = to_api_payload_expanded()
    # featured = 13 基础 + 5 EASE-Grid 变体（6931/6932/3408/3409/3410）
    assert len(featured) == 18
    assert len(expanded) >= 140

    codes = {item["code"] for item in expanded}
    utm_n = [c for c in codes if c.startswith("EPSG:326")]
    utm_s = [c for c in codes if c.startswith("EPSG:327")]
    assert len(utm_n) == 60
    assert len(utm_s) == 60

    # zone 25–45 = 21；静态 4527/4528/4529 + 动态补齐
    all_defs = list_crs(featured_only=False)
    gk_defs = [c for c in all_defs if "GK zone" in c.label or "高斯-克吕格" in c.label]
    assert len(gk_defs) == 21


def test_suggest_utm_zone_samples():
    assert suggest_utm_zone(116.4, 39.9) == "EPSG:32650"
    assert suggest_utm_zone(116.4, -33.0) == "EPSG:32750"
    assert suggest_utm_zone(0.0, 51.5) == "EPSG:32631"
    # zone = round(116.4/3)=39 → EPSG:4513+(39-25)=4527
    assert suggest_gk_zone(116.4) == "EPSG:4527"
    assert suggest_gk_zone(10.0) is None
