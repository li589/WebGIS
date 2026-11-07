"""Agent 回复质量回归测试（用户 2026-10-21 反馈「文本太杂乱」）。

这些测试锁定三件事，防止以后被改回去：

1. **正文不出现内部 id**（catalog_id / imported-xxx / 日期帧 / 裸 JSON）
2. **匹配不到图层时不瞎回落**（宁可反问，也不能错报成功）
3. **切日期先校验**（超范围明确说没有数据，而不是空口「正在更新时间轴」）

纯函数级测试，不启动 app，秒级完成。
"""

from __future__ import annotations

import json

from app.services.agent.mock_orchestrator import mock_chat
from app.services.agent.naming import (
    UNKNOWN_LAYER_NAME,
    fmt_value,
    human_layer_name,
    is_internal_id,
    join_layer_names,
)
from app.services.agent.orchestrator import (
    _build_system,
    _guard_reply_numbers,
    _stat_percent_values,
    _stat_values,
    _synthesize_reply_from_tool_steps,
    _wants_statistics,
)

INSIDE_IDS = (
    "imported-38993117b963",
    "method-smap-season-mean",
    "20251201_20260201",
)

CTX = {
    "active_layers": [
        {"catalog_id": "imported-38993117b963", "name": "土壤水分（SMAP 平均）"},
        {"catalog_id": "method-smap-season-mean", "name": "风云卫星反演（土壤水分）"},
    ]
}


def _reply(message: str, ctx: dict | None = None) -> dict:
    return mock_chat(message, client_context=ctx if ctx is not None else CTX)


def _assert_no_ids(text: str) -> None:
    for bad in INSIDE_IDS:
        assert bad not in text, f"正文出现了内部 id {bad}：{text}"


class TestReplyHasNoInternalIds:
    def test_list_active_layers_uses_names(self) -> None:
        out = _reply("有哪些活动图层")
        assert "土壤水分（SMAP 平均）" in out["reply"]
        assert "风云卫星反演（土壤水分）" in out["reply"]
        _assert_no_ids(out["reply"])

    def test_show_layer_uses_name(self) -> None:
        out = _reply("打开土壤水分")
        assert "土壤水分（SMAP 平均）" in out["reply"]
        _assert_no_ids(out["reply"])
        assert out["ui_intents"][0]["name"] == "set_layer_visibility"

    def test_hide_layer_uses_name(self) -> None:
        out = _reply("隐藏风云")
        assert "风云卫星反演（土壤水分）" in out["reply"]
        _assert_no_ids(out["reply"])

    def test_opacity_uses_name_and_percent(self) -> None:
        out = _reply("风云 透明度 60%")
        assert "60%" in out["reply"]
        _assert_no_ids(out["reply"])

    def test_remove_layer_uses_name(self) -> None:
        out = _reply("移除土壤水分")
        assert "土壤水分（SMAP 平均）" in out["reply"]
        _assert_no_ids(out["reply"])

    def test_fit_layer_uses_name(self) -> None:
        out = _reply("缩放到风云")
        assert "风云卫星反演（土壤水分）" in out["reply"]
        _assert_no_ids(out["reply"])

    def test_basemap_reply_has_no_source_id(self) -> None:
        out = _reply("切换为天地图影像")
        assert "天地图影像" in out["reply"]
        assert "tianditu-img" not in out["reply"]


class TestNoBlindFallback:
    """旧实现匹配不到就回落 layers[0] / CMFD 降水，会错报成功。"""

    def test_hide_unknown_layer_asks_instead_of_guessing(self) -> None:
        out = _reply("隐藏那个很厉害的东西")
        assert out["ui_intents"] == []
        assert "请指明是哪个图层" in out["reply"]

    def test_opacity_unknown_layer_asks(self) -> None:
        out = _reply("透明度 30%")
        assert out["ui_intents"] == []
        assert "请指明是哪个图层" in out["reply"]

    def test_open_without_any_layer_hint_asks(self) -> None:
        out = _reply("打开一下")
        assert out["ui_intents"] == []
        assert "要打开哪个图层" in out["reply"]

    def test_ambiguous_prefix_does_not_guess(self) -> None:
        ctx = {
            "active_layers": [
                {"catalog_id": "a-1", "name": "土壤水分（SMAP）"},
                {"catalog_id": "b-2", "name": "土壤墒情（风云）"},
            ]
        }
        out = _reply("打开土壤", ctx)
        assert out["ui_intents"] == [], "歧义时不应猜一个就执行"
        assert "哪个图层" in out["reply"]
        # 反问时要列出候选，否则用户不知道该怎么答
        assert "土壤水分（SMAP）" in out["reply"]


