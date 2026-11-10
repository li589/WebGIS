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


def test_undecided_reply_lists_candidates_without_picking(monkeypatch):
    """页面只挂 ω、问土壤水分：列出全部候选并让用户点名，一个数都不给。

    2026-11-07：这一步原先只回一句「当前地图上没有这一层的可统计版本」，
    本机明明有四族土壤水分；同一个问题两轮问还能得到两种答复（一次自己
    挑了 SMAP 算出 0.2929）。现在收敛成固定清单，且不写会话基线。
    """
    from app.services.agent import mock_orchestrator

    ctx = _ctx([OMEGA_LAYER])
    cands = [
        {
            "catalog_id": "method-smap-dynamic",
            "overlay_layer_id": "imported-a",
            "name": "SMAP 动态散射约束产品 · 土壤水分",
            "source": "smap",
            "on_page": False,
            "virtual": True,
        },
        {
            "catalog_id": "method-fy-dynamic",
            "overlay_layer_id": "imported-b",
            "name": "风云卫星 动态散射约束产品 · 土壤水分",
            "source": "fy",
            "on_page": False,
            "virtual": True,
        },
    ]
    monkeypatch.setattr(
        mock_orchestrator, "_same_variable_candidates", lambda var, ls: cands
    )
    out = mock_orchestrator._statistics_reply(
        "河南省的土壤水分平均值是多少", ctx["active_layers"], ctx, "sid", [], state={}
    )
    reply = out["reply"]
    assert "SMAP 动态散射约束产品 · 土壤水分" in reply
    assert "风云卫星 动态散射约束产品 · 土壤水分" in reply
    assert "我不替你挑" in reply
    assert "均值：" not in reply  # 没定层之前一个数都不许出
    # 只记「问的是哪个变量」和用户明说的区域，绝不写层——
    # 写了层下一轮就会被当基线拿去统计。
    assert "layer_id" not in out["topic_state"]
    assert out["topic_state"].get("variable") == "sm"


def test_named_version_narrows_by_page_source(monkeypatch):
    """点名了口径（「换回平均版」）时按页面同源收窄，不再反问「用哪个」。

    2026-11-08 实测 r69：动态版→平均版→动态版→「再换回平均版」，回了一句
    「本机有 2 个「土壤水分」的版本…我不替你挑」。口径已经说死了，剩下的只有
    来源分歧；页面是 SMAP、同源候选唯一 ⇒ 直接用它。跨来源才需要用户点头，
    那是 _cross_source_guard 的职责，不是这里的反问。
    """
    from app.services.agent import mock_orchestrator

    ctx = _ctx([OMEGA_LAYER])
    cands = [
        {
            "catalog_id": "method-smap-season-mean",
            "overlay_layer_id": "imported-136c60293bbf",
            "name": "SMAP 平均散射约束产品 · 土壤水分",
            "source": "smap",
            "on_page": False,
            "virtual": True,
        },
        {
            "catalog_id": "method-fy-omega-doy-avg",
            "overlay_layer_id": "imported-fyavg",
            "name": "风云卫星 平均散射约束产品 · 土壤水分",
            "source": "fy",
            "on_page": False,
            "virtual": True,
        },
    ]
    monkeypatch.setattr(
        mock_orchestrator, "_same_variable_candidates", lambda var, ls: cands
    )
    monkeypatch.setattr(mock_orchestrator, "_page_sources", lambda ls: {"smap"})
    layer, reply = mock_orchestrator._undecided_statistics_reply(
        text="再换回平均版",
        entities={"variable": "sm", "why": "没定层", "region": "广州市"},
        layers=ctx["active_layers"],
        sid="sid",
        intents=[],
    )
    assert reply is None, "同源候选唯一时不该再反问"
    assert layer is not None
    assert layer["name"] == "SMAP 平均散射约束产品 · 土壤水分"
    assert layer["catalog_id"] == "method-smap-season-mean"


