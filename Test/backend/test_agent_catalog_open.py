"""目录兜底与像元口径（2026-11-09 外部实测报告修复）。

外部测试报告两条：
1. 助手开场示例推荐「打开 CMFD 降水」，但该层不在页面活动层里，
   ``_resolve_layer`` 永远反问 ⇒ 示例指令与游客实际能力不一致。
   修：``_catalog_pick`` 从图层目录兜底一次，前端 set_layer_visibility
   本就支持「显示＝自动添加」。
2. 统计北京市土壤水分时报「边界内共 437 个像元」——437 = 23×19 读取窗口
   （含边界外），不是行政边界分母。修：正文只说 valid_pixels；
   工具返回带 total_pixels_note 说明口径。
"""

from __future__ import annotations

import pytest


class TestCatalogOpenFallback:
    """「打开 CMFD 降水」在页面没有该层时也应能打开（目录兜底）。"""

    def test_catalog_pick_hits_cmfd(self):
        from app.services.agent.mock_orchestrator import _catalog_pick

        pick = _catalog_pick("打开 CMFD 降水")
        assert pick is not None
        assert pick.catalog_id == "cmfd-precip-cn"
        assert pick.name == "CMFD 区域降水"

    def test_catalog_pick_rejects_unknown(self):
        from app.services.agent.mock_orchestrator import _catalog_pick

        assert _catalog_pick("打开一个根本不存在的图层xyzq") is None

    def test_open_cmfd_emits_add_intent(self):
        from app.services.agent.mock_orchestrator import mock_chat

        ctx = {
            "active_layers": [
                {
                    "catalog_id": "imported-38993117b963",
                    "name": "SMAP 平均散射约束产品 · 土壤水分",
                    "visible": True,
                    "selected": True,
                }
            ],
            "timeline": {"hour": 0, "date": "2025-07-15"},
        }
        r = mock_chat("打开 CMFD 降水", client_context=ctx, state={})
        intents = r.get("ui_intents") or []
        assert any(
            i.get("name") == "set_layer_visibility"
            and (i.get("args") or {}).get("catalog_id") == "cmfd-precip-cn"
            and (i.get("args") or {}).get("visible") is True
            for i in intents
        ), intents
        assert "已把" in (r.get("reply") or "")

    def test_open_page_layer_still_prefers_page(self):
        """页面上已有同名的层时仍优先页面层，不被目录兜底带偏。"""
        from app.services.agent.mock_orchestrator import mock_chat

        ctx = {
            "active_layers": [
                {
                    "catalog_id": "imported-38993117b963",
                    "name": "SMAP 平均散射约束产品 · 土壤水分",
                    "visible": True,
                    "selected": True,
                }
            ],
            "timeline": {"hour": 0, "date": "2025-07-15"},
        }
        r = mock_chat("隐藏土壤水分", client_context=ctx, state={})
        intents = r.get("ui_intents") or []
        assert any(
            i.get("name") == "set_layer_visibility"
            and (i.get("args") or {}).get("catalog_id") == "imported-38993117b963"
            for i in intents
        ), intents


class TestPixelDenominatorWording:
    """正文不把读取窗口总数（23×19=437）说成行政边界分母。"""

    def _stat_reply(self) -> str:
        from app.services.agent.mock_orchestrator import forced_statistics_reply

        ctx = {
            "active_layers": [
                {
                    "catalog_id": "imported-38993117b963",
                    "name": "SMAP 平均散射约束产品 · 土壤水分",
                    "visible": True,
                    "selected": True,
                }
            ],
            "timeline": {"hour": 0, "date": "2025-07-15"},
        }
        state = {
            "layer_id": "imported-38993117b963",
            "variable": "sm",
            "region": "北京市",
            "date": "20250701_20250731",
        }
        r = forced_statistics_reply(
            "统计北京市土壤水分", client_context=ctx, session_id="t", state=state
        )
        assert r and r.get("reply")
        return r["reply"]

    def test_reply_does_not_say_boundary_total(self):
        reply = self._stat_reply()
        assert "边界内共" not in reply
        # 不再出现「N / 437」式分母写法
        import re

        assert not re.search(r"有效像元[：:]\s*\d+\s*/\s*\d+", reply)

    def test_reply_states_valid_pixels_as_boundary_valid(self):
        reply = self._stat_reply()
        assert "边界内有效像元" in reply

    def test_tool_result_carries_note(self):
        """统计工具返回体带 total_pixels_note（geometry 路径）。"""
        import os
        import sys

        backend = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "Code", "backend")
        )
        if backend not in sys.path:
            sys.path.insert(0, backend)

        from app.services.agent import server_tools_runtime as rt

        AVG = "imported-38993117b963"
        ctx = {
            "active_catalog_ids": [AVG],
            "active_layers": [
                {
                    "catalog_id": AVG,
                    "overlay_layer_id": AVG,
                    "name": "SMAP 平均散射约束产品 · 土壤水分",
                    "visible": True,
                    "selected": True,
                }
            ],
            "selected_layer_id": AVG,
            "timeline": {"hour": 0, "date": "2025-07-15"},
        }
        r = rt._get_layer_statistics(
            {"catalog_id": AVG, "time": "20250701_20250731", "region": "北京市"},
            cred=None,
            user_message="统计北京市土壤水分",
            client_context=ctx,
            topic_state={"layer_id": AVG, "variable": "sm", "date": "20250701_20250731"},
        )
        note = str(r.get("total_pixels_note") or "")
        assert "读取窗口" in note
        assert "含行政区边界外" in note
