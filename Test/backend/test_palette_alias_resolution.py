"""palette 别名机制回归锁（2026-08-24 图层登记配置审查 P0 发现）。

旧实现 ``key = aliased or raw.lower() if raw.lower() in _PALETTES else raw``
因条件表达式优先级低于 or，实际解析为
``(aliased or raw.lower()) if (raw.lower() in _PALETTES) else raw``——
**别名从未生效**（凡原名不是实现键的别名一律回落 viridis）。
descriptor 语义 ramp（hfp-ramp/forest-ramp/…）与 matplotlib 经典名
（RdBu/Set3/…）共 17 个名字静默错色。
"""

from __future__ import annotations

import pytest

from app.services.raster_preview_service import resolve_palette_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 既有别名复活（优先级 bug 修复前全部回落 viridis）
        ("elevation-terrain-ramp", "terrain"),
        ("spectral-ramp", "spectral"),
        # descriptor 语义 ramp → registry de-facto 显示配色
        ("igbp", "tab10"),
        ("igbp-landcover-ramp", "tab10"),
        ("clcd-landcover-ramp", "tab10"),
        ("hfp-ramp", "hot"),
        ("forest-ramp", "greens"),
        ("ndvi-ramp", "greens"),
        ("biomass-ramp", "ylgn"),
        ("soil-moisture-ramp", "magenta-yellow"),
        ("station-ramp", "magenta-yellow"),
        ("bright-temp-ramp", "thermal-orange"),
        ("gebco-terrain-ramp", "terrain"),
        # matplotlib 经典名
        ("RdBu", "red-blue"),
        ("YlOrBr", "ylorrd"),
        ("PuBu", "blues"),
        ("Oranges", "reds"),
        ("Set3", "tab10"),
        ("RdYlGn", "rdylgn_r"),
        # 原有正常路径不回归
        ("brg", "brg"),
        ("YlGnBu", "ylgnbu"),
        ("thermal-orange", "thermal-orange"),
        ("viridis", "viridis"),
        ("", "viridis"),
        (None, "viridis"),
        ("totally-unknown", "viridis"),
    ],
)
def test_resolve_palette_id(raw: str | None, expected: str) -> None:
    assert resolve_palette_id(raw) == expected