class TestTimelineValidation:
    RANGE_CTX = {
        "active_layers": [{"catalog_id": "x", "name": "土壤水分"}],
        "timeline": {
            "data_range": {"start": "20251201", "end": "20260201", "frames": 63}
        },
    }

    def test_chinese_date_is_parsed(self) -> None:
        out = _reply("切换到2025年12月15日", self.RANGE_CTX)
        assert out["ui_intents"], "中文日期没被识别，整句掉进兜底"
        assert out["ui_intents"][0]["name"] == "set_timeline"
        assert out["ui_intents"][0]["args"]["date"] == "2025-12-15"
        assert "2025-12-15" in out["reply"]

    def test_iso_date_is_parsed(self) -> None:
        out = _reply("切到 2025-12-20", self.RANGE_CTX)
        assert out["ui_intents"][0]["args"]["date"] == "2025-12-20"

    def test_out_of_range_refuses_and_explains(self) -> None:
        out = _reply("切换到2026年6月15日", self.RANGE_CTX)
        assert out["ui_intents"] == [], "超范围仍下发了 set_timeline，会假装切成功"
        assert "没有切换" in out["reply"]
        assert "2025-12-01" in out["reply"]
        assert "2026-02-01" in out["reply"]

    def test_without_range_does_not_claim_success(self) -> None:
        out = _reply("切换到2025年12月15日")
        # 没有上报可用范围时不许断言「有数据」，但要说明以回显为准
        assert "以气泡下方的执行结果为准" in out["reply"]


class TestNamingHelpers:
    def test_human_layer_name_never_returns_id(self) -> None:
        assert human_layer_name("imported-38993117b963", None) == UNKNOWN_LAYER_NAME
        assert human_layer_name("imported-38993117b963", CTX) == "土壤水分（SMAP 平均）"

    def test_human_layer_name_ignores_id_like_default(self) -> None:
        assert (
            human_layer_name("nope", None, default="imported-abc12345")
            == UNKNOWN_LAYER_NAME
        )

    def test_is_internal_id(self) -> None:
        assert is_internal_id("imported-38993117b963")
        assert is_internal_id("20251201")
        assert is_internal_id("20251201_20260201")
        assert is_internal_id("123456677")
        assert not is_internal_id("土壤水分（SMAP 平均）")
        assert not is_internal_id("ETOPO 高程")

    def test_join_layer_names_caps_output(self) -> None:
        ctx = {
            "active_layers": [
                {"catalog_id": f"layer-{i}", "name": f"产品{i}"} for i in range(8)
            ]
        }
        text = join_layer_names([f"layer-{i}" for i in range(8)], ctx)
        assert "等 8 个图层" in text

    def test_join_layer_names_all_unknown_collapses(self) -> None:
        # 全部查不到名字时去重成一句，不重复刷「该图层」
        assert join_layer_names(["x-1", "x-2"], None) == UNKNOWN_LAYER_NAME

    def test_fmt_value(self) -> None:
        assert fmt_value(0.123456, "m³/m³") == "0.1235 m³/m³"
        assert fmt_value(None, "mm") == "无值"
        assert fmt_value(12, "℃") == "12 ℃"


class TestToolSynthesis:
    def _step(self, payload: dict) -> list[dict]:
        return [
            {
                "type": "tool_result",
                "detail": json.dumps(payload, ensure_ascii=False),
            }
        ]

    def test_layer_search_result_has_no_id_or_json(self) -> None:
        steps = self._step(
            {
                "ok": True,
                "query": "土壤",
                "layers": [
                    {
                        "layer_id": "imported-38993117b963",
                        "display_name": "土壤水分（SMAP 平均）",
                    }
                ],
            }
        )
        text = _synthesize_reply_from_tool_steps(steps) or ""
        assert "土壤水分（SMAP 平均）" in text
        _assert_no_ids(text)
        assert "{" not in text

    def test_sample_result_carries_quality_label(self) -> None:
        steps = self._step(
            {
                "ok": True,
                "lng": 116.4,
                "lat": 39.9,
                "samples": [
                    {
                        "ok": True,
                        "catalog_id": "imported-38993117b963",
                        "display_name": "土壤水分（SMAP 平均）",
                        "value": 0.21,
                        "unit": "m³/m³",
                        "time": "20251203",
                        "quality": "good",
                        "quality_label": "有效",
                    }
                ],
            }
        )
        text = _synthesize_reply_from_tool_steps(steps) or ""
        assert "土壤水分（SMAP 平均）" in text
        assert "0.21" in text
        assert "有效" in text
        _assert_no_ids(text)

    def test_layer_meta_does_not_dump_json(self) -> None:
        steps = self._step(
            {
                "ok": True,
                "layer": {
                    "layer_id": "imported-38993117b963",
                    "display_name": "土壤水分（SMAP 平均）",
                    "description": "SMAP 反演的表层土壤水分",
                    "temporal_coverage": "2025-12 至 2026-02",
                },
            }
        )
        text = _synthesize_reply_from_tool_steps(steps) or ""
        assert "土壤水分（SMAP 平均）" in text
        assert "{" not in text
        assert "layer_id" not in text
        _assert_no_ids(text)

    def test_error_is_translated(self) -> None:
        steps = self._step({"ok": False, "error": "无权访问该图层"})
        text = _synthesize_reply_from_tool_steps(steps) or ""
        assert "权限" in text


