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


class TestProductGroupNotHiddenByPageCatalogId:
    """页面层的 catalog_id 是产品族 id 时，**不能**把整条族记录过滤掉。

    2026-11-08 r58 实测（3/3 复现）：页面只挂「SMAP 动态 · 土壤水分」，
    问「SMAP 动态的土壤水分和植被光学厚度分别是多少」，模型回答
    「本机现有产物里，SMAP 动态散射约束产品只挂了土壤水分这一层」，
    还建议用户「去数据管理页确认是否已生成植被光学厚度这一支产物」——
    而盘上 `imported-5427e1020d63`(VOD) / `imported-94501b455dcd`(ω)
    与 `imported-a8940443fd6d`(SM) 同 run、同 12 片，都在。

    根因：`_page_layer_index` 会把 `catalog_id` 也登记进索引，而
    `seen = set(page.keys())` 又把整份索引当「已在页面上」⇒ 族记录被过滤，
    模型看不到 `group_members` 里另外两个变量层的产物 id。族 id 只是
    「这层属于哪族」的标记，不等于「这一族本身已作为图层挂在页面上」。
    """

    _CTX = {
        "active_catalog_ids": ["method-smap-omega-doy-dynamic"],
        "active_layers": [
            {
                "catalog_id": "method-smap-omega-doy-dynamic",
                "overlay_layer_id": "imported-a8940443fd6d",
                "name": "SMAP 动态散射约束产品 · 土壤水分",
                "selected": True,
                "visible": True,
            }
        ],
    }

    def test_group_record_survives_page_catalog_id(self) -> None:
        from app.services.agent.server_tools_runtime import _search_layers

        out = _search_layers(
            {"query": "SMAP 动态 植被光学厚度", "limit": 20},
            cred=None,
            client_context=self._CTX,
        )
        ids = [str(e.get("layer_id") or "") for e in out.get("layers") or []]
        assert "method-smap-omega-doy-dynamic" in ids, (
            "产品族记录被页面 catalog_id 吃掉了，模型将看不到同族其它变量层的产物 id"
        )

    def test_group_record_carries_all_members(self) -> None:
        from app.services.agent.server_tools_runtime import _search_layers

        out = _search_layers(
            {"query": "SMAP 动态 植被光学厚度", "limit": 20},
            cred=None,
            client_context=self._CTX,
        )
        group = next(
            (
                e
                for e in out.get("layers") or []
                if e.get("layer_id") == "method-smap-omega-doy-dynamic"
            ),
            None,
        )
        assert group is not None
        assert group.get("is_product_group") is True
        # 盘上有产物才列（绝不编造）；本机三层俱在时必须一层不少
        members = group.get("group_members") or []
        codes = {str(m.get("variable_label") or "") for m in members}
        assert {"土壤水分", "植被光学厚度"} <= codes or members == [], (
            f"族成员不完整：{codes}"
        )

    def test_page_layer_not_duplicated(self) -> None:
        from app.services.agent.server_tools_runtime import _search_layers

        out = _search_layers(
            {"query": "SMAP 动态 植被光学厚度", "limit": 20},
            cred=None,
            client_context=self._CTX,
        )
        ids = [str(e.get("layer_id") or "") for e in out.get("layers") or []]
        assert ids.count("imported-a8940443fd6d") <= 1, "页面上那一层被重复列出"