def test_named_variable_without_version_still_asks(monkeypatch):
    """只说变量、没点口径时仍要列清单（口径没定，不能替用户挑平均还是动态）。"""
    from app.services.agent import mock_orchestrator

    ctx = _ctx([OMEGA_LAYER])
    cands = [
        {
            "catalog_id": "method-smap-season-mean",
            "overlay_layer_id": "imported-136c60293bbf",
            "name": "SMAP 平均散射约束产品 · 土壤水分",
            "source": "smap",
            "on_page": False,
            "virtual": True,
        },
        {
            "catalog_id": "method-fy-omega-doy-avg",
            "overlay_layer_id": "imported-fyavg",
            "name": "风云卫星 平均散射约束产品 · 土壤水分",
            "source": "fy",
            "on_page": False,
            "virtual": True,
        },
    ]
    monkeypatch.setattr(
        mock_orchestrator, "_same_variable_candidates", lambda var, ls: cands
    )
    monkeypatch.setattr(mock_orchestrator, "_page_sources", lambda ls: {"smap"})
    layer, reply = mock_orchestrator._undecided_statistics_reply(
        text="河南省的土壤水分平均值是多少",
        entities={"variable": "sm", "why": "没定层", "region": "河南省"},
        layers=ctx["active_layers"],
        sid="sid",
        intents=[],
    )
    assert layer is None
    assert reply is not None
    assert "我不替你挑" in reply["reply"]


def test_resolved_layer_carries_region_and_date(monkeypatch):
    """层是在「候选收窄」这一步定下来的，区域/日期仍要沿用上一轮。

    2026-11-08 实测 r69 第 4 句：前三轮都是「广州市 / 2025-11-13」，
    「再换回平均版」这句却算成「整层 / 2025-12-16」（时间轴当天）。
    原因：区域沿用只认 layer_from in ("state","catalog")，这条路径标的是 "resolved"。
    """
    from app.services.agent import mock_orchestrator
    from app.services.agent import server_tools_runtime as rt

    ctx = _ctx([OMEGA_LAYER])
    cands = [
        {
            "catalog_id": "method-smap-season-mean",
            "overlay_layer_id": "imported-136c60293bbf",
            "name": "SMAP 平均散射约束产品 · 土壤水分",
            "source": "smap",
            "on_page": False,
            "virtual": True,
        },
        {
            "catalog_id": "method-fy-omega-doy-avg",
            "overlay_layer_id": "imported-fyavg",
            "name": "风云卫星 平均散射约束产品 · 土壤水分",
            "source": "fy",
            "on_page": False,
            "virtual": True,
        },
    ]
    monkeypatch.setattr(
        mock_orchestrator, "_same_variable_candidates", lambda var, ls: cands
    )
    monkeypatch.setattr(mock_orchestrator, "_page_sources", lambda ls: {"smap"})
    # 强制走「层定不下来 ⇒ 由候选收窄定层」那条路径
    monkeypatch.setattr(
        mock_orchestrator,
        "resolve_entities",
        lambda *a, **kw: {
            "layer": None,
            "variable": "sm",
            "region": None,
            "date": None,
            "why": "没定层",
            "layer_from": "",
        },
    )
    captured: dict = {}

    def fake_stat(args, **kwargs):
        captured.update(args)
        return {"ok": False, "error": "stub", "user_facing": "停在这里"}

    monkeypatch.setattr(rt, "_get_layer_statistics", fake_stat)
    out = mock_orchestrator._statistics_reply(
        "再换回平均版",
        ctx["active_layers"],
        ctx,
        "sid",
        [],
        state={
            "layer_id": "imported-a8940443fd6d",
            "layer_name": "SMAP 动态散射约束产品 · 土壤水分",
            "variable": "sm",
            "region": "广州市",
            "date": "2025-11-13",
        },
    )
    assert captured.get("region") == "广州市", "区域必须沿用上一轮"
    assert captured.get("time") == "2025-11-13", "日期必须沿用上一轮，不能回落到时间轴当天"
    assert captured.get("catalog_id") == "imported-136c60293bbf"
    assert out["reply"] == "停在这里"


