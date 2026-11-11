# -*- coding: utf-8 -*-
"""纯图层显隐确定性捷径测试（2026-11-10 用例 04 工具预算耗尽）。

根因：一句「只显示风云…组中的植被光学厚度，保持其他不变」，模型却反复
search_layers / get_layer_meta 查满 4 跳预算，没轮到下发显示就答「工具次数用完」。
显隐没有取数语义、目标层往往就挂在页面上，应由本地规则一步定位一步下发。
"""

from app.services.agent.orchestrator import _resolve_simple_visibility


def _ctx(*names: str) -> dict:
    """构造 client_context.active_layers（前端格式：name 是侧栏变量名）。"""
    layers = []
    for i, name in enumerate(names):
        layers.append(
            {
                "catalog_id": f"imported-{i:03d}",
                "overlay_layer_id": f"overlay-{i:03d}",
                "name": name,
                "visible": False,
                "selected": False,
            }
        )
    return {"active_layers": layers}


def test_show_vod_only_keeps_others_hits_target_layer():
    """用例 04：只显示「植被光学厚度」，命中 VOD 层而非 SM 层。"""
    ctx = _ctx("植被光学厚度", "土壤水分")
    intent = _resolve_simple_visibility(
        "请只显示风云卫星微波反演产品平均散射约束模型组中的植被光学厚度，"
        "保持该组土壤水分显示状态不变，其他图层也保持不变。完成后报告这两层的显示状态。",
        ctx,
    )
    assert intent is not None
    assert intent["name"] == "set_layer_visibility"
    assert intent["args"]["catalog_id"] == "imported-000"  # 植被光学厚度
    assert intent["args"]["visible"] is True


def test_hide_layer_sets_visible_false():
    """隐藏指令下发 visible=false。"""
    ctx = _ctx("土壤水分")
    intent = _resolve_simple_visibility("隐藏风云卫星的土壤水分图层", ctx)
    assert intent is not None
    assert intent["args"]["visible"] is False
    assert intent["args"]["catalog_id"] == "imported-000"


def test_show_simple_layer_hits():
    """简单「显示植被光学厚度」命中。"""
    ctx = _ctx("植被光学厚度")
    intent = _resolve_simple_visibility("显示植被光学厚度图层", ctx)
    assert intent is not None
    assert intent["args"]["visible"] is True


def test_stats_query_does_not_trigger():
    """含取数语义不触发捷径，留给模型。"""
    ctx = _ctx("土壤水分")
    assert _resolve_simple_visibility("帮我算一下广州的土壤水分平均值", ctx) is None


def test_timeline_switch_does_not_trigger():
    """切日期不触发。"""
    ctx = _ctx("土壤水分")
    assert _resolve_simple_visibility("切换到2025年12月15日", ctx) is None


def test_basemap_switch_does_not_trigger():
    """切底图不触发。"""
    ctx = _ctx("土壤水分")
    assert _resolve_simple_visibility("切换为天地图影像底图", ctx) is None


def test_missing_layer_returns_none():
    """目标层不在页面上时返回 None（不瞎回落替代）。"""
    ctx = _ctx("土壤水分")
    assert _resolve_simple_visibility("打开 CMFD 降水图层", ctx) is None
