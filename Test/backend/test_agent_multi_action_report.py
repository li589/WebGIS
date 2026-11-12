# -*- coding: utf-8 -*-
"""多步地图指令的「逐项报告」测试（2026-11-11 用户复测第 4 条）。

外部反馈：「同时隐藏 CMFD 和 VOD 时，若仅完成第一步，应明确报告哪一步成功、
哪一步失败或未执行，不能笼统提示『没有执行』。」

旧实现只遍历**已下发**的意图，回执天然只有成功项；用户点名 3 个、只解析出 2 个时，
第 3 个在回复里彻底消失。现在解析阶段把「点名但定位不到」的子句收集起来，
由 ``_map_actions_reply`` 写成「未执行」段。
"""

from app.services.agent.orchestrator import (
    _is_explicit_point_query,
    _is_explicit_statistics_read,
    _is_explicit_stats_composite,
    _map_actions_before_statistics,
    _map_actions_reply,
    _tool_trace_payload,
    _without_false_layer_carry,
)


def test_explicit_coordinate_sampling_is_recognised_but_map_location_is_not():
    assert _is_explicit_point_query("查询 SMAP 在 116.4074, 39.9042 的点位值")
    assert _is_explicit_point_query("查询经度 116.4074、纬度 39.9042 处的点位数值")
    assert _is_explicit_point_query("查询经度 116.4074、纬度 39.9042 处当前 SMAP 图层的数值")
    assert not _is_explicit_point_query("定位到 116.4074, 39.9042")


def test_execution_trace_keeps_requested_and_resolved_layer_ids_separate():
    trace = _tool_trace_payload(
        {"catalog_id": "fy-product-group"},
        {"ok": True, "samples": [{"ok": True, "catalog_id": "imported-fy-vod"}]},
    )
    assert trace["requested_catalog_id"] == "fy-product-group"
    assert trace["resolved_layer_id"] == "imported-fy-vod"


def _hidden_intents() -> list[dict]:
    return [
        {
            "name": "set_layer_visibility",
            "args": {
                "catalog_id": "imported-cmfd",
                "visible": False,
                "display_name": "CMFD 区域降水",
            },
        },
        {
            "name": "set_layer_visibility",
            "args": {
                "catalog_id": "imported-fy-sm",
                "visible": False,
                "display_name": "风云卫星 · 土壤水分",
            },
        },
    ]


def test_all_targets_resolved_reports_only_success():
    """全部定位成功：只报做成了什么，不出现「未执行」（不能无中生有）。"""
    text = _map_actions_reply(_hidden_intents())
    assert "已隐藏" in text
    assert "CMFD 区域降水" in text
    assert "没有执行" not in text


def test_unresolved_target_is_named_in_reply():
    """有定位不到的目标：必须点名说这一步没执行，不能只报成功的两步。"""
    text = _map_actions_reply(_hidden_intents(), ["VOD 植被光学厚度"])
    assert "没有执行" in text
    assert "VOD 植被光学厚度" in text
    # 成功项仍然要报，用户才知道「做成了哪些」
    assert "已隐藏" in text


def test_empty_unresolved_list_is_same_as_none():
    """空列表等价于没有未执行项（调用方无脑传 [] 也安全）。"""
    assert _map_actions_reply(_hidden_intents(), []) == _map_actions_reply(
        _hidden_intents()
    )


def test_duplicate_unresolved_is_reported_once():
    """同一条子句被重复收集时不重复罗列。"""
    text = _map_actions_reply(_hidden_intents(), ["VOD", "VOD"])
    assert text.count("VOD") == 1


def test_composite_layer_date_statistics_keeps_ui_prefix_for_local_execution():
    """组合命令应拆成界面操作和一次服务端统计，不能退回模型多轮循环。"""
    message = "显示 SMAP 平均散射约束产品中的土壤水分，将日期切换到 2025-11-13，并统计广州市行政区平均值。"
    assert _is_explicit_stats_composite(message)
    prefix = _map_actions_before_statistics(message)
    assert "统计" not in prefix
    assert "SMAP" in prefix
    assert "2025-11-13" in prefix


def test_self_contained_statistics_does_not_need_a_previous_chat_or_ui_action():
    message = "请统计 SMAP 平均散射约束产品中的土壤水分在 2025-11-13 广州市行政区的平均值。"
    assert _is_explicit_statistics_read(message)
    assert not _is_explicit_stats_composite(message)
    assert not _is_explicit_statistics_read(
        "请分别统计 SMAP 平均散射约束产品中的土壤水分在 2025-11-13 广州市和深圳市行政区的平均值。"
    )


def test_explicit_layer_rule_never_claims_it_was_carried_from_previous_turn():
    reply = "- 本轮没有重新指定的部分沿用上一轮：图层「土壤水分」\n\n均值：0.0643"
    assert _without_false_layer_carry(reply) == "\n均值：0.0643"