def test_undecided_reply_single_cross_source_candidate_needs_confirm(monkeypatch):
    """只有一种来源、但页面挂的是另一颗卫星 ⇒ 让用户点头，不替他换卫星。"""
    from app.services.agent import mock_orchestrator

    ctx = _ctx([OMEGA_LAYER])
    only = [
        {
            "catalog_id": "method-fy-dynamic",
            "overlay_layer_id": "imported-b",
            "name": "风云卫星 动态散射约束产品 · 土壤水分",
            "source": "fy",
            "on_page": False,
            "virtual": True,
        }
    ]
    monkeypatch.setattr(
        mock_orchestrator, "_same_variable_candidates", lambda var, ls: only
    )
    # 页面这层属于另一颗卫星（真实页面同理：挂风云、唯一候选是 SMAP）
    monkeypatch.setattr(mock_orchestrator, "_page_sources", lambda ls: {"smap"})
    out = mock_orchestrator._statistics_reply(
        "河南省的土壤水分平均值是多少", ctx["active_layers"], ctx, "sid", [], state={}
    )
    # 引导语必须点名那一层：这轮没定层、没写基线，下一句只靠「就用它」
    # 是解析不到对象的（实测会答「没有与你点名的来源一致的图层」）。
    assert "说一句「用 " in out["reply"]
    assert "风云卫星 动态" in out["reply"]
    assert "均值：" not in out["reply"]


def test_tool_error_text_never_leaks_to_user(monkeypatch):
    """工具的 ``error`` 是给模型的指令，正文只能用 ``user_facing``。

    跨来源守卫那份 ``error`` 里写着「**回答里不得出现任何统计数值**」，
    旧代码把它原样拼进正文，用户会读到一段自我训话（2026-11-07 实测）。
    """
    from app.services.agent import mock_orchestrator, server_tools_runtime

    ctx = _ctx([OMEGA_LAYER])
    layer = {
        "catalog_id": "imported-x",
        "overlay_layer_id": "imported-x",
        "name": "SMAP 动态散射约束产品 · 土壤水分",
    }
    monkeypatch.setattr(
        mock_orchestrator,
        "resolve_entities",
        lambda *a, **k: {
            "layer": layer,
            "variable": "sm",
            "region": None,
            "date": None,
            "why": None,
            "layer_from": "message",
        },
    )
    monkeypatch.setattr(
        server_tools_runtime,
        "_get_layer_statistics",
        lambda *a, **k: {
            "ok": False,
            "error_code": "cross_source_needs_confirm",
            "error": "接下来只能这样回答：**回答里不得出现任何统计数值**",
            "user_facing": "页面上现在挂的是「风云卫星·等效散射 ω」，要哪一个？",
        },
    )
    out = mock_orchestrator._statistics_reply(
        "河南省的土壤水分", ctx["active_layers"], ctx, "sid", [], state={}
    )
    assert "不得出现任何统计数值" not in out["reply"]
    assert "页面上现在挂的是" in out["reply"]


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


def test_state_written_from_message_without_tool_calls():
    """模型一次工具都不调（复述历史就答了），也必须记住用户点名的层。

    11-06 实测：第 1 句「SMAP 动态的土壤水分」没调工具 ⇒ 状态空 ⇒ 第 2 句
    「土壤水分的平均值是多少」被挑成「风云卫星 平均」。
    """
    from app.services.agent.orchestrator import _state_patch_from_message

    ctx = {"active_layers": SM_LAYERS}
    patch = _state_patch_from_message("SMAP 动态的土壤水分", ctx, {})
    assert patch["layer_id"] == "sm-smap-dyn"
    assert patch["variable"] == "sm"
    # 只是页面兜底（没说对象）时不许写
    assert _state_patch_from_message("平均值是多少", ctx, {}) == {}


def test_switching_variable_clears_stale_layer():
    """「换成土壤水分」时旧记的 ω 层必须清掉，否则两轮后又被当成本轮对象。"""
    from app.services.agent.orchestrator import _state_patch_from_message

    stale = {
        "layer_id": "om-smap-avg",
        "layer_name": "SMAP 平均散射约束产品 · 等效散射 ω",
        "variable": "omega",
    }
    patch = _state_patch_from_message(
        "换成土壤水分", {"active_layers": SM_LAYERS + [OMEGA_LAYER]}, stale
    )
    assert patch["variable"] == "sm"
    assert set(patch["clear"]) == {"layer_id", "layer_name"}


def test_sanitize_trusts_layer_name_over_variable():
    """层名与变量矛盾时以层名为准（实盘见过 {等效散射 ω, sm}）。"""
    got = dialogue_state.sanitize(
        {"layer_id": "x", "layer_name": "等效散射 ω", "variable": "sm"}
    )
    assert got["variable"] == "omega"


