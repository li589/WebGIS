"""跨轮上下文回归测试（外部测试 2026-11-06 三条失败）。

锁定的行为：

1. **「其余不变」只改用户说到的那一项**——图层、区域、日期不再被页面选中层顶掉；
2. **区域解析抗动词干扰**——「再回到河南省…」不能整句放弃退回全幅；
3. **界面意图回执不许写成已完成**——服务端只能回「已下发」，真实结果由前端回报；
4. **多跳意图合并而不是覆盖**——复合指令里第一跳的「显示某层」不能被顶掉。

纯函数级测试，不连数据、不启动 app，秒级完成。
"""

from __future__ import annotations

import json

from app.services.agent import dialogue_state
from app.services.agent.mock_orchestrator import (
    _parse_region_arg,
    resolve_entities,
)
from app.services.agent.orchestrator import (
    _UI_TOOL_ACK,
    _merge_intents,
    _state_patch_from_intents,
)

#: 与页面实际显示名一致（产品族 + 变量），共四族两支
LAYERS = [
    {"catalog_id": "imported-a94205dad5f9", "name": "风云卫星 平均散射约束产品 · VOD"},
    {"catalog_id": "imported-731b37b59c97", "name": "风云卫星 动态散射约束产品 · VOD"},
    {"catalog_id": "imported-bce85323670f", "name": "SMAP 平均散射约束产品 · VOD"},
    {"catalog_id": "imported-5427e1020d63", "name": "SMAP 动态散射约束产品 · VOD"},
]

#: 上一轮已经确认过的对象：SMAP 平均 · VOD / 河南省 / 2025-12-15
STATE = {
    "layer_id": "imported-bce85323670f",
    "layer_name": "SMAP 平均散射约束产品 · VOD",
    "variable": "vod",
    "region": "河南省",
    "date": "2025-12-15",
}


def test_region_survives_leading_verb():
    """「再回到河南省」里的动词不能把整个候选吞掉（旧实现 findall 得到「再回到河南省」）。"""
    assert _parse_region_arg("再回到河南省2025年12月15日") == "河南省"
    assert _parse_region_arg("回到河南原来的日期，其余不变") == "河南省"
    # 同省不同级：靠后的那个才是用户真指的
    assert _parse_region_arg("河南省郑州市的均值") == "郑州市"


def test_follow_up_keeps_layer_region_date():
    """「只把日期改成 X，其余保持不变」——只换日期，图层与区域都沿用上一轮。"""
    entities = resolve_entities(
        "只把日期改成2025年12月16日，其余保持不变", LAYERS, state=STATE
    )
    assert entities["layer"]["catalog_id"] == "imported-bce85323670f"
    assert entities["layer_from"] == "state"
    assert entities["region"] == "河南省"
    assert entities["region_from"] == "state"
    assert entities["date"] == "2025-12-16"
    assert entities["date_from"] == "message"


def test_follow_up_keeps_date_when_user_says_original():
    """「回到河南原来的日期」——区域是本轮点名的，日期沿用上一轮。"""
    entities = resolve_entities("回到河南原来的日期，其余不变", LAYERS, state=STATE)
    assert entities["region"] == "河南省"
    assert entities["region_from"] == "message"
    assert entities["date"] == "2025-12-15"
    assert entities["date_from"] == "state"


def test_explicit_product_wins_over_state():
    """点名了新的产品形态就换层，不许被上一轮的层压住。"""
    entities = resolve_entities(
        "换成 SMAP 动态那套，河南省12月15日", LAYERS, state=STATE
    )
    assert entities["layer"]["catalog_id"] == "imported-5427e1020d63"
    assert entities["layer_from"] == "message"


def test_no_state_keeps_old_page_fallback():
    """没有会话记录时行为不变：仍然按页面选中层兜底。"""
    layers = [dict(item) for item in LAYERS]
    layers[3]["selected"] = True
    entities = resolve_entities("平均值是多少", layers, state=None)
    assert entities["layer"]["catalog_id"] == "imported-5427e1020d63"
    assert entities["layer_from"] == "page"


def test_lost_layer_asks_instead_of_guessing():
    """记录里的层已经不在页面上、又无法从候选里唯一定位时：如实反问，不拿别的层顶上。"""
    entities = resolve_entities(
        "再算一次平均值",
        [LAYERS[0], LAYERS[1]],
        state={"layer_id": "imported-999", "layer_name": "某个已移除的层"},
    )
    assert entities["layer"] is None
    assert "某个已移除的层" in (entities["why"] or "")


def test_state_merge_keeps_unmentioned_fields():
    merged = dialogue_state.merge(STATE, date="2025-12-16")
    assert merged["date"] == "2025-12-16"
    assert merged["region"] == "河南省"
    assert merged["layer_id"] == "imported-bce85323670f"
    # 显式清空才真的清空
    assert "region" not in dialogue_state.merge(STATE, clear={"region"})


def test_state_sanitize_drops_unknown_keys():
    assert dialogue_state.sanitize(
        {"layer_id": " x ", "evil": "1", "variable": "??"}
    ) == {"layer_id": "x"}
    assert dialogue_state.sanitize(None) == {}
    assert dialogue_state.sanitize("bad") == {}


def test_variable_from_name_not_fooled_by_family_name():
    """族名里的「散射」不许把所有层都判成 ω（VOD 层名同时含 VOD 与散射）。"""
    assert dialogue_state.variable_from_name("SMAP 平均散射约束产品 · VOD") == "vod"
    assert (
        dialogue_state.variable_from_name("风云卫星 动态散射约束产品 · 土壤水分")
        == "sm"
    )
    assert dialogue_state.variable_from_name("SMAP 平均散射约束产品 · 等效散射 ω") == (
        "omega"
    )