class TestShrinkKeepsStatistics:
    """早期轮次的工具返回被截断时，数值不能丢。

    2026-11-08 r59-d2 实测：一份 1994 字符的统计返回，`mean` 在 318 位、
    `value_basis` 在 1075、`min` 在 1585、`max` 在 1614、`std` 在 1641。
    阈值曾为 700，按位置截就把极值与时间口径全切掉，模型跳到第 4 跳只能回
    「均值、有效像元数这些数字没有回传上来」。现在阈值抬到 2000，这类返回整份保留。
    """

    @staticmethod
    def _stat_payload() -> str:
        import json

        # 模拟真实统计返回：外层元信息很长，数值字段排在最后
        payload = {
            "ok": True,
            "catalog_id": "imported-a8940443fd6d",
            "resolved_layer_id": "",
            "display_name": "SMAP 动态散射约束产品 · 土壤水分",
            "answer_lead": "我按「SMAP 动态散射约束产品 · 土壤水分」取数",
            "scope": "full_extent",
            "requested_bbox": None,
            "region": None,
            "region_level": None,
            "region_geometry_crs": "WGS84",
            # 真实返回里 temporal_summary 约 1290 字符，是「数值字段排在最后」的主因
            "temporal_summary": "共 12 个时间片，" + "填充" * 650,
            "actual_time": "20251216",
            "period_start": "20251216",
            "period_end": "20251216",
            "time_source": "page",
            "is_daily_frame": True,
            "value_basis": {"kind": "ondemand_frame", "note": "按需补出的单日帧"},
            "valid_count": 363201,
            "mean": 0.16531404,
            "min": 0.02,
            "max": 0.8076871,
            "std": 0.11518533,
        }
        return json.dumps(payload, ensure_ascii=False)

    def test_typical_statistics_survive_untouched(self) -> None:
        """典型统计返回（约 2000 字符）不应被截断，数值与时间口径必须都在。"""
        from app.services.agent.orchestrator import _shrink_tool_text

        text = self._stat_payload()
        assert len(text) > 1500, "样本要接近真实长度才有意义"
        out = _shrink_tool_text(text)
        assert out == text, "典型统计返回被截断了"
        for key in ("mean", "min", "max", "std", "valid_count", "value_basis", "period_start"):
            assert f'"{key}"' in out, f"丢了关键字段 {key}"

    def test_numbers_are_still_parseable(self) -> None:
        """压缩后仍应是可用 JSON（至少要能读到数值），不是切一半的残片。"""
        import json

        from app.services.agent.orchestrator import _shrink_tool_text

        out = _shrink_tool_text(self._stat_payload())
        parsed = json.loads(out)
        assert parsed["mean"] == 0.16531404
        assert parsed["max"] == 0.8076871

    def test_overlong_text_truncated_with_note(self) -> None:
        from app.services.agent.orchestrator import (
            _TOOL_RESULT_KEEP_CHARS,
            _shrink_tool_text,
        )

        text = "错误：" + "x" * (_TOOL_RESULT_KEEP_CHARS * 2)
        out = _shrink_tool_text(text)
        assert out.startswith("错误：")
        assert "已省略" in out
        assert len(out) < len(text)

    def test_short_text_untouched(self) -> None:
        from app.services.agent.orchestrator import _shrink_tool_text

        text = '{"ok": true}'
        assert _shrink_tool_text(text) == text


class TestRoundingTolerance:
    """模型把参考值四舍五入（0.0593→0.059）不是编造。

    2026-11-07 实测 R（重启后第三次复验）：正文写「标准差 0.059、最小 0.082」，
    工具返回 0.0593 / 0.0820，3 位有效数字比较因两边位数不同全对不上，整段被
    重写成模板句——用户问的百分比换算随之丢失。
    """

    def test_short_rounding_matches(self) -> None:
        from app.services.agent.orchestrator import _number_matches

        assert _number_matches(0.059, {0.0593}) is True
        assert _number_matches(0.082, {0.08204}) is True
        assert _number_matches(0.456, {0.45638}) is True

    def test_wrong_number_still_rejected(self) -> None:
        from app.services.agent.orchestrator import _number_matches

        assert _number_matches(0.293, {0.2025}) is False
        assert _number_matches(163.0, {1995.0}) is False

    def test_small_value_two_decimal_rounding(self) -> None:
        """0.0295 写成 0.03 是「保留 2 位小数」的正常转写，不该判成编造。

        2026-11-07 实测新疆：模型把标准差 0.0295 写成 0.03，绝对差 0.0005、
        肉眼完全一样，但相对差 1.7% 超过 0.6% 阈值 ⇒ 整段被重写成模板句。
        """
        from app.services.agent.orchestrator import _number_matches

        assert _number_matches(0.03, {0.0295}) is True
        assert _number_matches(0.021, {0.0208}) is True

    def test_mid_value_two_decimal_rounding(self) -> None:
        """0.165→0.17、0.808→0.81 是「保留 2 位小数」的正常转写，不该判编造。

        2026-11-07 实测 c（问「有没有 0 或负值」）：模型把整幅均值 0.165 写成
        0.17、最大值 0.808 写成 0.81。0.165 恰好 >0.1，吃不到原来「|ref|<0.1」
        的绝对误差兜底，相对误差 3% 又超 0.6%，整段被换成模板句。舍入误差是绝对
        的（round(x,2) 误差 ≤0.005），与数值大小无关，故取消 <0.1 门槛。
        """
        from app.services.agent.orchestrator import _number_matches

        assert _number_matches(0.17, {0.165}) is True
        assert _number_matches(0.81, {0.808}) is True

    def test_absolute_tolerance_does_not_loosen_real_errors(self) -> None:
        """绝对误差兜底只容「保留 2 位小数」的舍入（≤0.006），换整套数仍拦。"""
        from app.services.agent.orchestrator import _number_matches

        assert _number_matches(0.293, {0.2025}) is False
        assert _number_matches(0.1507, {0.2025}) is False
        assert _number_matches(0.30, {0.2025}) is False

    def test_reply_with_rounded_stats_is_kept(self) -> None:
        stats = {
            **_SM_1216,
            "min": 0.08204492181539536,
            "max": 0.45637741684913635,
            "std": 0.0593,
        }
        reply = (
            "按河南省行政边界，2025-12-16 平均值 0.2025 m³/m³，"
            "最小 0.082、最大 0.456，标准差 0.059，有效像元 1995 个。"
        )
        out, changed = _guard_reply_numbers(reply, _tool_steps(stats))
        assert changed is False
        assert out == reply


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
        # 2026-11-07 r42-h：模型看到「不是取数出错」后仍补了一句「按需补取也失败，
        # 属于取数失败」，同一段话自相矛盾。文案里必须直接否掉「取数失败」这个词。
        assert "不是取数失败" in note

    def test_inside_range_is_silent(self) -> None:
        from app.services.agent.server_tools_runtime import _outside_coverage_note

        assert _outside_coverage_note(self._KEYS, "20251220") is None

    def test_unknown_request_is_silent(self) -> None:
        from app.services.agent.server_tools_runtime import _outside_coverage_note

        assert _outside_coverage_note(self._KEYS, None) is None
        assert _outside_coverage_note([], "20261107") is None


