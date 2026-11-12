# -*- coding: utf-8 -*-
"""静态层切日期、产品族落到具体变量、页面状态查询（2026-11-11 老师第三轮复测）。

这一轮报的三条：

1. 「添加 CMFD 并切换日期」——CMFD 被页面标成静态数据，时间轴没动，回复却说切了。
   根因：静态判定只在**前端**（``agent-ui-intent.ts``）和后端提示词里，后端代码
   在下发前从不判断；而前端那条「不支持切换日期」的回执要下一轮才回到后端。
2. 「显示风云平均产品中的 VOD」只勾上了产品族（相当于文件夹），VOD 那层没打开。
   根因：``_resolve_layer`` 只按**层名**匹配，命中组就停，从不展开
   ``layer_identity`` 的 ``group_members``。
3. 隐藏图层仍是选中层时问「现在选中的是哪个」，走模型链路会答「没有下发界面
   操作」——查询类请求本来就不该下发操作，把「没执行动作」当成失败是判定错了。
"""

from __future__ import annotations

import pytest

from app.services.agent import mock_orchestrator as mo
from app.services.agent.orchestrator import (
    _FORECAST_QUERY_RE,
    _STATE_QUERY_EXCLUDE_RE,
    _STATE_QUERY_RE,
    _layer_is_static,
    _page_state_reply,
)


# ── 一、静态层：能确证是静态才拦 ────────────────────────────────


def test_cmfd_precip_is_static():
    """CMFD 区域降水盘上没有时间帧 ⇒ 静态，不能切日期。"""
    assert _layer_is_static("cmfd-precip-cn") is True


def test_dynamic_layer_is_not_static():
    """有单日帧的层绝不能被判成静态，否则正常切日期全被拦死。"""
    assert _layer_is_static("imported-nas-smap-avg-sm") is False


def test_unknown_layer_is_not_static():
    """认不出的 id 一律不拦——「读不到」不等于「静态」。"""
    assert _layer_is_static("imported-does-not-exist-000") is False
    assert _layer_is_static("") is False


# ── 二、产品族要落到具体变量层 ──────────────────────────────────


def _fake_group(monkeypatch):
    fake = {
        "is_product_group": True,
        "product_group_label": "风云平均",
        "group_members": [
            {
                "overlay_layer_id": "imported-fy-avg-vod",
                "variable": "vod",
                "variable_label": "植被光学厚度",
            },
            {
                "overlay_layer_id": "imported-fy-avg-sm",
                "variable": "sm",
                "variable_label": "土壤水分",
            },
        ],
    }
    monkeypatch.setattr(
        mo, "_layer_identity", lambda cid: fake if cid == "method-fy-average" else {}
    )


def test_group_expands_to_vod_member(monkeypatch):
    """「风云平均产品中的 VOD」必须落到族内的 VOD 层，而不是族本身。"""
    _fake_group(monkeypatch)
    pick = mo._expand_product_group(
        mo.LayerPick("method-fy-average", "风云平均产品"),
        "显示风云平均产品中的VOD",
    )
    assert pick is not None
    assert pick.catalog_id == "imported-fy-avg-vod"
    assert "植被光学厚度" in pick.name


def test_group_expands_to_sm_member(monkeypatch):
    """同一句话换成「土壤水分」，落到的必须是另一个成员。"""
    _fake_group(monkeypatch)
    pick = mo._expand_product_group(
        mo.LayerPick("method-fy-average", "风云平均产品"),
        "打开风云平均产品里的土壤水分",
    )
    assert pick is not None
    assert pick.catalog_id == "imported-fy-avg-sm"


def test_group_without_variable_is_not_guessed(monkeypatch):
    """没点名变量就不许替用户挑一个——原样返回，让上层反问。"""
    _fake_group(monkeypatch)
    pick = mo._expand_product_group(
        mo.LayerPick("method-fy-average", "风云平均产品"), "显示风云平均产品"
    )
    assert pick is not None
    assert pick.catalog_id == "method-fy-average"


def test_non_group_pick_is_untouched(monkeypatch):
    """普通栅格层不受影响。"""
    monkeypatch.setattr(mo, "_layer_identity", lambda cid: {})
    pick = mo._expand_product_group(
        mo.LayerPick("imported-nas-fy-raw-vod", "植被光学厚度"), "显示 VOD"
    )
    assert pick is not None
    assert pick.catalog_id == "imported-nas-fy-raw-vod"


def test_resolve_layer_expands_page_group(monkeypatch):
    """页面上挂的是产品族时，「显示 …里的 VOD」也要落到成员层。"""
    _fake_group(monkeypatch)
    layers = mo._normalize_layers(
        {
            "active_layers": [
                {
                    "catalog_id": "method-fy-average",
                    "name": "风云平均产品",
                    "visible": False,
                    "selected": False,
                }
            ]
        }
    )
    pick = mo._resolve_layer("显示风云平均产品中的VOD", layers)
    assert pick is not None
    assert pick.catalog_id == "imported-fy-avg-vod"


# ── 三、页面状态查询：查询不该被判成「没执行」 ──────────────────


def test_state_query_matches_common_wording():
    for text in (
        "现在选中的是哪个",
        "当前选中哪个图层",
        "哪个图层被选中了",
        "哪些图层在勾选显示",
    ):
        assert _STATE_QUERY_RE.search(text), text


def test_state_query_does_not_swallow_actions():
    """带动作/取数词的一律交给正常链路，不能被状态查询截胡。"""
    for text in (
        "显示 SMAP 土壤水分图层",
        "隐藏当前选中的图层",
        "计算当前选中图层的平均值",
    ):
        assert _STATE_QUERY_EXCLUDE_RE.search(text), text


def test_page_state_reply_reports_hidden_but_selected():
    """隐藏但仍选中：必须同时说清「选中」和「已隐藏」，不能只说层名。"""
    ctx = {
        "active_layers": [
            {
                "catalog_id": "imported-nas-fy-raw-vod",
                "name": "植被光学厚度",
                "visible": False,
                "selected": True,
            }
        ]
    }
    reply = _page_state_reply(ctx)
    assert "当前选中的是" in reply
    assert "已隐藏" in reply


def test_page_state_reply_visible_selected():
    ctx = {
        "active_layers": [
            {
                "catalog_id": "imported-nas-fy-raw-vod",
                "name": "植被光学厚度",
                "visible": True,
                "selected": True,
            }
        ]
    }
    reply = _page_state_reply(ctx)
    assert "当前选中的是" in reply
    assert "勾选显示" in reply
    assert "已隐藏" not in reply


def test_page_state_reply_empty_page():
    assert "没有图层" in _page_state_reply({"active_layers": []})


# ── 四、预报请求：平台没有未来数据，不能说「没查到」 ────────────


@pytest.mark.parametrize(
    "text",
    ["明天会下雨吗", "未来三天有降雨预报吗", "给我河南省的降雨预报"],
)
def test_forecast_query_matches(text):
    assert _FORECAST_QUERY_RE.search(text), text


@pytest.mark.parametrize(
    "text",
    ["河南省 2025 年 12 月的降雨量平均值", "查询 12 月 15 日的土壤水分"],
)
def test_forecast_query_does_not_match_history(text):
    """历史观测/统计不能被当成预报拦掉。"""
    assert not _FORECAST_QUERY_RE.search(text), text
