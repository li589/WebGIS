# -*- coding: utf-8 -*-
"""模型不可用 / 撞预算时的「本地接管」与降级文案测试（2026-11-11）。

背景：用户反馈「没额度就说切换为本地了」，实测代码是直接返回一段固定文案，
``ui_intents`` 为空——本地规则明明能确定的纯界面操作也被一并放弃。
这里把两条边界钉死：

1. 纯界面操作（显示/隐藏/切日期/底图/缩放）→ 本地规则接管，照常下发意图；
2. 要数值的请求 → 一律不接管，绝不产出替代数值。

另外钉死降级文案：那段「收窄到 2~3 个省」只允许在处理多区域对比时出现，
显示图层、问单位这类请求不能收到它。
"""

from app.services.agent.clients.openai_compat import LlmClientError
from app.services.agent.orchestrator import (
    AgentRequestLimitError,
    _local_takeover,
    _request_limit_reply,
    run_chat,
)

REGION_ADVICE_MARKERS = ("收窄", "2~3 个", "河南、山东、河北")


def _ctx(*names: str) -> dict:
    """构造 client_context.active_layers（前端格式：name 是侧栏变量名）。"""
    layers = []
    for i, name in enumerate(names):
        layers.append(
            {
                "catalog_id": f"imported-{i:03d}",
                "overlay_layer_id": f"overlay-{i:03d}",
                "name": name,
                "visible": False,
                "selected": False,
            }
        )
    return {"active_layers": layers}


# ── 一、本地接管：纯界面操作照常下发 ─────────────────────────────────


def test_local_takeover_shows_named_layer():
    """「显示植被光学厚度」模型挂了也要能显示——这是本地规则完全能确定的动作。"""
    picked = _local_takeover(
        "显示植被光学厚度",
        client_context=_ctx("植被光学厚度", "土壤水分"),
        session_id="s-local-1",
    )
    assert picked is not None, "纯显隐操作不该放弃"
    names = [i["name"] for i in picked["ui_intents"]]
    assert names == ["set_layer_visibility"]
    assert picked["ui_intents"][0]["args"]["visible"] is True
    assert "以页面为准" in picked["reply"]


def test_local_takeover_handles_group_phrase_with_avg_in_name():
    """「平均散射约束模型组」里的「平均」不是取数意图，不能被当禁词误伤。"""
    picked = _local_takeover(
        "请只显示风云卫星微波反演产品平均散射约束模型组中的植被光学厚度，"
        "保持该组土壤水分显示状态不变。",
        client_context=_ctx("植被光学厚度", "土壤水分"),
        session_id="s-local-2",
    )
    assert picked is not None
    assert {i["name"] for i in picked["ui_intents"]} <= {"set_layer_visibility"}


def test_local_takeover_skips_data_queries():
    """要数值的请求一律不接管——本地规则算不出数，硬答就是编数据。"""
    for text in (
        "河南省土壤水分平均值是多少",
        "统计一下 2025 年 12 月广州市的土壤水分",
        "植被光学厚度的单位是什么",
        "全国土壤水分的分布趋势",
    ):
        assert (
            _local_takeover(
                text,
                client_context=_ctx("植被光学厚度", "土壤水分"),
                session_id="s-local-3",
            )
            is None
        ), text


def test_local_takeover_ignores_non_ui_messages():
    """既不是界面操作、也不是取数的闲聊，不接管。"""
    assert (
        _local_takeover(
            "你好",
            client_context=_ctx("土壤水分"),
            session_id="s-local-4",
        )
        is None
    )


# ── 二、降级文案：多区域建议只在多区域对比时出现 ─────────────────────


def test_limit_reply_has_no_region_advice_for_layer_ops():
    reply = _request_limit_reply(message="显示植被光学厚度")
    assert not any(m in reply for m in REGION_ADVICE_MARKERS)
    assert "页面状态没有变化" in reply


def test_limit_reply_keeps_region_advice_for_multi_region_compare():
    reply = _request_limit_reply(message="河南、山东、河北的土壤水分平均值分别是多少")
    assert "收窄" in reply


# ── 三、端到端：模型异常走哪条路 ─────────────────────────────────────


def _run_with_failure(monkeypatch, exc: Exception):
    def boom(*_a, **_k):
        raise exc

    monkeypatch.setattr("app.services.agent.orchestrator._run_chat_impl", boom)


def test_llm_error_still_dispatches_layer_visibility(monkeypatch):
    """模型 LLM 报错，但「显示某层」必须照样下发，且不套区域统计文案。"""
    _run_with_failure(monkeypatch, LlmClientError("HTTP 500 上游炸了"))
    out = run_chat(
        "显示植被光学厚度",
        session_id="s-e2e-1",
        client_context=_ctx("植被光学厚度", "土壤水分"),
    )
    assert out["provider"] == "degraded"
    assert [i["name"] for i in out["ui_intents"]] == ["set_layer_visibility"]
    assert out["ui_intents"][0]["command_id"].startswith("cmd-")
    assert not any(m in out["reply"] for m in REGION_ADVICE_MARKERS)
    # 降级过程说明只留在 steps 里，正文不暴露异常细节
    assert "HTTP 500" not in out["reply"]


def test_llm_error_never_invents_numbers_for_stats(monkeypatch):
    """要数值时模型挂了，只能如实说没算，不能出任何替代数值。"""
    _run_with_failure(monkeypatch, LlmClientError("timeout"))
    out = run_chat(
        "河南省土壤水分平均值是多少",
        session_id="s-e2e-2",
        client_context=_ctx("土壤水分"),
    )
    assert out["ui_intents"] == []
    assert "页面状态没有变化" in out["reply"]
    assert "%" not in out["reply"] and "0." not in out["reply"]


def test_budget_limit_on_layer_op_uses_local_rules(monkeypatch):
    """撞预算（不是连不上）时，显隐请求同样由本地规则接管。"""
    _run_with_failure(
        monkeypatch,
        AgentRequestLimitError(
            "工具多轮累计输入预估约 30000 token，超过单次上限 20000 token，已中止。"
        ),
    )
    out = run_chat(
        "显示植被光学厚度",
        session_id="s-e2e-3",
        client_context=_ctx("植被光学厚度", "土壤水分"),
    )
    assert [i["name"] for i in out["ui_intents"]] == ["set_layer_visibility"]
    assert not any(m in out["reply"] for m in REGION_ADVICE_MARKERS)


def test_budget_limit_on_multi_region_keeps_advice(monkeypatch):
    """真在多区域对比时撞预算，才给「一次点名 2~3 个」的建议。"""
    _run_with_failure(
        monkeypatch,
        AgentRequestLimitError(
            "工具多轮累计输入预估约 30000 token，超过单次上限 20000 token，已中止。"
        ),
    )
    out = run_chat(
        "河南、山东、河北的土壤水分平均值分别是多少",
        session_id="s-e2e-4",
        client_context=_ctx("土壤水分"),
    )
    assert out["ui_intents"] == []
    assert "收窄" in out["reply"]


def test_readonly_negation_still_blocks_takeover(monkeypatch):
    """「不要打开 X」即使模型挂了，也不许被本地规则顺手打开。"""
    _run_with_failure(monkeypatch, LlmClientError("boom"))
    out = run_chat(
        "不要打开植被光学厚度，只告诉我图层名",
        session_id="s-e2e-5",
        client_context=_ctx("植被光学厚度"),
    )
    assert out["ui_intents"] == []