class TestPercentHint:
    """规则引擎接管时，「换算成百分比」也要答到点上。

    2026-11-07 实测 r33：模型这一轮没调任何取数工具，按设计由规则引擎出数，
    答复里只有「均值：0.2025」，用户问的百分比没答。只对体积含水量成立。
    """

    def test_volume_water_content_is_converted(self) -> None:
        from app.services.agent.mock_orchestrator import _percent_hint

        hint = _percent_hint("m³/m³", 0.2025, "把河南省这个平均值换算成百分比是多少？")
        assert hint is not None
        assert "20.25%" in hint

    def test_dimensionless_is_not_converted(self) -> None:
        from app.services.agent.mock_orchestrator import _percent_hint

        assert _percent_hint("1", 0.1507, "换算成百分比") is None
        assert _percent_hint("无量纲", 0.1507, "换算成百分比") is None

    def test_not_asked_is_silent(self) -> None:
        from app.services.agent.mock_orchestrator import _percent_hint

        assert _percent_hint("m³/m³", 0.2025, "这天的平均值是多少") is None

    def test_missing_mean_is_silent(self) -> None:
        from app.services.agent.mock_orchestrator import _percent_hint

        assert _percent_hint("m³/m³", None, "换算成百分比") is None


class TestGivenValueConversion:
    """「把 0.2025 换成每亩多少吨水」不是一次新取数。

    2026-11-07 r42-i 实测：句中的「多少」命中 _STATISTICS_WORDS，规则引擎整段
    换成整幅统计（0.1653 m³/m³ / 363201 个有效像元 / 5.8%），一个都没回答他问的
    换算；正确做法是说明「换成水量需要容重和土层厚度，这一层没有」。
    判据必须「有换算动词」且「消息里已经给了小数」——R 那种「把这个平均值换算成
    百分比是多少」没给数值，仍要走统计取数，不能被误伤。
    """

    def test_given_value_conversion_is_not_statistics(self) -> None:
        from app.services.agent.orchestrator import _wants_statistics

        assert _wants_statistics("把 0.2025 换成每亩多少吨水，可以吗？") is False

    def test_conversion_without_given_value_still_statistics(self) -> None:
        from app.services.agent.orchestrator import _wants_statistics

        assert _wants_statistics("把河南省这个平均值换算成百分比是多少？") is True

    def test_plain_statistics_still_statistics(self) -> None:
        from app.services.agent.orchestrator import _wants_statistics

        assert _wants_statistics("河南省 2025-12-16 的土壤水分平均值是多少") is True
        assert _wants_statistics("那最大值呢？") is True

    def test_detector_requires_both_parts(self) -> None:
        from app.services.agent.orchestrator import _is_given_value_conversion

        assert _is_given_value_conversion("0.203 折合多少毫米") is True
        assert _is_given_value_conversion("换算成百分比") is False
        assert _is_given_value_conversion("0.203 这一天怎么样") is False


