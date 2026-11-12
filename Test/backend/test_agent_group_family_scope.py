# -*- coding: utf-8 -*-
"""产品族 / 产品形态 / 列表查询的边界（2026-11-12 老师第三轮复测）。

三处真缺陷，全部在本地规则层：

1. ``身份证里的 product_family`` 只会是 ``dynamic`` / ``average`` / ``raw``，
   而「动态」这一档在提示表里写成了 ``raw``。说「风云动态产品里的土壤水分」
   时收窄结果为空，助手只能回「没找到」——换一个字说「平均」就好使。
2. 图层库里的族名是「风云卫星 平均散射约束产品」，用户说的是「风云平均产品」。
   整句搜不到、名字首词（「风云卫星」）也对不上，于是「显示组里的 VOD」
   只能勾上族（相当于文件夹），画面没有变化。
3. 「哪些图层的土壤水分平均值最高」这样的句子同时含「图层」和「平均」，
   被当成列表查询交给本地回答，而本地那条路的统计分支排在列表之前，
   结果是拿一段均值正文回答一个「哪些」的问题。
"""

from __future__ import annotations

import pytest

from app.services.agent.mock_orchestrator import (
    _FAMILY_LABELS,
    _IDENTITY_FAMILY_HINTS,
    _catalog_pick_by_group_and_variable,
    _narrow_by_identity,
)
from app.services.agent.orchestrator import _is_list_active_layers_query


def _layers() -> list[dict]:
    """假 id，身份直接从 id 字符串推（测试不能依赖盘上真有产物）。"""
    return [
        {"catalog_id": "imported-nas-fy-avg-vod", "name": "植被光学厚度"},  # fy / average
        {"catalog_id": "imported-nas-fy-dynamic-vod", "name": "植被光学厚度"},  # fy / dynamic
        {"catalog_id": "imported-nas-smap-avg-sm", "name": "土壤水分"},  # smap / average
        {"catalog_id": "imported-nas-smap-dynamic-sm", "name": "土壤水分"},  # smap / dynamic
    ]


class TestFamilyHints:
    """「动态」必须能收窄到 dynamic 那一族。"""

    def test_dynamic_word_matches_dynamic_family(self):
        kept = _narrow_by_identity("显示风云动态产品中的土壤水分", _layers())
        assert [item["catalog_id"] for item in kept] == ["imported-nas-fy-dynamic-vod"]

    def test_average_word_matches_average_family(self):
        kept = _narrow_by_identity("显示风云平均产品中的土壤水分", _layers())
        assert [item["catalog_id"] for item in kept] == ["imported-nas-fy-avg-vod"]

    def test_every_family_has_a_human_label(self):
        for _, families in _IDENTITY_FAMILY_HINTS:
            for family in families:
                assert family in _FAMILY_LABELS, f"{family} 没有中文叫法"

    def test_raw_layers_still_called_dynamic_to_users(self):
        assert _FAMILY_LABELS["raw"] == "动态版"
        assert _FAMILY_LABELS["dynamic"] == "动态版"


class TestListQueryBoundary:
    """「列图层」不能把取数请求也吞进去。"""

    @pytest.mark.parametrize(
        "message",
        ["有哪些活动图层", "查看当前图层", "当前图层是哪个", "哪些图层有土壤水分数据"],
    )
    def test_plain_list_questions_stay_local(self, message):
        assert _is_list_active_layers_query(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            "哪些图层的土壤水分平均值最高",
            "哪些图层的像元数最多",
            "当前图层的统计信息",
            "查看当前图层最大值",
        ],
    )
    def test_statistics_questions_are_not_list_queries(self, message):
        assert _is_list_active_layers_query(message) is False

    def test_selected_layer_query_is_not_a_list_query(self):
        """「现在选中的是哪个」走的是页面状态分支，不是列表分支。"""
        assert _is_list_active_layers_query("现在选中的是哪个") is False


class TestGroupPick:
    """「族 + 变量」的选层只在该收窄的时候收窄。"""

    def test_plain_variable_does_not_go_through_group_pick(self):
        """没说来源、没说形态：只指变量，交给普通选层，别凭空挑一个族。"""
        assert _catalog_pick_by_group_and_variable("显示植被光学厚度") is None

    def test_group_word_without_variable_does_not_pick(self):
        """「打开风云平均产品」没点变量：不能替用户挑一个变量塞进去。"""
        assert _catalog_pick_by_group_and_variable("打开风云平均产品") is None
