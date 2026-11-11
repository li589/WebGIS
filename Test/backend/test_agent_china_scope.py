# -*- coding: utf-8 -*-
"""「中国 / 全国」范围口径 + 底图切换规则直出（2026-11-10 线上实测两条 P0）。

两件事：

1. P0-2：问「中国区域 / 全国 / 中国境内」的平均土壤水分，模型把「中国」当成
   没有行政区、静默落到全球整幅栅格（SMAP 是全球产品），把全球均值 0.153
   当成中国值回给用户。系统只有省级和地级市掩膜、没有「中国全境」这一级，
   所以必须在正文点明「算的是全球整幅，不是中国范围」。

2. P0-1：问「切换为天地图影像」等底图切换指令，模型不调工具却回「已下发」
   （completion_tokens=18）。底图切换是确定性界面操作，应走规则引擎直出
   switch_basemap，绝不外呼模型。
"""

import re
from unittest.mock import Mock

from app.services.agent import orchestrator as orch
from app.services.agent.orchestrator import (
    _append_region_scope_note,
    _mentions_china_scope,
)


class TestMentionsChinaScope:
    def test_china_words_are_detected(self):
        for msg in (
            "中国区域的平均土壤水分是多少",
            "全国的平均土壤水分是多少",
            "中国境内的平均土壤水分",
            "我国平均土壤水分",
            "中国全境的平均土壤水分",
        ):
            assert _mentions_china_scope(msg) is True, msg

    def test_non_china_words_are_not_detected(self):
        for msg in (
            "河南省的平均土壤水分",
            "广州市的平均土壤水分",
            "各省份的平均土壤水分",
            "整幅栅格的平均值",
        ):
            assert _mentions_china_scope(msg) is False, msg

    def test_institution_names_are_not_detected(self):
        """「中国气象局」「中国科学院」是机构名，不是统计范围，不能误伤。"""
        for msg in (
            "中国气象局发布的土壤水分产品",
            "中国科学院的数据",
        ):
            assert _mentions_china_scope(msg) is False, msg


class TestChinaScopeNote:
    def test_china_scope_with_global_raster_gets_named(self):
        reply = "整层的只读统计：\n- 均值：0.153 m³/m³"
        out = _append_region_scope_note("中国区域的平均土壤水分是多少", reply, [])
        assert "全球整幅栅格" in out
        assert "省级和地级市" in out

    def test_china_scope_already_explained_is_not_repeated(self):
        reply = "上面的数是按全球整幅栅格算的，不是中国范围。均值 0.153 m³/m³"
        out = _append_region_scope_note("全国的平均土壤水分", reply, [])
        assert out == reply

    def test_province_scope_is_not_flagged(self):
        """「河南省」是真正的行政区，有 region 统计时不该挂中国口径。"""
        reply = "按「河南省」行政边界：均值 0.2484 m³/m³"
        out = _append_region_scope_note("河南省的平均土壤水分", reply, [])
        assert "全球整幅栅格" not in out

    def test_no_false_positive_on_normal_turns(self):
        for msg in (
            "把时间轴调到2025年11月",
            "你能做什么？",
            "这个图层是什么数据？",
            "换成河南省呢",
        ):
            assert _append_region_scope_note(msg, "正常回复", []) == "正常回复", msg


class TestBasemapSwitchSkipsModel:
    """P0-1：底图切换是确定性界面操作，走规则引擎直出，不外呼模型。"""

    def test_switch_basemap_skips_model(self, monkeypatch):
        from app.services.agent import orchestrator

        model_call = Mock(side_effect=AssertionError("the model must not be called"))
        monkeypatch.setattr(
            orchestrator,
            "get_effective_profile_raw",
            lambda **_: {
                "id": "test-model",
                "protocol": "openai",
                "provider_kind": "openai",
                "context_window_input": 4000,
            },
        )
        monkeypatch.setattr(orchestrator, "load_topic_state", lambda **_: {})
        monkeypatch.setattr(orchestrator, "load_history", lambda **_: [])
        monkeypatch.setattr(orchestrator, "append_turn", lambda **_: None)
        monkeypatch.setattr(orchestrator, "get_profile_api_key", model_call)

        result = orchestrator._run_chat_impl("切换为天地图影像")

        assert result["provider"] == "openai-basemap-rule"
        assert result["ui_intents"] == [
            {"name": "switch_basemap", "args": {"basemap_id": "tianditu-img"}}
        ]
        assert result["usage"]["total_tokens"] < 300
        model_call.assert_not_called()

    def test_all_frontend_shortcut_phrasings_skip_model(self, monkeypatch):
        """前端快捷指令原文 4 种说法，都必须被规则直出拦住，不能空口承诺。"""
        from app.services.agent import orchestrator

        phrases = (
            "切换为天地图影像",
            "切换到天地图影像底图",
            "换成天地图影像底图",
            "切换为高德街道底图",
        )
        for phrase in phrases:
            model_call = Mock(
                side_effect=AssertionError("the model must not be called")
            )
            monkeypatch.setattr(
                orchestrator,
                "get_effective_profile_raw",
                lambda **_: {
                    "id": "test-model",
                    "protocol": "openai",
                    "provider_kind": "openai",
                    "context_window_input": 4000,
                },
            )
            monkeypatch.setattr(orchestrator, "load_topic_state", lambda **_: {})
            monkeypatch.setattr(orchestrator, "load_history", lambda **_: [])
            monkeypatch.setattr(orchestrator, "append_turn", lambda **_: None)
            monkeypatch.setattr(orchestrator, "get_profile_api_key", model_call)

            result = orchestrator._run_chat_impl(phrase)
            intents = result.get("ui_intents") or []
            assert any(
                str(i.get("name")) == "switch_basemap" for i in intents
            ), phrase
            model_call.assert_not_called()


