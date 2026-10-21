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
from app.services.agent.orchestrator import _synthesize_reply_from_tool_steps

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
