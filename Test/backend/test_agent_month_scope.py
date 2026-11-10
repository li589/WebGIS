"""「月」粒度提问的口径锁（2026-11-08 外部复测「25 年 12 月」被答成 7 月块）。

用户连着两轮问 12 月，得到的回答是：

    实际数据时间块：2025-07-01 至 2025-07-31
    你请求的日期是 2025-07-31

两个错叠在一起：**月份丢了**（问 12 月答 7 月）、**粒度也丢了**（问整月答某一天）。
根因是 ``_parse_date_arg`` 要求「年-月-日」齐全，「25年12月」「2025年12月」
「2025-12」「12月」全部解析成 ``None``，于是被当成「这句话没提日期」，
静默落回页面时间轴停在的 07-31。

这里锁四件事：
1. 只要年月的写法都认得出来（两位年按 20XX）；
2. 认得出来就**绝不**再落回页面时间轴；
3. 有整月块就走整月块，没有就走逐日合并——不拿某一天冒充满月；
4. 该月根本不在时间清单里时，明说没有，不拿别的月顶替。

纯函数级，不连数据；`_month_scan` 用 monkeypatch 注入时间清单。
"""

from __future__ import annotations

import pytest

from app.services.agent import mock_orchestrator as mo
from app.services.agent import server_tools_runtime


class TestParseMonthArg:
    @pytest.mark.parametrize(
        "text,fallback,expect",
        [
            ("对啊，25年12月的", 2025, (2025, 12)),
            ("2025年12月广州市的平均土壤水分", 2025, (2025, 12)),
            ("2025年12月的平均", None, (2025, 12)),
            ("2025-12", None, (2025, 12)),
            ("2025/12", None, (2025, 12)),
            ("12月的平均", 2025, (2025, 12)),
            ("12月份呢", 2024, (2024, 12)),
            ("25年1月", None, (2025, 1)),
        ],
    )
    def test_month_is_recognised(self, text, fallback, expect):
        assert mo._parse_month_arg(text, fallback) == expect

    @pytest.mark.parametrize(
        "text,fallback",
        [
            ("12月的平均", None),      # 借不到年份就不猜
            ("2025年13月", 2025),      # 13 月不是月份
            ("2025年0月", 2025),
            ("20251215那天", 2025),    # 完整日期不走月份这条路
            ("11月9日到16日", 2025),    # 区间同理
            ("2025-12-15", 2025),
        ],
    )
    def test_month_is_not_invented(self, text, fallback):
        assert mo._parse_month_arg(text, fallback) is None

    def test_compact_date_wins_over_month(self):
        """`20251215` 是完整日期，月份解析不能把它吃掉。"""
        assert mo._parse_date_arg("20251215那天") == "2025-12-15"
        assert mo._parse_month_arg("20251215那天", 2025) is None


class TestMonthDayList:
    def test_december_has_31_days(self):
        days = mo._month_day_list(2025, 12)
        assert len(days) == 31
        assert days[0] == "20251201"
        assert days[-1] == "20251231"

    def test_leap_february(self):
        assert len(mo._month_day_list(2024, 2)) == 29
        assert len(mo._month_day_list(2025, 2)) == 28

    def test_year_rolls_over(self):
        days = mo._month_day_list(2025, 12)
        assert days[-1] == "20251231"


class TestPeriodDay:
    @pytest.mark.parametrize(
        "raw,expect",
        [
            ("20251201", (2025, 12, 1)),      # 工具层回的就是这种紧凑写法
            ("2025-12-01", (2025, 12, 1)),
            ("20251201_20251231", None),      # 16 位是块键，不是日期
            ("", None),
            (None, None),
            ("20251301", None),
        ],
    )
    def test_parse(self, raw, expect):
        got = mo._period_day(raw)
        assert (None if got is None else (got.year, got.month, got.day)) == expect


class TestMonthBlockCovers:
    def test_full_month_block(self):
        res = {"period_start": "20251201", "period_end": "20251231"}
        assert mo._month_block_covers(res, 2025, 12) is True

    def test_dashed_format_also_works(self):
        res = {"period_start": "2025-12-01", "period_end": "2025-12-31"}
        assert mo._month_block_covers(res, 2025, 12) is True

    def test_single_day_frame_is_not_a_month(self):
        """12-15 的单日帧曾被当成「12 月」，那天广州 247 像元全空。"""
        res = {"period_start": "20251215", "period_end": "20251215"}
        assert mo._month_block_covers(res, 2025, 12) is False

    def test_other_month_is_not_this_month(self):
        res = {"period_start": "20250701", "period_end": "20250731"}
        assert mo._month_block_covers(res, 2025, 12) is False

    def test_short_gap_is_not_a_month(self):
        res = {"period_start": "20251201", "period_end": "20251205"}
        assert mo._month_block_covers(res, 2025, 12) is False


