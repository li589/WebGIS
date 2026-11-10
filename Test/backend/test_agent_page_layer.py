# -*- coding: utf-8 -*-
"""取数对象的三条规则（2026-11-09 用户复测引入）。

外部反馈原文：「明确说『查当前图层』时，助手知道页面选的是风云 VOD，统计工具却
仍用了上轮的 SMAP 土壤水分。」并给出规则：

1. **点名产品** ⇒ 就查该产品；
2. **点名「当前图层」** ⇒ 就查页面选中的图层；
3. **只改日期或区域** ⇒ 沿用上一条实际统计的产品。

第 1、3 条在 ``_product_sticky_layer`` 里早已有判定（点名来源/变量/口径放行、
其余粘回基线），第 2 条**完全没有**——「查当前图层」既不点来源也不点变量，
于是被当成「没点名换产品」，粘回上一轮的 SMAP 土壤水分（实测 0.2929/163，
页面选中的风云 VOD 是 0.4134/8）。层名、数值、像元数全都合法，用户看不出取错。
"""

from __future__ import annotations

from app.services.agent.server_tools_runtime import (
    _asks_page_layer,
    _page_selected_layer_id,
    _product_sticky_layer,
)

SMAP_SM = "imported-38993117b963"  # 上一轮实际统计过的 SMAP 平均 · 土壤水分
FY_VOD = "imported-a94205dad5f9"  # 页面选中的风云平均 · 植被光学厚度
FY_VOD_DYN = "imported-731b37b59c97"  # 同族另一口径（用来模拟模型传错层）

STATE = {
    "layer_id": SMAP_SM,
    "layer_name": "SMAP 平均散射约束产品 · 土壤水分",
    "variable": "sm",
    "region": "河南省",
    "date": "2025-12-15",
}


def _page(selected_id: str, layers: list[tuple[str, bool]]):
    return {
        "active_catalog_ids": [cid for cid, _ in layers],
        "active_layers": [
            {
                "catalog_id": cid,
                "name": cid,
                "overlay_layer_id": cid,
                "visible": True,
                "selected": selected,
            }
            for cid, selected in layers
        ],
        "timeline": {"hour": 0, "date": "2025-12-15", "playing": False},
        "selected_layer_id": selected_id,
    }


PAGE = _page(FY_VOD, [(FY_VOD, True), (SMAP_SM, False)])


class TestAsksPageLayer:
    """哪些说法算「点名当前图层」。"""

    def test_recognises_explicit_phrases(self):
        for msg in (
            "查一下当前图层的均值",
            "查当前图层，统计河南省 2025-12-15",
            "帮我看下页面现在选中这层的均值",
            "就用当前图层算一下河南省",
            "地图上这层，河南省 12月15日 的均值",
            "看选中那层的值",
        ):
            assert _asks_page_layer(msg) is True, msg

    def test_does_not_hijack_plain_followups(self):
        """「这层 / 那层」单独出现时指上一轮，不能被当成页面选中层。"""
        for msg in (
            "那 2025-12-16 呢",
            "换成河南省呢",
            "只把统计日期改成 2025-12-16",
            "那 VOD 呢",
            "改用 SMAP 平均散射约束产品",
        ):
            assert _asks_page_layer(msg) is False, msg


class TestPageSelectedLayer:
    def test_returns_the_selected_runtime_layer(self):
        assert _page_selected_layer_id(PAGE) == FY_VOD

    def test_ignores_visible_but_unselected_layers(self):
        """可见 ≠ 选中：只有 visible 层时不能冒充页面选中层。"""
        page = _page("", [(FY_VOD, False), (SMAP_SM, False)])
        assert _page_selected_layer_id(page) == ""

    def test_tolerates_imports_prefix(self):
        page = _page("", [(FY_VOD, True)])
        page["active_layers"][0]["overlay_layer_id"] = f"imports/{FY_VOD}"
        assert _page_selected_layer_id(page) == FY_VOD

    def test_multiple_selected_falls_back_to_top_level(self):
        page = _page(FY_VOD, [(FY_VOD, True), (SMAP_SM, True)])
        assert _page_selected_layer_id(page) == FY_VOD

    def test_empty_context(self):
        assert _page_selected_layer_id(None) == ""
        assert _page_selected_layer_id({}) == ""


class TestThreeRules:
    def test_rule2_page_layer_wins_over_session_product(self):
        used, note = _product_sticky_layer(
            FY_VOD, topic_state=dict(STATE), user_message="查一下当前图层的均值", client_context=PAGE
        )
        assert used == FY_VOD, "点名「当前图层」却粘回了上一轮的 SMAP 土壤水分"
        assert note is None

    def test_rule2_corrects_a_wrong_layer_from_the_model(self):
        """模型传错层时，「当前图层」这层语义要把请求纠正回页面选中层。"""
        used, _ = _product_sticky_layer(
            FY_VOD_DYN, topic_state=dict(STATE), user_message="查当前图层", client_context=PAGE
        )
        assert used == FY_VOD

    def test_rule3_followup_keeps_session_product(self):
        used, note = _product_sticky_layer(
            FY_VOD, topic_state=dict(STATE), user_message="那 2025-12-16 呢", client_context=PAGE
        )
        assert used == SMAP_SM
        assert note is not None

    def test_rule3_region_change_keeps_session_product(self):
        used, _ = _product_sticky_layer(
            FY_VOD, topic_state=dict(STATE), user_message="换成河南省呢", client_context=PAGE
        )
        assert used == SMAP_SM

    def test_rule1_named_product_still_switches(self):
        used, _ = _product_sticky_layer(
            FY_VOD,
            topic_state=dict(STATE),
            user_message="改用风云卫星平均散射约束产品的植被光学厚度",
            client_context=PAGE,
        )
        assert used == FY_VOD

    def test_page_layer_without_selection_lets_model_pass(self):
        """页面没有明确选中层：用户只能指模型拿到的这一层，不要粘回。"""
        empty = _page("", [(FY_VOD, False)])
        used, _ = _product_sticky_layer(
            FY_VOD, topic_state=dict(STATE), user_message="查当前图层", client_context=empty
        )
        assert used == FY_VOD


