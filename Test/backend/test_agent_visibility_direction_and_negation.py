# -*- coding: utf-8 -*-
"""多目标显隐的方向、漏项，以及「别」被当否定词的误判（2026-11-11 老师复测）。

这一轮报了 11 条问题，其中四处是**做反事 / 说错话**，比"没做"更严重：

1. 「隐藏植被光学厚度并显示 SMAP 土壤水分」下发 ``visible=True``——把用户要隐藏
   的层显示了，回执还写「已显示」。根因是 Hide 分支要求全文不含「显示」，整句
   落进 Show 分支后用**全文第一个方向词**套所有目标。
2. 「隐藏植被光学厚度和土壤水分」只做了第一个，另一个静默丢弃、回执不提。
3. 「添加 CMFD 并切换到某天」只下发 set_timeline，添加根本没执行。
4. 「分别计算广州和深圳的土壤水分平均值」里的「分**别**」被 ``_EXPLANATION_ONLY_RE``
   的裸「别」命中成「别计算」⇒ 判定用户要求不要统计 ⇒ 两个均值都没算出来。

另外两条状态口径：隐藏层仍是选中层时必须说清「已隐藏」；单步日期请求撞预算时
不许让用户「拆成两句话」。
"""

from app.services.agent.mock_orchestrator import mock_chat
from app.services.agent.orchestrator import (
    _NEGATION_OR_READONLY_HINT,
    _map_actions_reply,
    _request_limit_reply,
)
from app.services.agent.server_tools_runtime import (
    _EXPLANATION_ONLY_RE,
    _tool_blocked_by_current_instruction,
)


def _ctx(*, vod_visible: bool = True, sm_visible: bool = True) -> dict:
    return {
        "map_ready": True,
        "timeline": {"date": "2025-11-13", "hour": 0},
        "active_layers": [
            {
                "catalog_id": "imported-nas-fy-raw-vod",
                "name": "植被光学厚度",
                "visible": vod_visible,
                "selected": True,
            },
            {
                "catalog_id": "imported-nas-smap-avg-sm",
                "name": "土壤水分",
                "visible": sm_visible,
                "selected": False,
            },
        ],
    }


def _run(message: str, ctx: dict | None = None) -> dict:
    return mock_chat(
        message,
        session_id="s-vis",
        client_context=ctx or _ctx(),
        state={},
    )


def _intents(out: dict) -> list[dict]:
    return [i for i in (out.get("ui_intents") or []) if isinstance(i, dict)]


def _vis(out: dict) -> list[tuple[str, bool]]:
    return [
        (
            str((i.get("args") or {}).get("catalog_id")),
            bool((i.get("args") or {}).get("visible")),
        )
        for i in _intents(out)
        if i.get("name") == "set_layer_visibility"
    ]


# ── 一、「别」不是所有场合都是否定词 ────────────────────────────


def test_fenbie_is_not_a_negation():
    """「分**别**计算」是并列要求，不是「别计算」。"""
    msg = "分别计算广州和深圳的土壤水分平均值"
    assert _EXPLANATION_ONLY_RE.search(msg) is None
    assert _tool_blocked_by_current_instruction("get_layer_statistics", msg) is None
    assert _NEGATION_OR_READONLY_HINT.search(msg) is None


def test_tebie_and_jianbie_are_not_negations():
    for msg in ("特别说明一下这层是什么", "鉴别一下这两层", "级别说明", "类别查询"):
        assert _NEGATION_OR_READONLY_HINT.search(msg) is None, msg


def test_real_negation_still_blocks_data_tools():
    """真否定必须继续拦住——别把闸门一起拆了。"""
    for msg in ("别统计，只解释一下", "不要取数", "不用统计"):
        assert _tool_blocked_by_current_instruction("get_layer_statistics", msg), msg
    for msg in ("别统计", "不要打开 GPCP"):
        assert _NEGATION_OR_READONLY_HINT.search(msg), msg


# ── 二、多目标显隐：方向按子句走，不许全文一个方向 ──────────────


def test_hide_then_show_keeps_each_direction():
    """「隐藏 A 并显示 B」——A 必须 False、B 必须 True。"""
    out = _run("隐藏植被光学厚度并显示 SMAP 土壤水分")
    pairs = dict(_vis(out))
    assert pairs.get("imported-nas-fy-raw-vod") is False
    assert pairs.get("imported-nas-smap-avg-sm") is True


def test_show_then_hide_keeps_each_direction():
    out = _run("显示 SMAP 土壤水分并隐藏植被光学厚度")
    pairs = dict(_vis(out))
    assert pairs.get("imported-nas-smap-avg-sm") is True
    assert pairs.get("imported-nas-fy-raw-vod") is False


def test_shared_direction_covers_all_targets():
    """「隐藏 A 和 B」只有一个方向词，两个目标都要做。"""
    out = _run("隐藏植被光学厚度和土壤水分")
    assert set(dict(_vis(out))) == {
        "imported-nas-fy-raw-vod",
        "imported-nas-smap-avg-sm",
    }
    assert all(v is False for _, v in _vis(out))


# ── 三、多目标里定位不到的那一步必须点名 ────────────────────────


def test_second_target_missing_is_reported():
    """CMFD 不在页面也不在目录时，不能只做 VOD 就完事。"""
    out = _run("隐藏 CMFD 和 VOD")
    assert "CMFD" in out["reply"]
    assert "没有执行" in out["reply"]


# ── 四、添加 + 切日期：两件事都要下发 ───────────────────────────