# --- 数值守卫（2026-11-07 第四次复测：一次问两个变量时一项错数被另一项掩护） ---

_SM_1216 = {
    "catalog_id": "method-smap-omega-doy-sm",
    "mean": 0.2025324847763941,
    "valid_pixels": 1995,
    "region": "河南省",
    "actual_time": "20251216",
    "unit": "m³/m³",
    "unit_label": "m³/m³",
    "display_name": "SMAP 动态散射约束产品 · 土壤水分",
}
_VOD_BLOCK = {
    "catalog_id": "imported-5427e1020d63",
    "mean": 0.15066699127652752,
    "valid_pixels": 1340,
    "region": "河南省",
    "actual_time": "20251211_20251218",
    "unit": "1",
    "unit_label": "无量纲",
    "display_name": "SMAP 动态散射约束产品 · 植被光学厚度",
}
_GZ_1216 = {
    "catalog_id": "method-smap-omega-doy-sm",
    "mean": 0.1664,
    "valid_pixels": 63,
    "min": 0.102,
    "max": 0.558,
    "std": 0.066,
    "region": "广州市",
    "actual_time": "20251216",
    "unit": "m³/m³",
    "unit_label": "m³/m³",
    "display_name": "SMAP 动态散射约束产品 · 土壤水分",
}


def _tool_steps(*rows: dict) -> list[dict]:
    return [
        {"type": "tool_result", "detail": json.dumps(r, ensure_ascii=False)}
        for r in rows
    ]