# --- 会话基线记「真读到的那份」而不是「模型传的那份」（2026-11-07 游客实测） ---
# 现场：第 4 句「只改日期」模型传了风云平均的目录 id，工具粘性纠正成 SMAP 并算对；
# 但会话基线被写成风云，第 5 句「只改区域」就按风云取数 ⇒ 广州市 0.3079 / 36 像元。


def test_tool_result_records_product_when_resolved_is_empty():
    """粘性纠正后工具返回的 catalog_id 已是产物 id，resolved_layer_id 恒为空。

    旧实现只认 resolved_layer_id ⇒ 这一跳什么都不记，基线留在模型传错的那颗卫星。
    """
    from app.services.agent.orchestrator import _state_patch_from_tool_results

    patch = _state_patch_from_tool_results(
        [
            {
                "ok": True,
                "catalog_id": "imported-a8940443fd6d",
                "resolved_layer_id": "",
                "display_name": "SMAP 动态散射约束产品 · 土壤水分",
            }
        ]
    )
    assert patch["layer_id"] == "imported-a8940443fd6d"
    assert "SMAP" in patch["layer_name"]
    # 失败返回不写（没读到就没对象）
    assert (
        _state_patch_from_tool_results(
            [{"ok": False, "catalog_id": "imported-a8940443fd6d"}]
        )
        == {}
    )


def test_intents_do_not_override_the_layer_tool_actually_read():
    """工具已读到某层时，意图里的 catalog_id 只是请求参数，不许覆盖基线。"""
    ctx = {"active_layers": SM_LAYERS}
    intents = [
        {
            "name": "set_layer_visibility",
            "args": {"catalog_id": "sm-fy-avg", "visible": True},
        },
        {"name": "set_timeline", "args": {"date": "2025-12-16"}},
    ]
    kept = _state_patch_from_intents(intents, ctx, keep_layer=True)
    assert "layer_id" not in kept  # 层由工具结果负责
    assert kept["date"] == "2025-12-16"  # 日期照记
    # 没有工具结果时照旧记层
    assert "layer_id" in _state_patch_from_intents(intents, ctx)


def test_intents_switch_layer_before_timeline_and_align_day():
    """复合指令：切层必须在切日期之前，日期要落到实际取数那天。

    切层会触发前端时间轴「按图层记忆」跳转（既有设计），排在它前面的
    set_timeline 会被冲掉 —— 实测页面停在 7 月 31 日、正文却报 12-16 的值。
    """
    from app.services.agent.orchestrator import _order_ui_intents

    page = {
        "active_layers": [
            {
                "catalog_id": "method-smap-omega-doy-dynamic",
                "overlay_layer_id": "imported-a8940443fd6d",
                "name": "SMAP 动态散射约束产品 · 土壤水分",
                "selected": True,
            }
        ],
        "timeline": {"date": "2025-07-31"},
    }
    steps = [
        {
            "type": "tool_result",
            "detail": json.dumps(
                {
                    "ok": True,
                    "catalog_id": "imported-a8940443fd6d",
                    "period_start": "20251216",
                    "period_end": "20251216",
                    "mean": 0.1664,
                }
            ),
        }
    ]
    out = _order_ui_intents(
        {
            "ui_intents": [
                {"name": "set_timeline", "args": {"date": "2025-07-31"}},
                {
                    "name": "set_layer_visibility",
                    "args": {"catalog_id": "method-smap-omega-doy-dynamic"},
                },
            ],
            "steps": steps,
        },
        page,
    )
    names = [i["name"] for i in out["ui_intents"]]
    assert names == ["set_layer_visibility", "set_timeline"]
    tl = out["ui_intents"][1]["args"]
    assert tl["date"] == "2025-12-16"
    assert tl["catalog_id"] == "method-smap-omega-doy-dynamic"