class TestExtremeHint:
    """问「那最大值呢」时把值点出来，别只给一个区间让用户自己找。

    2026-11-07 r42-j 实测：规则引擎接管后只回「范围：0.0820 ~ 0.4564」，答案藏在
    区间右端，前面还压着一条无关的均值。
    """

    _RES = {"min": 0.08204492181539536, "max": 0.45637741684913635}

    def test_max_is_named(self) -> None:
        from app.services.agent.mock_orchestrator import _extreme_hint

        hint = _extreme_hint("m³/m³", self._RES, "那最大值呢？")
        assert hint is not None
        assert "0.4564" in hint
        assert "m³/m³" in hint

    def test_min_is_named(self) -> None:
        from app.services.agent.mock_orchestrator import _extreme_hint

        hint = _extreme_hint("m³/m³", self._RES, "这边最低多少")
        assert hint is not None
        assert "0.0820" in hint

    def test_dimensionless_has_no_unit_suffix(self) -> None:
        from app.services.agent.mock_orchestrator import _extreme_hint

        hint = _extreme_hint("1", self._RES, "最大值是多少")
        assert hint is not None
        assert " m³/m³" not in hint
        assert "1" not in hint.replace("0.4564", "")

    def test_not_asked_is_silent(self) -> None:
        from app.services.agent.mock_orchestrator import _extreme_hint

        assert _extreme_hint("m³/m³", self._RES, "河南省的均值是多少") is None

    def test_missing_value_is_silent(self) -> None:
        from app.services.agent.mock_orchestrator import _extreme_hint

        assert _extreme_hint("m³/m³", {"min": None, "max": None}, "最大值") is None


class TestOverBudgetReplyWording:
    """预算超限的对外文案不许讲内部机制。

    2026-11-08 实测：问「哪些省的土壤水分比较高？给我前三个」，模型逐省循环调统计，
    累积 51353 token 被中止，旧文案回答「累计输入超过了单次上限，中途停下」还教用户
    「先在左侧把要问的那一层点上」——把用户带进系统内部视角，且依然拿不到答案。
    """

    def test_no_internal_mechanism_in_reply(self) -> None:
        from app.services.agent.orchestrator import _llm_down_reply

        out = _llm_down_reply("工具多轮累计输入预估约 51353 token，超过单次上限 40000 token，已中止。")
        for banned in ("token", "上限", "工具调用", "左侧", "选中"):
            assert banned not in out, f"对外文案不该出现内部机制用词：{banned}"

    def test_tells_user_how_to_narrow(self) -> None:
        from app.services.agent.orchestrator import _llm_down_reply

        out = _llm_down_reply("工具多轮累计输入预估约 51353 token，超过单次上限 40000 token，已中止。")
        assert "2~3" in out or "2-3" in out, "要告诉用户一次点名几个区域"
        assert "平均值" in out, "要给出可照抄的问法示例"