class TestNumberGuard:
    """正文里的统计值必须逐项与本轮取数对得上。

    背景（2026-11-07 实测）：问「土壤水分和 VOD 分别是多少」，工具两次都返回
    SM 0.2025/1995，模型却写「土壤水分 0.293/163」（那是 12-15 的值）。旧判据是
    「正文里任意一个数对上白名单就放行」，VOD 的 0.1507/1340 一对上，整段连错值
    一起流出去，用户拿到一半真一半假。
    """

    def test_one_wrong_among_right_is_rewritten(self) -> None:
        reply = (
            "- 「土壤水分」按「河南省」行政边界，2025-12-16 平均值 0.293 m³/m³，"
            "有效像元 163 个。\n"
            "- 「植被光学厚度」平均值 0.1507 无量纲，有效像元 1340 个。"
        )
        out, changed = _guard_reply_numbers(
            reply, _tool_steps(_SM_1216, _VOD_BLOCK)
        )
        assert changed is True
        assert "0.2025" in out and "1995" in out
        assert "0.293" not in out and "163" not in out

    def test_all_right_is_kept(self) -> None:
        reply = (
            "- 「土壤水分」按「河南省」行政边界，2025-12-16 平均值 0.2025 m³/m³，"
            "有效像元 1995 个。\n"
            "- 「植被光学厚度」平均值 0.1507 无量纲，有效像元 1340 个。"
        )
        out, changed = _guard_reply_numbers(
            reply, _tool_steps(_SM_1216, _VOD_BLOCK)
        )
        assert changed is False
        assert out == reply

    def test_rounding_is_not_treated_as_fabrication(self) -> None:
        """0.2025 写成 0.203、0.1507 写成 0.151 属于正常转写，不许重写。"""
        reply = "河南省的平均值为 0.203 m³/m³，有效像元 1995 个。"
        _, changed = _guard_reply_numbers(reply, _tool_steps(_SM_1216))
        assert changed is False

    def test_derived_numbers_do_not_trigger_rewrite(self) -> None:
        """差值、百分比是模型自己算的，工具从没返回过，不能因此判成编造。"""
        reply = (
            "同一天（2025-12-16）广州市的平均值是 0.166 m³/m³，"
            "河南省是 0.203 m³/m³，广州比河南低约 0.037 m³/m³（低约 18%）。\n"
            "- 广州市：有效像元 63 个（占该市范围内总像元的约 26%），"
            "最低 0.102、最高 0.558 m³/m³，标准差 0.066"
        )
        _, changed = _guard_reply_numbers(reply, _tool_steps(_GZ_1216, _SM_1216))
        assert changed is False

    def test_cross_round_comparison_is_kept(self) -> None:
        """「那跟广州市比差多少」：本轮只统计了广州，正文把上一轮的河南一起比。

        数值全真，只是河南那组不在本轮白名单里。逐个强校验会把这段正确的对比
        整段换成单边一句话，用户问的「差多少」反而没答（2026-11-07 实测）。
        """
        reply = (
            "同一天（2025-12-16）广州市的平均值是 0.166 m³/m³，"
            "河南省是 0.203 m³/m³，广州比河南低约 0.037 m³/m³（低约 18%）。\n"
            "- 广州市：有效像元 63 个（占该市范围内总像元的约 26%），"
            "最低 0.102、最高 0.558 m³/m³，标准差 0.066"
        )
        _, changed = _guard_reply_numbers(reply, _tool_steps(_GZ_1216))
        assert changed is False

    def test_stat_values_skip_dates_and_ratios(self) -> None:
        vals = _stat_values(
            "2025-12-16 平均值 0.2025，占约 26%，低 0.037，有效像元 1995 个"
        )
        assert vals == {0.2025, 1995.0}

    def test_region_regex_prefix_does_not_fake_conflict(self) -> None:
        """区域正则左侧贪心，会抽出「按河南省」，不能因此判成张冠李戴。

        2026-11-07 实测 R：正文本来已经把 0.2025 换算成 20.25%，只因为写的
        「按河南省行政边界」被抽成「按河南省」、与工具返回的「河南省」对不上，
        整段被换成模板句，用户拿回的还是原值——换算白做。
        """
        reply = (
            "按河南省行政边界，2025-12-16 的平均值 0.2025 m³/m³，"
            "换算成百分比是 20.25%（体积含水量）。"
        )
        out, changed = _guard_reply_numbers(reply, _tool_steps(_SM_1216))
        assert changed is False
        assert out == reply
        assert "20.25" in out

    def test_wrong_region_is_still_rewritten(self) -> None:
        """真张冠李戴照样要拦：工具查的是河南省，正文写广州市。"""
        reply = "按广州市行政边界，2025-12-16 的平均值 0.203 m³/m³，有效像元 1995 个。"
        out, changed = _guard_reply_numbers(reply, _tool_steps(_SM_1216))
        assert changed is True
        assert "河南省" in out

    def test_percent_conversion_after_mean_is_kept(self) -> None:
        """0.2025 换算成 20.25% 是模型自己乘 100，不能判成「均值对不上」。

        2026-11-07 实测 R：把 20.25% 写在「平均值」后面，被 `_stat_values` 抓成
        统计值、与工具返回的 0.2025 比不过 ⇒ 整段重写，换算白做；而同一个问法
        另一次因为百分数没挨着「平均值」就过掉了——同一问题两种结果。
        """
        reply = (
            "按河南省行政边界，2025-12-16 平均值 0.2025 m³/m³，"
            "换算后平均值约 20.25%（体积含水量）。"
        )
        out, changed = _guard_reply_numbers(reply, _tool_steps(_SM_1216))
        assert changed is False
        assert out == reply

    def test_wrong_percent_conversion_is_still_rewritten(self) -> None:
        """换算错了照样拦：0.2025 换成 15.07% 对不上。"""
        reply = "按河南省行政边界，2025-12-16 平均值约 15.07%。"
        out, changed = _guard_reply_numbers(reply, _tool_steps(_SM_1216))
        assert changed is True
        assert "0.2025" in out

    def test_percent_values_are_split_out(self) -> None:
        assert _stat_values("平均值约 20.25%，有效像元 1995 个") == {20.25, 1995.0}
        assert _stat_percent_values("平均值约 20.25%，有效像元 1995 个") == {20.25}


class TestRealDateIsInjected:
    """「今天几号」不能拿时间轴日期冒充。

    2026-11-07 实测 N：页面时间轴停在 2025-12-16，问「今天几号」，答「今天是
    2025-12-16」——把用户正在看的那一帧说成了真实日期。服务端把真实日期写进
    系统词，并要求区分二者。
    """

    def test_today_is_not_timeline_date(self) -> None:
        from datetime import datetime

        ctx = {
            "active_catalog_ids": ["method-smap-omega-doy-dynamic"],
            "active_layers": [],
            "timeline": {"hour": 0, "date": "2025-12-16", "playing": False},
        }
        text = _build_system(ctx, cred=None)
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        assert "## 真实日期" in text
        assert today in text
        assert "不是今天" in text