def test_intents_add_timeline_when_missing():
    """只下发切层、没下发日期时补一条，否则页面停在图层记忆帧、与正文日期不符。"""
    from app.services.agent.orchestrator import _order_ui_intents

    page = {
        "active_layers": [
            {
                "catalog_id": "method-smap-omega-doy-dynamic",
                "overlay_layer_id": "imported-a8940443fd6d",
                "selected": True,
            }
        ]
    }
    steps = [
        {
            "type": "tool_result",
            "detail": json.dumps(
                {
                    "ok": True,
                    "catalog_id": "imported-a8940443fd6d",
                    "period_start": "20251216",
                    "period_end": "20251216",
                }
            ),
        }
    ]
    out = _order_ui_intents(
        {
            "ui_intents": [
                {
                    "name": "set_layer_visibility",
                    "args": {"catalog_id": "method-smap-omega-doy-dynamic"},
                }
            ],
            "steps": steps,
        },
        page,
    )
    names = [i["name"] for i in out["ui_intents"]]
    assert names == ["set_layer_visibility", "set_timeline"]
    assert out["ui_intents"][1]["args"]["date"] == "2025-12-16"


def test_intents_leave_timeline_alone_for_month_block():
    """月块 / 多年平均不钉时间轴：一句「2025 年整年平均」不该把页面切到某一天。"""
    from app.services.agent.orchestrator import _order_ui_intents

    page = {
        "active_layers": [
            {
                "catalog_id": "method-fy-omega-doy-avg",
                "overlay_layer_id": "imported-55359b8ecd3d",
            }
        ]
    }
    steps = [
        {
            "type": "tool_result",
            "detail": json.dumps(
                {
                    "ok": True,
                    "catalog_id": "imported-55359b8ecd3d",
                    "period_start": "20250701",
                    "period_end": "20250731",
                }
            ),
        }
    ]
    out = _order_ui_intents(
        {
            "ui_intents": [
                {
                    "name": "set_layer_visibility",
                    "args": {"catalog_id": "method-fy-omega-doy-avg"},
                }
            ],
            "steps": steps,
        },
        page,
    )
    assert [i["name"] for i in out["ui_intents"]] == ["set_layer_visibility"]


def test_remember_var_layer_maps_triple_variables():
    """按变量分槽：sm/vod 各记一份，互不覆盖；非三变量不写。"""
    s = dialogue_state.remember_var_layer({}, variable="sm", layer_id="imported-sm-avg")
    s = dialogue_state.remember_var_layer(s, variable="vod", layer_id="imported-vod-dyn")
    assert dialogue_state.var_layers_mapping(s) == {
        "sm": "imported-sm-avg",
        "vod": "imported-vod-dyn",
    }
    # 非三变量（降水）不写进映射
    s2 = dialogue_state.remember_var_layer(s, variable="precip", layer_id="imported-cmfd")
    assert dialogue_state.var_layers_mapping(s2) == {
        "sm": "imported-sm-avg",
        "vod": "imported-vod-dyn",
    }


def test_var_layers_survives_layer_id_overwrite():
    """单槽 layer_id 被 CMFD 覆盖后，三变量映射仍保留，产品粘性可找回版本。"""
    s = dialogue_state.merge(
        {},
        layer_id="imported-sm-avg",
        variable="sm",
        var_layers='{"sm": "imported-sm-avg"}',
    )
    # CMFD 覆盖单槽 layer_id，但不动 var_layers
    s = dialogue_state.merge(s, layer_id="imported-cmfd", layer_name="CMFD 降水")
    assert s["layer_id"] == "imported-cmfd"
    assert dialogue_state.var_layers_mapping(s) == {"sm": "imported-sm-avg"}


def test_var_layers_incoming_merges_across_turns():
    """跨轮累积：新增变量条目合并进旧映射，不整条覆盖。"""
    s = dialogue_state.merge({}, var_layers='{"sm": "imported-sm-avg"}')
    s = dialogue_state.merge(s, var_layers='{"vod": "imported-vod-dyn"}')
    assert dialogue_state.var_layers_mapping(s) == {
        "sm": "imported-sm-avg",
        "vod": "imported-vod-dyn",
    }


def test_sanitize_drops_bad_var_layers():
    """非法 JSON / 非三变量条目在 sanitize 时被清理。"""
    assert "var_layers" not in dialogue_state.sanitize({"var_layers": "not-json"})
    s = dialogue_state.sanitize(
        {"var_layers": '{"sm": "imported-x", "precip": "imported-y"}'}
    )
    assert dialogue_state.var_layers_mapping(s) == {"sm": "imported-x"}