class TestVersionSwitchBeatsInheritance:
    """用户明确点名换口径时，产品粘性必须放行，不能让会话继承把它改回去。

    2026-11-08 用户复测报「同一会话换版失效」：先说动态版查广州 11-09~16（0.1482），
    追问「改用平均版」后答复称已换版、执行记录仍取动态版。本地 8/8 未能复现，
    但代码里确有两处结构性缺口会让它偶发：
      ① 提示词「不要重新挑」那条没配例外，模型容易把「改用平均版」也当成
         「别重挑，沿用上一轮」；
      ② `_VERSION_MENTION_RE['average']` 没有「季均」，而页面上那一组的
         catalog 正是 `method-smap-season-mean`（family=average）⇒ 用户说
         「改用季均版」时认不出是点名换口径，被粘性改回动态版。
    """

    def test_version_words_are_recognized(self) -> None:
        from app.services.agent.server_tools_runtime import _mentions_version

        for msg in ("改用平均版", "换成季节平均那套", "改用季均版", "切到季均"):
            assert _mentions_version(msg, "average") is True, f"没认出点名平均口径：{msg}"
        assert _mentions_version("切到动态版", "dynamic") is True

    def test_plain_statistics_words_are_not_version_switch(self) -> None:
        """「平均值是多少」是统计请求，绝不能当成「换平均版」（2026-11-06 同类坑）。"""
        from app.services.agent.server_tools_runtime import _mentions_version

        for msg in ("平均值是多少", "改用平均值", "这层的平均是多少", "换成广州呢"):
            assert _mentions_version(msg, "average") is False, f"误判成换口径：{msg}"

    def test_sticky_releases_on_version_switch(self, monkeypatch) -> None:
        """上一轮是动态版、这轮点名平均版 ⇒ 粘性必须放行到平均版。

        身份解析依赖盘上产物目录，测试环境把数据根指到了临时目录，所以这里
        注入假的身份解析，只验证「判定逻辑」本身。
        """
        from app.services.agent import server_tools_runtime as rt

        def fake_identity(layer_id: str, _ctx) -> tuple[str, dict[str, str]]:
            family = "dynamic" if "a894" in layer_id else "average"
            return layer_id, {"variable": "sm", "source": "smap", "product_family": family}

        monkeypatch.setattr(rt, "_identity_of", fake_identity)
        monkeypatch.setattr(
            rt, "_baseline_layer_id", lambda _st, _ctx: "imported-a8940443fd6d"
        )
        used, note = rt._product_sticky_layer(
            "imported-136c60293bbf",
            topic_state={"layer_id": "imported-a8940443fd6d"},
            user_message="改用平均版。",
            client_context={"active_layers": []},
        )
        assert note is None, "点名换口径却被粘性改回上一轮"
        assert used == "imported-136c60293bbf"

    def test_sticky_still_holds_when_nothing_named(self, monkeypatch) -> None:
        """没点名任何项（只换区域）时必须继续粘住上一轮那层。"""
        from app.services.agent import server_tools_runtime as rt

        def fake_identity(layer_id: str, _ctx) -> tuple[str, dict[str, str]]:
            family = "dynamic" if "a894" in layer_id else "average"
            return layer_id, {"variable": "sm", "source": "smap", "product_family": family}

        monkeypatch.setattr(rt, "_identity_of", fake_identity)
        monkeypatch.setattr(
            rt, "_baseline_layer_id", lambda _st, _ctx: "imported-a8940443fd6d"
        )
        used, note = rt._product_sticky_layer(
            "imported-136c60293bbf",
            topic_state={"layer_id": "imported-a8940443fd6d"},
            user_message="换成广州呢？",
            client_context={"active_layers": []},
        )
        assert note is not None, "只换区域时不该换产品"
        assert used == "imported-a8940443fd6d"


class TestBackrefWithoutHistory:
    """首轮就引用「刚才/上一轮」⇒ 必须澄清，不许重算一遍伪造跨轮连续性。

    2026-11-08 实测 r62-h：新会话第一句问「刚才我问的那个数是多少来着？」，
    规则引擎按页面选中层重算了一遍，正文还写「本轮没有重新指定的部分沿用上一轮」。
    数值本身没错（就是当前层的整幅均值），但「沿用上一轮」是不实说法 ⇒
    用户会以为跨会话记得历史。判据：含明确回指词 + state 里无可继承上文。
    """

    def test_first_turn_backref_is_clarified(self) -> None:
        from app.services.agent.orchestrator import (
            _MISSING_HISTORY_REPLY,
            _statistics_fallback_reply,
        )

        reply, patch = _statistics_fallback_reply(
            "刚才我问的那个数是多少来着？",
            "整层均值 0.1653 m³/m³",
            [],
            "t-backref",
            {"active_layers": []},
            state=None,
        )
        assert reply == _MISSING_HISTORY_REPLY
        assert "0.1653" not in reply, "不许把重算的数字当「上一轮的数」给出来"
        assert patch is None

    def test_empty_state_backref_is_clarified(self) -> None:
        from app.services.agent.orchestrator import _refers_to_missing_history

        assert _refers_to_missing_history("上一轮那个平均值是多少", {}) is True
        assert _refers_to_missing_history("刚才那个数是多少", {"layer_id": ""}) is True

    def test_with_state_is_not_treated_as_missing(self) -> None:
        """真有上文（state 记着层）时，回指是正常的，不能拦。"""
        from app.services.agent.orchestrator import _refers_to_missing_history

        state = {"layer_id": "imported-a8940443fd6d", "layer_name": "SMAP 动态 · 土壤水分"}
        assert _refers_to_missing_history("刚才那个数是多少", state) is False

    def test_plain_question_untouched(self) -> None:
        """不带回指词的正常提问一律不碰。"""
        from app.services.agent.orchestrator import _refers_to_missing_history

        assert _refers_to_missing_history("这一层的平均值是多少", None) is False
        assert _refers_to_missing_history("河南省的土壤水分平均值", {}) is False

    def test_page_layer_patch_is_not_history(self) -> None:
        """本轮补进状态的页面层不算「上文」，首轮回指仍须澄清。

        2026-11-08 实测 r65-C：新会话第一句「刚才那个平均值是多少来着？」仍然
        报出整层均值 0.1653 并写「沿用上一轮」。原因是 ``_state_patch_from_message``
        在本轮开头就把**页面选中层**补成基线（为了「其余不变」能继承），于是传到
        兜底的 ``state`` 非空 ⇒ 回指判断误以为真有上文。判据必须用**进本轮之前**
        的快照 ``history_state``，不能用合并后的 ``state``。
        """
        from app.services.agent.orchestrator import (
            _MISSING_HISTORY_REPLY,
            _statistics_fallback_reply,
        )

        state_after_patch = {
            "layer_id": "imported-a8940443fd6d",
            "layer_name": "SMAP 动态散射约束产品 · 土壤水分",
        }
        reply, patch = _statistics_fallback_reply(
            "刚才那个平均值是多少来着？",
            "整层均值 0.1653 m³/m³",
            [],
            "t-backref-page",
            {"active_layers": []},
            state=state_after_patch,
            history_state={},
        )
        assert reply == _MISSING_HISTORY_REPLY
        assert "0.1653" not in reply
        assert "沿用上一轮" not in reply, "首轮没有上一轮，不许这么写"
        assert patch is None

    def test_real_history_still_allowed(self) -> None:
        """真有上文时（history_state 非空），回指照旧放行到取数逻辑。"""
        from app.services.agent.orchestrator import _refers_to_missing_history

        state = {"layer_id": "imported-a8940443fd6d"}
        assert _refers_to_missing_history("刚才那个数是多少", state) is False