class TestMonthScan:
    def test_finds_month_block(self, monkeypatch):
        monkeypatch.setattr(
            server_tools_runtime,
            "_local_time_keys",
            lambda cid: ["20250701_20250731", "20251201_20251231"],
        )
        key, present = mo._month_scan("imported-x", 2025, 12)
        assert key == "20251201_20251231"
        assert present is True

    def test_only_daily_frames(self, monkeypatch):
        """只有单日帧时报「这一月出现过」，让调用方走逐日合并。"""
        monkeypatch.setattr(
            server_tools_runtime,
            "_local_time_keys",
            lambda cid: ["20251201", "20251213", "20251215"],
        )
        key, present = mo._month_scan("imported-x", 2025, 12)
        assert key is None
        assert present is True

    def test_month_absent(self, monkeypatch):
        monkeypatch.setattr(
            server_tools_runtime,
            "_local_time_keys",
            lambda cid: ["20250701_20250731"],
        )
        key, present = mo._month_scan("imported-x", 2025, 12)
        assert key is None
        assert present is False

    def test_missing_list_falls_back_to_daily(self, monkeypatch):
        def boom(cid):
            raise RuntimeError("no meta")

        monkeypatch.setattr(server_tools_runtime, "_local_time_keys", boom)
        key, present = mo._month_scan("imported-x", 2025, 12)
        assert key is None
        assert present is True


LAYER = {
    "catalog_id": "imported-55359b8ecd3d",
    "name": "风云卫星 · 平均散射约束产品 · 土壤水分",
    "visible": True,
    "selected": True,
}
CTX = {"active_layers": [LAYER], "timeline": {"date": "2025-07-31"}}


class TestResolveEntitiesMonth:
    def test_two_digit_year_month(self):
        """「对啊，25年12月的」必须解析出 (2025, 12)，而不是 None。"""
        out = mo.resolve_entities(
            "对啊，25年12月的",
            mo._normalize_layers(CTX),
            client_context=CTX,
            state={"layer_id": "imported-55359b8ecd3d", "region": "广州市",
                   "date": "2025-12-15"},
        )
        assert out["month"] == (2025, 12)
        # 日期没有被编出来：调用方必须走月份这条路
        assert not out["date"]

    def test_month_with_year_does_not_touch_timeline(self):
        out = mo.resolve_entities(
            "2025年12月广州市的平均土壤水分",
            mo._normalize_layers(CTX),
            client_context=CTX,
        )
        assert out["month"] == (2025, 12)
        assert out["region"] == "广州市"

    def test_plain_date_still_takes_priority(self):
        out = mo.resolve_entities(
            "2025年12月15日广州市土壤水分",
            mo._normalize_layers(CTX),
            client_context=CTX,
        )
        assert out["date"] == "2025-12-15"
        assert out["month"] is None


# ---------------------------------------------------------------------------
# 闸门这一侧：月份必须和「X 日到 Y 日」同等对待，否则模型原文被放行。
#
# 2026-11-08 用户实测：模型这一轮调过一次 get_layer_statistics，传的 time
# 是页面时间轴上停着的 12-15（那天广州 247 像元全缺测），闸门按「调过工具
# 就尊重原文」放行，于是「12 月平均」被答成「这天算不出平均值」。
# 根因是 `_asks_date_range` 只认「X 日到 Y 日」，对「25 年 12 月」返回 False。
# ---------------------------------------------------------------------------


