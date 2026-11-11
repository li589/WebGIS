# -*- coding: utf-8 -*-
"""「切换图层到日期」部分下发守卫测试（2026-11-10 外部实测）。

同样一句「切换到风云动态图层，日期设到某天」，4 次里 1 次模型只下发
``set_timeline``、漏了 ``set_layer_visibility``，正文却写「下发了显示 + 切时间轴」。
这类「部分意图 + 正文夸大」现有零意图守卫拦不住，靠本守卫单独纠正。
"""

from app.services.agent.orchestrator import _guard_partial_layer_switch_intent


def _reply_claiming_both() -> dict:
    return {
        "reply": "已下发显示「风云卫星 动态散射约束产品 · 土壤水分」，并把时间轴切到 2025-12-01；这两条操作已下发。",
        "ui_intents": [
            {"name": "set_timeline", "args": {"date": "2025-12-01"}},
        ],
    }


def test_partial_switch_claiming_both_is_corrected():
    """只切了时间轴、漏勾图层，却写「两条都下发」→ 纠正成如实说明。"""
    out = _guard_partial_layer_switch_intent(
        "切换到风云卫星动态散射约束产品图层，日期设到2025年12月1日",
        _reply_claiming_both(),
    )
    assert "没有勾选" in out["reply"]
    assert "已下发显示" not in out["reply"]


def test_layer_already_shown_is_untouched():
    """图层和日期都下发了 → 不拦。"""
    out = _guard_partial_layer_switch_intent(
        "切换到风云卫星动态散射约束产品图层，日期设到2025年12月1日",
        {
            "reply": "已下发显示，并切时间轴。",
            "ui_intents": [
                {"name": "set_layer_visibility", "args": {"visible": True}},
                {"name": "set_timeline", "args": {"date": "2025-12-01"}},
            ],
        },
    )
    assert out["reply"] == "已下发显示，并切时间轴。"


def test_no_date_in_message_is_untouched():
    """纯图层切换、没有日期含义 → 不触发本守卫（不是复合指令）。"""
    out = _guard_partial_layer_switch_intent(
        "切换到风云卫星动态散射约束产品图层",
        {
            "reply": "已下发显示。",
            "ui_intents": [{"name": "set_timeline", "args": {}}],
        },
    )
    assert out["reply"] == "已下发显示。"


def test_no_layer_word_in_message_is_untouched():
    """纯切日期、没有图层切换含义 → 不触发。"""
    out = _guard_partial_layer_switch_intent(
        "把时间轴切到2025年12月1日",
        {
            "reply": "已切到 2025-12-01。",
            "ui_intents": [{"name": "set_timeline", "args": {"date": "2025-12-01"}}],
        },
    )
    assert out["reply"] == "已切到 2025-12-01。"


def test_no_done_word_is_untouched():
    """正文没写完成态 → 不拦（可能正文本来就如实说明）。"""
    out = _guard_partial_layer_switch_intent(
        "切换到风云卫星动态散射约束产品图层，日期设到2025年12月1日",
        {
            "reply": "我先按土壤水分层下发，时间轴切到 2025-12-01。",
            "ui_intents": [{"name": "set_timeline", "args": {"date": "2025-12-01"}}],
        },
    )
    assert out["reply"] == "我先按土壤水分层下发，时间轴切到 2025-12-01。"


def test_zero_intents_is_untouched_here():
    """零意图时不归本守卫管（交给 _guard_unclaimed_view_intent），原样返回。"""
    out = _guard_partial_layer_switch_intent(
        "切换到风云卫星动态散射约束产品图层，日期设到2025年12月1日",
        {"reply": "已下发显示并切时间轴。", "ui_intents": []},
    )
    assert out["reply"] == "已下发显示并切时间轴。"