class TestBasemapIntentSurvivesReadOnlyGuard:
    """补「切换」进 _VIEW_WRITE_VERBS 后，底图切换意图不能被只读守卫剥掉。

    2026-11-10 线上探针实测：规则直出 switch_basemap 后，被外层
    ``_guard_read_only_ui_intents`` 当成「只读查询顺手改图」剥掉，ui_intents
    变空、正文还追加「本次是只读查询…」与「已切换」自相矛盾。根因是
    ``_VIEW_WRITE_VERBS`` 漏了「切换为/切换成」这种动词在前、目标在后的语序。
    """

    def test_view_write_verbs_match_basemap_phrasings(self):
        for msg in (
            "切换为天地图影像",
            "切换到天地图影像底图",
            "换成天地图影像底图",
            "切换成高德街道底图",
        ):
            assert orch._VIEW_WRITE_VERBS.search(msg), msg

    def test_read_only_guard_keeps_switch_basemap(self):
        result = {
            "reply": "已切换到天地图影像底图。",
            "ui_intents": [
                {"name": "switch_basemap", "args": {"basemap_id": "tianditu-img"}}
            ],
        }
        out = orch._guard_read_only_ui_intents("切换为天地图影像", result)
        assert out["ui_intents"] == result["ui_intents"]
        assert "本次是只读查询" not in out["reply"]


class TestChinaScopeStatsSkipsModel:
    """「中国/全国」作为统计范围走规则直出，绝不沿用上一轮区域、不调模型。

    2026-11-10 线上实测：先问河北、再问「中国区域」，模型把「中国」沿用成
    河北（0.2403），正文按河北算、补丁又说全球整幅，自相矛盾。根因是
    ``_NO_REGION_RE`` 只认「全国」不认「中国」，沿用分支把「中国」漏过去。
    现在入口层直接识别「中国/全国 + 取数词」，规则直出并给出替代口径。
    """

    def test_china_scope_stats_skips_model(self, monkeypatch):
        from app.services.agent import orchestrator

        model_call = Mock(side_effect=AssertionError("the model must not be called"))
        monkeypatch.setattr(
            orchestrator,
            "get_effective_profile_raw",
            lambda **_: {
                "id": "test-model",
                "protocol": "openai",
                "provider_kind": "openai",
                "context_window_input": 4000,
            },
        )
        monkeypatch.setattr(orchestrator, "load_topic_state", lambda **_: {})
        monkeypatch.setattr(orchestrator, "load_history", lambda **_: [])
        monkeypatch.setattr(orchestrator, "append_turn", lambda **_: None)
        monkeypatch.setattr(orchestrator, "get_profile_api_key", model_call)

        result = orchestrator._run_chat_impl("中国区域的平均土壤水分是多少")

        assert result["provider"] == "openai-china-scope-rule"
        assert "省级和地级市" in result["reply"]
        assert "没有取数" in result["reply"]
        # 绝不出现上一轮区域名（河北），也绝不算成全球
        assert "河北" not in result["reply"]
        model_call.assert_not_called()

    def test_china_scope_does_not_trigger_on_pure_view(self, monkeypatch):
        """「缩放到中国」是视图操作，不带取数词，不能误入取数拦截。"""
        # 只验证判定条件本身：纯视图句不含取数词，china_scope_stats 不应命中
        msg = "缩放到中国全境"
        china_stats = bool(
            orch._mentions_china_scope(msg)
            and re.search(r"查询|统计|计算|均值|平均值|多少|数值|取数|平均", msg)
        )
        assert china_stats is False


class TestTotalTimeout:
    """整轮总超时配置解析（2026-11-10 老师实测一轮 27s+ 还在等待）。"""

    def test_default_is_120(self, monkeypatch):
        monkeypatch.delenv("BACKEND_AGENT_TOTAL_TIMEOUT", raising=False)
        assert orch._total_timeout_seconds() == 120.0

    def test_explicit_value(self, monkeypatch):
        monkeypatch.setenv("BACKEND_AGENT_TOTAL_TIMEOUT", "90")
        assert orch._total_timeout_seconds() == 90.0

    def test_zero_disables(self, monkeypatch):
        monkeypatch.setenv("BACKEND_AGENT_TOTAL_TIMEOUT", "0")
        assert orch._total_timeout_seconds() == 0.0

    def test_invalid_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("BACKEND_AGENT_TOTAL_TIMEOUT", "abc")
        assert orch._total_timeout_seconds() == 120.0

    def test_clamped_to_lower_bound(self, monkeypatch):
        monkeypatch.setenv("BACKEND_AGENT_TOTAL_TIMEOUT", "5")
        assert orch._total_timeout_seconds() == 15.0