class TestAsksMonthScope:
    CTX = {
        "active_catalog_ids": ["imported-55359b8ecd3d"],
        "active_layers": [
            {
                "catalog_id": "imported-55359b8ecd3d",
                "instance_id": "i-0",
                "name": "风云卫星 平均散射约束产品 · 土壤水分",
                "overlay_layer_id": "imported-55359b8ecd3d",
                "visible": True,
                "selected": True,
            }
        ],
        "timeline": {"hour": 0, "date": "2025-12-15", "playing": False},
        "selected_layer_id": "imported-55359b8ecd3d",
    }

    @pytest.mark.parametrize(
        "text",
        [
            "25年12月广州的平均土壤水分",
            "2025年12月广州的平均土壤水分",
            "2025-12 广州市土壤水分平均",
            "12月广州的平均土壤水分",
        ],
    )
    def test_month_phrasings_are_recognised(self, text):
        from app.services.agent import orchestrator as orch

        assert orch._asks_month_scope(text, {}, self.CTX) is True

    @pytest.mark.parametrize(
        "text",
        [
            "12月15日广州市土壤水分",  # 具体某一天，不是整月
            "广州市土壤水分",  # 没提时间
            "20251113 那天广州市土壤水分",
        ],
    )
    def test_non_month_phrasings_are_not_recognised(self, text):
        from app.services.agent import orchestrator as orch

        assert orch._asks_month_scope(text, {}, self.CTX) is False

    def test_year_can_come_from_state(self):
        """只写「12月」时年份借会话状态。"""
        from app.services.agent import orchestrator as orch

        assert (
            orch._asks_month_scope("12月的平均", {"date": "2024-12-01"}, {}) is True
        )

    def test_no_year_anywhere_is_not_recognised(self):
        """借不到年份就不当成可算的请求，交给上层去问哪一年。"""
        from app.services.agent import orchestrator as orch

        assert orch._asks_month_scope("12月的平均", {}, {}) is False

    def test_month_makes_range_question_true(self):
        """月份命中后，区间闸门要把它当成「区间」，从而不让模型原文过关。"""
        from app.services.agent import orchestrator as orch

        msg = "25年12月广州的平均土壤水分"
        assert orch._wants_statistics(msg) is True
        assert orch._asks_date_range(msg, {}, self.CTX) is False
        assert orch._asks_month_scope(msg, {}, self.CTX) is True

    def test_month_block_reply_is_not_rejected_as_unmerged(self, monkeypatch):
        """引擎走「整月块」分支的答案，不许被当成「没走合并」丢掉。

        2026-11-08 r98 实测（用户重启后连中两次）：闸门原先只认「合并平均」，
        而那是**逐日合并**分支的专属措辞；整月块分支写的是「整月合成块」。
        于是引擎算对的 0.3399 被忽略，模型那句「12-15 这天 247 个像元全缺测」
        被原样放行——数值没错，问的整个月却答成了一天。
        """
        from app.services.agent import mock_orchestrator as mo
        from app.services.agent import orchestrator as orch

        canned = (
            "「风云卫星 平均散射约束产品 · 土壤水分」按「广州市」行政边界的只读统计：\n"
            "- 均值：0.3399 m³/m³\n"
            "- 有效像元：36 / 247（占 14.6%）\n"
            "- 口径：这一层该月本身就是整月合成块（2025-12-01 至 2025-12-31）"
        )
        monkeypatch.setattr(mo, "forced_statistics_reply", lambda *a, **k: {"reply": canned})
        steps = orch._EventSteps()
        steps.append(
            {
                "type": "tool",
                "summary": 'get_layer_statistics({"time": "2025-12-15", "region": "广州市"})',
            }
        )
        model_reply = "2025-12-15 这一天，边界内 247 个像元全部缺测，所以算不出均值。"
        out, _ = orch._statistics_fallback_reply(
            "25年12月广州的平均土壤水分",
            model_reply,
            steps,
            "t-month-block",
            self.CTX,
            state={},
            history_state={},
        )
        assert out == canned
        assert "0.3399" in out
        assert "缺测" not in out

    def test_engine_without_merge_markers_still_yields_to_model(self, monkeypatch):
        """反向保险：引擎文案里既没有「合并平均」也没有「整月合成块」时，
        说明它没走合并分支（认不出层 / 落到县区级说明），仍要尊重模型原文。"""
        from app.services.agent import mock_orchestrator as mo
        from app.services.agent import orchestrator as orch

        canned = "「某图层」按「天河区」只能到地级市一级统计，请改到市。均值不适用。"
        monkeypatch.setattr(mo, "forced_statistics_reply", lambda *a, **k: {"reply": canned})
        steps = orch._EventSteps()
        steps.append({"type": "tool", "summary": "get_layer_statistics({})"})
        model_reply = "广州市 2025 年 12 月均值 0.3399 m³/m³，36 个有效像元。"
        out, _ = orch._statistics_fallback_reply(
            "25年12月广州的平均土壤水分",
            model_reply,
            steps,
            "t-month-no-merge",
            self.CTX,
            state={},
            history_state={},
        )
        assert out == model_reply