def test_add_layer_and_set_date_emits_both():
    """「添加 CMFD 并切到某天」：添加要执行，日期要说清为什么切不了。

    CMFD 区域降水是静态数据（没有时间维度）。2026-11-11 老师复测第 3 条：旧口径
    照样下发 set_timeline，页面拒绝执行，回复却写「已切到」。现在只下发添加，
    并在正文里说明这一层不支持切换日期。
    """
    out = _run("添加 CMFD 降水并切换到 2025-12-01")
    names = [i.get("name") for i in _intents(out)]
    assert "set_layer_visibility" in names
    assert "set_timeline" not in names
    assert "静态数据" in out["reply"]
    assert "不支持切换日期" in out["reply"]


def test_date_only_request_does_not_add_anything():
    """纯日期请求不许顺手挂个图层上来。"""
    out = _run("把时间轴切到 2025-12-15")
    assert [i.get("name") for i in _intents(out)] == ["set_timeline"]


# ── 五、「把当前图层切换到某日」要真的切日期 ────────────────────


def test_switch_current_layer_to_date_sets_timeline():
    """老师复测原句：以前被「当前图层」这个列表查询词截胡，回的是图层清单。"""
    out = _run("把当前图层切换到2025年12月25日")
    assert [i.get("name") for i in _intents(out)] == ["set_timeline"]
    assert (i_args := (_intents(out)[0].get("args") or {}))["date"] == "2025-12-25"
    assert "当前有" not in out["reply"]


# ── 六、隐藏层仍是选中层：必须说清「已隐藏」 ────────────────────


def test_selected_but_hidden_is_stated():
    out = _run("现在选中的是哪个", _ctx(vod_visible=False))
    assert "植被光学厚度" in out["reply"]
    assert "隐藏" in out["reply"]
    # 不能出现「没有选中任何图层」再自相矛盾
    assert "没有选中任何图层" not in out["reply"]


def test_selected_and_visible_is_stated():
    out = _run("现在选中的是哪个", _ctx(vod_visible=True))
    assert "植被光学厚度" in out["reply"]
    assert "勾选显示" in out["reply"]


# ── 七、超预算文案不再甩锅给用户 ────────────────────────────────


def test_limit_reply_never_tells_user_to_split_a_single_command():
    reply = _request_limit_reply(message="把当前图层切换到2025年12月25日")
    assert "拆成两句话" not in reply
    assert "内容较多" not in reply
    assert "页面状态没有变化" in reply


# ── 八、确定性路径（走 _resolve_deterministic_map_actions 那条） ──────
#
# mock_chat 改好了不代表线上修好了：run_chat 会先走这条确定性路径，它自己
# 有一套子句拆分/日期判定/目标定位。下面几条是实测真实链路时暴露的坑。


def _det(
    message: str, unresolved: list[str] | None = None, notes: list[str] | None = None
):
    from app.services.agent.orchestrator import _resolve_deterministic_map_actions

    return _resolve_deterministic_map_actions(
        message,
        _ctx(),
        unresolved=unresolved if unresolved is not None else [],
        notes=notes,
    )


def test_chinese_date_is_recognized_in_deterministic_path():
    """「2025年12月25日」以前整条认不出——日期正则的分隔符字符类没有「月」。"""
    acts = _det("把当前图层切换到2025年12月25日")
    assert acts is not None
    assert [a["name"] for a in acts] == ["set_timeline"]
    assert acts[0]["args"]["date"] == "2025-12-25"


def test_deterministic_path_splits_on_bing():
    """确定性路径的切句正则原来不含「并」⇒ 两个目标共用一个方向。"""
    acts = _det("隐藏植被光学厚度并显示 SMAP 土壤水分")
    assert acts is not None
    pairs = {a["args"]["catalog_id"]: a["args"]["visible"] for a in acts}
    assert pairs["imported-nas-fy-raw-vod"] is False
    assert pairs["imported-nas-smap-avg-sm"] is True


def test_deterministic_path_reports_unresolved_hidden_target():
    """隐藏方向不许走 demo 兜底硬配一个层，必须点名「没执行」。"""
    missing: list[str] = []
    acts = _det("隐藏 CMFD 和 VOD", missing)
    assert acts is not None, "有可执行的一步，不该整条退回模型"
    assert [a["name"] for a in acts] == ["set_layer_visibility"]
    assert missing and "CMFD" in missing[0]


def test_deterministic_path_add_then_date_binds_new_layer():
    """添加 + 切日期：图层加上了，静态层要说清「不支持切日期」而不是假装切了。

    CMFD 区域降水盘上没有时间帧（``time_list`` 为空），日期这一步不可能生效。
    旧口径返回 ``["set_layer_visibility", "set_timeline"]`` 且正文写「日期已切换到
    2025-12-01」——正是老师复测里「说切了、页面没动」的那条。
    """
    notes: list[str] = []
    acts = _det("添加 CMFD 降水并切换到 2025-12-01", notes=notes)
    assert acts is not None, "添加这一步做成了，不该整条退回模型"
    assert [a["name"] for a in acts] == ["set_layer_visibility"]
    assert notes and "静态数据" in notes[0]
    reply = _map_actions_reply(acts, [], notes)
    assert "已显示" in reply
    assert "静态数据" in reply
    assert "日期已切换到" not in reply


def test_deterministic_path_dynamic_layer_binds_new_instance():
    """有时序的层：添加 + 切日期两条都要下发，日期绑到新加那层。"""
    acts = _det("显示 SMAP 土壤水分并切换到 2025-12-01")
    assert acts is not None
    assert [a["name"] for a in acts] == ["set_layer_visibility", "set_timeline"]
    assert acts[1]["args"].get("catalog_id") == acts[0]["args"]["catalog_id"]
