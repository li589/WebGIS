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
