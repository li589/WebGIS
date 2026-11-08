# -*- coding: utf-8 -*-
"""区域口径守卫 + 服务端重算答复的优先级（2026-11-09 r113 实测引入）。

两件事：

1. ``_guard_reply_numbers`` 看到带 ``authoritative`` 标记的工具步骤（服务端
   自己重算出来的答复）就不要再校验数值。r113 实测：问「2025年12月河南省」，
   模型自己先按 12-15 取了单日帧（0.115 / 8 像元），引擎随后按整月块算出
   0.2484 / 1284，守卫把白名单只建成模型那份，于是把**正确**的整月答复
   重写成了单日数。
2. ``_append_region_scope_note``：县/区一级、以及地名没认出来时，必须在正文
   里点明按哪个范围算的。r113 实测：问「广州市天河区」被静默按整市回答，
   问「河兰省」被静默当成「河南省」。
"""

import json

from app.services.agent import orchestrator as orch
from app.services.agent.orchestrator import _append_region_scope_note, _guard_reply_numbers


def _step(payload):
    return {
        "type": "tool_result",
        "summary": "工具返回",
        "detail": json.dumps(payload, ensure_ascii=False),
    }


_SINGLE_DAY = {
    "ok": True,
    "catalog_id": "imported-55359b8ecd3d",
    "display_name": "风云卫星 平均散射约束产品 · 土壤水分",
    "scope": "region",
    "region": "河南省",
    "region_level": "province",
    "statistic": "mean",
    "requested_time": "20251215",
    "actual_time": "20251215",
    "mean": 0.11497563123703003,
    "min": 0.0512,
    "max": 0.2001,
    "std": 0.041,
    "valid_pixels": 8,
    "total_pixels": 4012,
    "unit_label": "m³/m³",
    "time_source": "requested",
}


def _engine_step(text):
    return {
        "type": "tool_result",
        "summary": "服务端按整月块取数（该层时间清单里就有整月块，未拆成单日）",
        "detail": text,
        "authoritative": True,
    }


ENGINE_TEXT = (
    "「风云卫星 平均散射约束产品 · 土壤水分」按「河南省」行政边界的只读统计：\n"
    "- 均值：0.2484 m³/m³\n"
    "- 范围：0.0200 ~ 0.5209\n"
    "- 有效像元：1284 / 4012（占 32.0%）\n"
    "- 实际数据时间块：2025-12-01 至 2025-12-31"
)


class TestAuthoritativeEngineReply:
    """服务端重算出来的整月答复，不许被模型自己那次单日取数顶掉。"""

    def test_engine_reply_is_kept(self):
        steps = [_step(_SINGLE_DAY), _engine_step(ENGINE_TEXT)]
        out, changed = _guard_reply_numbers(ENGINE_TEXT, steps)
        assert changed is False
        assert out == ENGINE_TEXT

    def test_without_marker_the_guard_would_rewrite_it(self):
        """反证：去掉 authoritative 标记，守卫就会把整月答复换成单日那份。"""
        steps = [_step(_SINGLE_DAY)]
        out, changed = _guard_reply_numbers(ENGINE_TEXT, steps)
        assert changed is True
        assert "0.2484" not in out
        assert "0.115" in out


class TestCountyScopeNote:
    def test_county_is_named_and_city_scope_stated(self):
        reply = "「风云卫星 平均散射约束产品 · 土壤水分」按「广州市」行政边界的只读统计：\n- 均值：0.3399 m³/m³"
        steps = [_step({**_SINGLE_DAY, "region": "广州市", "region_level": "city"})]
        out = _append_region_scope_note("2025年12月广州市天河区的平均土壤水分", reply, steps)
        assert out.startswith(reply)
        assert "天河区" in out
        assert "「广州市」整市" in out
        assert "省级和地级市" in out

    def test_county_already_mentioned_is_not_repeated(self):
        reply = "天河区只支持到地级市，下面是广州市整市的值：0.3399"
        steps = [_step({**_SINGLE_DAY, "region": "广州市", "region_level": "city"})]
        out = _append_region_scope_note("广州市天河区的平均土壤水分", reply, steps)
        assert out == reply


class TestUnknownRegionNote:
    def test_unknown_name_with_region_stats_names_both(self):
        """「河兰省」被模型顺成「河南省」时必须点明，否则用户当成自己写的地方。"""
        reply = "按「河南省」行政边界的只读统计：\n- 均值：0.2484 m³/m³"
        steps = [_step({**_SINGLE_DAY, "region": "河南省"})]
        out = _append_region_scope_note("2025年12月河兰省的平均土壤水分", reply, steps)
        assert "河兰省" in out
        assert "「河南省」算的" in out

    def test_unknown_name_without_region_stats_says_whole_raster(self):
        reply = "整层的只读统计：\n- 均值：0.1494 m³/m³"
        out = _append_region_scope_note("2025年12月河兰省的平均土壤水分", reply, [])
        assert "河兰省" in out
        assert "整幅栅格" in out

    def test_known_region_gets_no_note(self):
        reply = "按「河南省」行政边界的只读统计：\n- 均值：0.2484 m³/m³"
        steps = [_step({**_SINGLE_DAY, "region": "河南省"})]
        out = _append_region_scope_note("2025年12月河南省的平均土壤水分", reply, steps)
        assert out == reply


class TestNoFalsePositive:
    """守卫不能把正常提问当异常，否则每条答复尾巴都挂一段废话。"""

    def test_time_and_capability_questions_untouched(self):
        for msg, reply in [
            ("把时间轴调到2025年11月", "已下发把时间轴切到 2025 年 11 月"),
            ("你能做什么？", "我是 CGDA 的地图助手"),
            ("这个图层是什么数据？", "按月合成的平均版"),
            ("换成河南省呢", "按「河南省」行政边界：均值 0.2484"),
            ("各省份的平均土壤水分", "整层均值 0.1494"),
        ]:
            assert _append_region_scope_note(msg, reply, []) == reply, msg

    def test_month_prefix_is_not_taken_as_place_name(self):
        """正则只能按后缀切，「2025年12月河南省」会带出「月河南省」，必须剥掉。"""
        assert orch._unknown_region_token("2025年12月河南省的平均土壤水分") is None
        assert orch._unknown_region_token("2025年12月河兰省的平均土壤水分") == "河兰省"

    def test_date_suffix_is_not_taken_as_place_name(self):
        """「12月18日广州」会切出「日广州」，只有紧跟数字的「日」才剥。"""
        assert orch._unknown_region_token("2025年12月13日到12月18日广州的平均土壤水分") is None
        assert orch._unknown_region_token("2025年12月18日河兰省的平均土壤水分") == "河兰省"

    def test_county_helper_still_works(self):
        from app.services.agent.mock_orchestrator import _county_like_region_name

        assert _county_like_region_name("2025年12月广州市天河区的平均土壤水分") == "天河区"