class TestQualityQuestionIsNotStatistics:
    """问「精度 / 误差 / 不确定度」不是要均值，不许被规则引擎换成整幅均值。

    2026-11-07 r25 实测（3/3 稳定复现）：「取到的这个像元值精度是多少？」
    因为 `_STATISTICS_WORDS` 里有「像元」「多少」被判成统计请求，整段被换成
    **整幅全球**的 0.1653 / 363201 个有效像元（5.8%）——用户问的是刚算出来的
    河南值准不准，拿到的却是一个口径完全不同、看着却像答案的数字。
    """

    def test_precision_question_is_not_statistics(self) -> None:
        for msg in (
            "取到的这个像元值精度是多少？误差多大？",
            "这个数据的误差有多大",
            "不确定度是多少",
            "置信度多少",
            "这一层的分辨率是多少",
        ):
            assert _wants_statistics(msg) is False, msg

    def test_real_statistics_still_triggered(self) -> None:
        for msg in (
            "河南省的平均值是多少",
            "广州市的土壤水分是多少",
            "统计一下山东省的均值",
        ):
            assert _wants_statistics(msg) is True, msg


class TestPageSelectionEmptySignal:
    """页面没有选中图层时，「这层」没有指代对象，必须把这一事实交给模型。

    2026-11-07 r25 实测（3/3）：`active_layers=[]` 时问「这层土壤水分」，
    模型 search_layers 拿到候选后自己挑一层就算（2 次挑平均族 0.191、
    1 次挑动态族 0.203），正文一个字不提页面是空的。
    """

    _CTX_EMPTY = {"active_catalog_ids": [], "active_layers": []}
    _CTX_FULL = {
        "active_catalog_ids": ["method-smap-omega-doy-dynamic"],
        "active_layers": [
            {
                "catalog_id": "method-smap-omega-doy-dynamic",
                "overlay_layer_id": "imported-a8940443fd6d",
                "selected": True,
                "visible": True,
            }
        ],
    }

    def test_empty_page_is_flagged(self) -> None:
        from app.services.agent.server_tools_runtime import _search_layers

        out = _search_layers({"query": "土壤水分"}, cred=None, client_context=self._CTX_EMPTY)
        assert out.get("page_selection_empty") is True
        assert "没有选中" in str(out.get("page_selection_note") or "")

    def test_page_with_layer_is_not_flagged(self) -> None:
        from app.services.agent.server_tools_runtime import _search_layers

        out = _search_layers({"query": "土壤水分"}, cred=None, client_context=self._CTX_FULL)
        assert "page_selection_empty" not in out


class TestCatalogRasterHeader:
    """产品族条目要能答出像元大小；盘上没有产物时绝不许编一个出来。"""

    def test_missing_products_return_empty(self, monkeypatch) -> None:
        import app.services.agent.server_tools_runtime as runtime

        monkeypatch.setattr(runtime, "_overlay_for_catalog_variable", lambda *a, **k: "")
        assert runtime._catalog_raster_header("method-smap-omega-doy-dynamic") == {}


class TestOutsideCoverageNote:
    """超范围不是「取数出错」。

    2026-11-07 实测：时间轴停在 2025-12-16，用户问「河南今天墒情怎么样」，模型按
    真实日期 2026-11-07 去取，拿到「取数服务返回错误…取数失败，不等于该日没有
    数据」，紧接着又自己补「最新只到 2026-02，那天本来就没有」——前后矛盾。
    """

    _KEYS = ["20250701_20250731", "20251219_20251226", "20260202_20260208"]

    def test_later_than_last_is_coverage_not_failure(self) -> None:
        from app.services.agent.server_tools_runtime import _outside_coverage_note

        note = _outside_coverage_note(self._KEYS, "20261107")
        assert note is not None
        assert "20260208" in note
        assert "不是取数失败" in note

    def test_earlier_than_first_is_coverage(self) -> None:
        from app.services.agent.server_tools_runtime import _outside_coverage_note

        note = _outside_coverage_note(self._KEYS, "20240101")
        assert note is not None
        assert "20250701" in note

    def test_inside_range_is_silent(self) -> None:
        from app.services.agent.server_tools_runtime import _outside_coverage_note

        assert _outside_coverage_note(self._KEYS, "20251220") is None

    def test_unknown_request_is_silent(self) -> None:
        from app.services.agent.server_tools_runtime import _outside_coverage_note

        assert _outside_coverage_note(self._KEYS, None) is None
        assert _outside_coverage_note([], "20261107") is None