class TestGuardUnclaimedViewIntent:
    """写视图请求若一条意图都没下发，正文不许写成「已下发/已移除」完成态。

    2026-11-07 实测 r56/r58/r59：问「把这个图层删掉」，4 次里 2 次模型不调任何
    工具、不下发 remove_layer，却回「已下发移除…请求」——前端拿不到指令，画面
    纹丝不动，用户以为删成功了。判据三重同时成立才纠正：①消息含写视图动词
    ②本轮 ui_intents 为空 ③正文写完成态。三者缺一不动。
    """

    def test_unclaimed_view_write_is_corrected(self) -> None:
        from app.services.agent.orchestrator import _guard_unclaimed_view_intent

        out = _guard_unclaimed_view_intent(
            "把这个图层删掉。",
            {"reply": "已下发移除「SMAP 土壤水分」，它已从面板摘掉。", "ui_intents": []},
        )
        assert "没能把操作下发" in out["reply"]
        assert "已移除" not in out["reply"]

    def test_intent_present_is_untouched(self) -> None:
        from app.services.agent.orchestrator import _guard_unclaimed_view_intent

        reply = "已下发移除「SMAP 土壤水分」，执行结果以页面提示为准。"
        out = _guard_unclaimed_view_intent(
            "把这个图层删掉。",
            {"reply": reply, "ui_intents": [{"name": "remove_layer", "args": {}}]},
        )
        assert out["reply"] == reply

    def test_read_only_question_is_untouched(self) -> None:
        from app.services.agent.orchestrator import _guard_unclaimed_view_intent

        reply = "河南省 2025-12-16 均值 0.203 m³/m³。"
        out = _guard_unclaimed_view_intent("河南的均值是多少", {"reply": reply, "ui_intents": []})
        assert out["reply"] == reply

    def test_no_done_word_is_untouched(self) -> None:
        from app.services.agent.orchestrator import _guard_unclaimed_view_intent

        reply = "这一层正在计算中，暂时移除不了。"
        out = _guard_unclaimed_view_intent(
            "把这个图层删掉。", {"reply": reply, "ui_intents": []}
        )
        assert out["reply"] == reply

    def test_transitive_done_phrase_is_corrected(self) -> None:
        """2026-11-08 实测 r57-h1：模型回「已把「…」从图层面板移除」——
        「已把…移除」是及物完成态变体，不命中旧正则「已移除」，漏网成空口承诺。"""
        from app.services.agent.orchestrator import _guard_unclaimed_view_intent

        out = _guard_unclaimed_view_intent(
            "把这个图层删掉。",
            {"reply": "已把「SMAP 动态散射约束产品 · 土壤水分」从图层面板移除。", "ui_intents": []},
        )
        assert "没能把操作下发" in out["reply"]