class TestFallbackPathHonoursPageLayer:
    """兜底路径（模型这轮没调取数工具）也必须认「当前图层」。

    2026-11-09 实测：上一轮问土壤水分、页面选着风云 VOD，用户说「查当前图层」，
    模型选择**反问**而不是取数 ⇒ 落到 ``_statistics_fallback_reply`` ⇒
    ``resolve_entities`` 的优先级 ⓪「沿用上一轮」先命中 ⇒ 拿 state 里的 SMAP
    土壤水分去算，与用户说的正好相反。

    只在 ``_product_sticky_layer`` 里修是不够的：那条路只在模型**调了工具**时
    才走，同一个问题在两条路径上给两个对象，用户只会觉得时好时坏。
    """

    def _resolve(self, message: str, selected: str = FY_VOD):
        from app.services.agent.mock_orchestrator import (
            _normalize_layers,
            resolve_entities,
        )

        ctx = _page(selected, [(FY_VOD, True), (SMAP_SM, True)])
        return resolve_entities(
            message, _normalize_layers(ctx), client_context=ctx, state=dict(STATE)
        )

    def test_page_layer_wins_in_resolver(self):
        for msg in ("查当前图层的均值", "当前图层统计一下", "现在这层是多少"):
            ent = self._resolve(msg)
            assert (ent.get("layer") or {}).get("catalog_id") == FY_VOD, msg
            assert ent.get("layer_from") == "page", msg

    def test_followup_still_uses_session_product(self):
        for msg in ("那 2025-12-16 呢", "换成河南省呢"):
            ent = self._resolve(msg)
            assert (ent.get("layer") or {}).get("catalog_id") == SMAP_SM, msg
            assert ent.get("layer_from") == "state", msg

    def test_no_selection_falls_back_to_session(self):
        from app.services.agent.mock_orchestrator import (
            _normalize_layers,
            resolve_entities,
        )

        ctx = _page("", [(FY_VOD, True), (SMAP_SM, True)])
        ent = resolve_entities(
            "查当前图层", _normalize_layers(ctx), client_context=ctx, state=dict(STATE)
        )
        assert (ent.get("layer") or {}).get("catalog_id") == SMAP_SM


CMFD = "cmfd-precip-cn"  # 目录参考层，非三变量，会覆盖单槽 layer_id
SMAP_SM_DYN = "imported-a8940443fd6d"  # SMAP 动态 · 土壤水分（模型自选错的版本）


class TestVarLayersRecovery:
    """产品粘性跨变量记忆（2026-11-09）：单槽被非三变量层覆盖后仍能找回版本。"""

    def _state_sm_covered_by_cmfd(self):
        return {
            "layer_id": CMFD,
            "layer_name": "CMFD 区域降水",
            "variable": "",
            "var_layers": '{"sm": "imported-38993117b963"}',
        }

    def _fake_identity(self, monkeypatch):
        """测试环境身份表不完整，注入假身份：3899=平均版、a894=动态版。"""
        from app.services.agent import server_tools_runtime as rt

        def fake(layer_id: str, _ctx):
            if "38993117b963" in layer_id:
                return layer_id, {
                    "variable": "sm",
                    "source": "smap",
                    "product_family": "average",
                }
            if "a8940443fd6d" in layer_id:
                return layer_id, {
                    "variable": "sm",
                    "source": "smap",
                    "product_family": "dynamic",
                }
            return layer_id, {"variable": "unknown", "source": "unknown"}

        monkeypatch.setattr(rt, "_identity_of", fake)

    def test_switch_back_to_sm_recovers_average_version(self, monkeypatch):
        """SM 平均版 → CMFD 覆盖单槽 → 切回土壤水分：找回平均版而非动态版。"""
        self._fake_identity(monkeypatch)
        used, note = _product_sticky_layer(
            SMAP_SM_DYN,
            topic_state=self._state_sm_covered_by_cmfd(),
            user_message="切回土壤水分图层",
            client_context={},
        )
        assert used == SMAP_SM, f"应找回 SM 平均版，实际 {used}"
        assert note is not None

    def test_named_version_still_switches(self, monkeypatch):
        """用户点名换口径（切到动态）时，跨变量记忆不得拦住。"""
        self._fake_identity(monkeypatch)
        used, note = _product_sticky_layer(
            SMAP_SM_DYN,
            topic_state=self._state_sm_covered_by_cmfd(),
            user_message="切到 SMAP 动态散射约束产品的土壤水分",
            client_context={},
        )
        assert used == SMAP_SM_DYN, f"点名换动态版应放行，实际 {used}"

    def test_no_memory_falls_back_to_pass(self, monkeypatch):
        """没有跨变量记忆时，维持原有放行（不误改）。"""
        self._fake_identity(monkeypatch)
        state = {"layer_id": CMFD, "layer_name": "CMFD 区域降水"}
        used, _ = _product_sticky_layer(
            SMAP_SM_DYN,
            topic_state=state,
            user_message="切回土壤水分图层",
            client_context={},
        )
        assert used == SMAP_SM_DYN