def test_ui_ack_does_not_claim_execution():
    """界面意图的服务端回执只能是「已下发、未执行」。"""
    ack = json.loads(_UI_TOOL_ACK)
    assert ack["executed"] is False
    assert ack["status"] == "queued"
    assert "尚未执行" in ack["note"]  # 明确告诉模型：还没执行


def test_intents_merge_keeps_both_hops():
    first = [
        {"name": "set_layer_visibility", "args": {"catalog_id": "a", "visible": True}}
    ]
    second = [{"name": "set_timeline", "args": {"date": "2025-12-16"}}]
    merged = _merge_intents(first, second)
    assert [i["name"] for i in merged] == ["set_layer_visibility", "set_timeline"]
    # 同一意图重复下发只留一份
    assert len(_merge_intents(merged, first)) == 2


def test_state_patch_from_intents_ignores_hiding():
    ctx = {"active_layers": LAYERS}
    show = _state_patch_from_intents(
        [
            {
                "name": "set_layer_visibility",
                "args": {"catalog_id": "imported-5427e1020d63", "visible": True},
            }
        ],
        ctx,
    )
    assert show["layer_id"] == "imported-5427e1020d63"
    assert show["variable"] == "vod"
    hide = _state_patch_from_intents(
        [
            {
                "name": "set_layer_visibility",
                "args": {"catalog_id": "imported-5427e1020d63", "visible": False},
            }
        ],
        ctx,
    )
    assert hide == {}


# --- 变量一致性：问土壤水分不能拿 ω 顶上（2026-11-06 实测） -------------------
# 现场：用户先问「SMAP 动态的土壤水分」，再说「土壤水分的平均值是多少」，
# 答复却是「等效散射 ω」的 0.0999。变量其实认对了（sm），错在最后一层兜底
# 只看「页面选中层」，没受变量约束。

#: 四族土壤水分 + 一个页面选中的 ω 层（与当时页面一致）
SM_LAYERS = [
    {"catalog_id": "sm-fy-avg", "name": "风云卫星 平均散射约束产品 · 土壤水分"},
    {"catalog_id": "sm-fy-dyn", "name": "风云卫星 动态散射约束产品 · 土壤水分"},
    {"catalog_id": "sm-smap-avg", "name": "SMAP 平均散射约束产品 · 土壤水分"},
    {"catalog_id": "sm-smap-dyn", "name": "SMAP 动态散射约束产品 · 土壤水分"},
]
OMEGA_LAYER = {
    "catalog_id": "om-smap-avg",
    "name": "SMAP 平均散射约束产品 · 等效散射 ω",
    "selected": True,
}


def _ctx(layers):
    return {"active_layers": layers, "timeline": {"date": "2025-07-31"}}


def test_soil_moisture_question_never_falls_back_to_omega():
    ctx = _ctx(SM_LAYERS + [OMEGA_LAYER])
    got = resolve_entities(
        "土壤水分的平均值是多少", ctx["active_layers"], client_context=ctx, state={}
    )
    assert got["variable"] == "sm"
    # 拿不到唯一的土壤水分层时：宁可反问，也不能返回 ω
    assert got["layer"] is None
    assert got["why"]


def test_soil_moisture_question_picks_only_same_variable_layer():
    ctx = _ctx(
        [
            {**SM_LAYERS[1], "visible": False},
            {**SM_LAYERS[3], "visible": True},
            OMEGA_LAYER,
        ]
    )
    got = resolve_entities(
        "土壤水分的平均值是多少", ctx["active_layers"], client_context=ctx, state={}
    )
    assert (got["layer"] or {}).get("catalog_id") == "sm-smap-dyn"


def test_statistics_refuses_when_variable_does_not_match(monkeypatch):
    """通用防线：选层逻辑将来再改，只要变量对不上就在出数前拦住。"""
    from app.services.agent import mock_orchestrator

    ctx = _ctx(SM_LAYERS + [OMEGA_LAYER])
    monkeypatch.setattr(
        mock_orchestrator,
        "resolve_entities",
        lambda *a, **k: {
            "layer": OMEGA_LAYER,
            "variable": "sm",
            "region": None,
            "date": None,
            "why": None,
            "layer_from": "page",
        },
    )
    out = mock_orchestrator._statistics_reply(
        "土壤水分的平均值是多少", ctx["active_layers"], ctx, "sid", [], state={}
    )
    assert "等效散射 ω" in out["reply"]
    assert "均值：" not in out["reply"]  # 一个数字都不许放出去


def test_tool_calls_write_topic_state():
    """模型自己查过哪一层，也要记进会话（界面意图那条路原本就记）。"""
    from app.services.agent.orchestrator import _state_patch_from_tool_calls

    ctx = {"active_layers": SM_LAYERS + [OMEGA_LAYER]}
    patch = _state_patch_from_tool_calls(
        [
            {"name": "get_layer_coverage", "args": {"catalog_id": "sm-smap-dyn"}},
            # 界面意图此刻还没被浏览器执行，不能当作「就在看它」
            {"name": "set_layer_visibility", "args": {"catalog_id": "om-smap-avg"}},
        ],
        ctx,
    )
    assert patch["layer_id"] == "sm-smap-dyn"
    assert patch["variable"] == "sm"