class TestCarriedMonthScope:
    """整月口径要跟着对话走（2026-11-09 r116 实测）。

    「2025年12月河南省的平均土壤水分」之后接「换成广州市呢」，月份被丢掉、
    退回页面那天（12-15）；而 12-15 在广州是整片缺测，于是答成「这天算不出」，
    与上一句的整月口径完全不是一回事。状态里必须记着 ``2025-12`` 并沿用。
    """

    CTX = {
        "active_layers": [
            {
                "catalog_id": "imported-55359b8ecd3d",
                "instance_id": "i-0",
                "name": "风云卫星 平均散射约束产品 · 土壤水分",
                "overlay_layer_id": "imported-55359b8ecd3d",
                "visible": True,
                "selected": True,
            }
        ],
        "timeline": {"hour": 0, "date": "2025-12-15", "playing": False},
        "selected_layer_id": "imported-55359b8ecd3d",
    }
    STATE = {
        "layer_id": "imported-55359b8ecd3d",
        "layer_name": "风云卫星 平均散射约束产品 · 土壤水分",
        "variable": "sm",
        "region": "河南省",
        "date": "2025-12",
    }

    def test_month_question_is_stored_as_month_in_state(self):
        from app.services.agent import mock_orchestrator as mo

        ents = mo.resolve_entities(
            "2025年12月河南省的平均土壤水分",
            self.CTX["active_layers"],
            client_context=self.CTX,
            state={},
        )
        patch = mo._entities_state_patch(ents)
        assert patch["date"] == "2025-12"
        assert patch["region"] == "河南省"

    @pytest.mark.parametrize(
        "text",
        ["换成广州市呢", "换成植被光学厚度", "那整幅呢"],
    )
    def test_follow_up_keeps_month(self, text):
        from app.services.agent import orchestrator as orch

        assert orch._carried_month_scope(text, self.STATE) is True

    @pytest.mark.parametrize(
        "text",
        ["12月16日广州的土壤水分", "2025-12-16 广州的土壤水分", "20251216 广州的土壤水分"],
    )
    def test_explicit_day_cancels_carried_month(self, text):
        from app.services.agent import orchestrator as orch

        assert orch._carried_month_scope(text, self.STATE) is False

    @pytest.mark.parametrize("state", [{}, {"date": "2025-12-15"}, None])
    def test_only_month_state_carries(self, state):
        from app.services.agent import orchestrator as orch

        assert orch._carried_month_scope("换成广州市呢", state) is False

    def test_model_day_does_not_overwrite_month_state(self):
        """模型自己挑的 12-15 不能把状态里的「2025-12」顶掉。"""
        from app.services.agent import orchestrator as orch

        patch = {"layer_id": "imported-55359b8ecd3d", "region": "广州市", "date": "2025-12-15"}
        out = orch._drop_model_day_over_month("换成广州市呢", self.STATE, patch)
        assert "date" not in out
        assert out["region"] == "广州市"

    def test_explicit_day_does_update_state(self):
        from app.services.agent import orchestrator as orch

        patch = {"region": "广州市", "date": "2025-12-16"}
        out = orch._drop_model_day_over_month("12月16日广州的土壤水分", self.STATE, patch)
        assert out["date"] == "2025-12-16"

    def test_day_state_is_left_alone(self):
        """上一轮本来问的就是某一天，模型传来的日期照常写回。"""
        from app.services.agent import orchestrator as orch

        state = {**self.STATE, "date": "2025-12-16"}
        patch = {"date": "2025-12-18"}
        assert orch._drop_model_day_over_month("换成广州市呢", state, patch)["date"] == "2025-12-18"


class TestToolMonthRewrite:
    """工具层：用户点的是整月，模型传的却是月里某一天 —— 按整月块取数。

    r117 实测「广州和河南 2025年12月哪个土壤水分高」：模型两次都传 12-15，
    广州当天整片缺测、河南只有 8 个像元，比较结论全错。多区域比较只能靠模型
    自己取数（规则引擎一次算一个区域），所以口径必须在工具层就对齐。
    """

    def _patch(self, monkeypatch, block, present=True):
        from app.services.agent import mock_orchestrator as mo

        monkeypatch.setattr(
            mo, "_month_scan", lambda cid, y, m: (block, present), raising=True
        )

    def test_month_message_rewrites_day_to_block(self, monkeypatch):
        from app.services.agent.server_tools_runtime import _month_block_for_message

        self._patch(monkeypatch, "20251201_20251231")
        assert (
            _month_block_for_message("25年12月广州的平均土壤水分", "20251215", "imported-x")
            == "20251201_20251231"
        )

    def test_explicit_day_is_not_rewritten(self, monkeypatch):
        from app.services.agent.server_tools_runtime import _month_block_for_message

        self._patch(monkeypatch, "20251201_20251231")
        assert (
            _month_block_for_message("2025年12月16日广州的土壤水分", "20251215", "imported-x")
            is None
        )

    def test_other_month_is_not_rewritten(self, monkeypatch):
        from app.services.agent.server_tools_runtime import _month_block_for_message

        self._patch(monkeypatch, "20251101_20251130")
        assert (
            _month_block_for_message("11月广州的平均土壤水分", "20251215", "imported-x") is None
        )

    def test_absent_block_returns_none(self, monkeypatch):
        from app.services.agent.server_tools_runtime import _month_block_for_message

        self._patch(monkeypatch, None, present=False)
        assert (
            _month_block_for_message("25年12月广州的平均土壤水分", "20251215", "imported-x")
            is None
        )

    def test_no_message_no_rewrite(self, monkeypatch):
        from app.services.agent.server_tools_runtime import _month_block_for_message

        self._patch(monkeypatch, "20251201_20251231")
        assert _month_block_for_message("", "20251215", "imported-x") is None


class TestRangeStatisticsNasUnavailable:
    """区间/整月逐日合并遇到「按需取数服务不可用」要第一次就停，不能逐日空跑。

    2026-11-09（第十八轮）实测：NAS 隧道整个挂掉（HTTP 530）时，问「12月1日
    到12月31日」会把 31 天逐日各重试 3 次、卡死 3 分多钟。这里锁住：
    ondemand_fetch.reason 是 nas_unreachable / fetch_failed 时，只取一次就转述
    「取数服务暂时不可用」；nas_missing（上游该日真没成果）仍逐日继续。
    """

    def _reply(self, monkeypatch, fetch_reason, call_counter):
        from app.services.agent import mock_orchestrator as mo
        from app.services.agent import server_tools_runtime

        def fake_stats(*a, **k):
            call_counter.append(1)
            return {
                "ok": False,
                "error": "取数服务返回错误，这次没取到",
                "ondemand_fetch": {"reason": fetch_reason, "ok": False},
            }

        # _range_statistics_reply 内部是「函数内局部导入」，
        # 所以要把假实现打到 server_tools_runtime 模块的属性上。
        monkeypatch.setattr(
            server_tools_runtime, "_get_layer_statistics", fake_stats, raising=True
        )
        return mo._range_statistics_reply(
            text="统计土壤水分2025年12月1日到12月31日的均值",
            target={"catalog_id": "imported-x", "overlay_layer_id": "imported-x"},
            region=None,
            days=["20251201", "20251202", "20251203", "20251204"],
            name="SMAP 平均散射约束产品",
            sid="s",
            intents=[],
            client_context=None,
            state=None,
            entities={},
        )

    def test_nas_unreachable_stops_after_first_day(self, monkeypatch):
        calls = []
        reply = self._reply(monkeypatch, "nas_unreachable", calls)
        assert len(calls) == 1  # 只取了一次，没有逐日空跑
        assert "取数服务暂时不可用" in reply["reply"]

    def test_fetch_failed_also_stops_after_first_day(self, monkeypatch):
        calls = []
        reply = self._reply(monkeypatch, "fetch_failed", calls)
        assert len(calls) == 1
        assert "取数服务暂时不可用" in reply["reply"]

    def test_nas_missing_keeps_going(self, monkeypatch):
        """上游该日真没成果（nas_missing）不是服务故障，仍逐日继续。"""
        calls = []
        reply = self._reply(monkeypatch, "nas_missing", calls)
        assert len(calls) == 4  # 四天都取了一遍，没有提前停
