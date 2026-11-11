"""按任务裁剪工具时的边界（2026-11-11）。

老师复测的两条现象根因都在这里：

1. 新开对话只发「显示 SMAP 土壤水分图层」，页面仍停在风云 VOD。
   —— 同族的「显示 SMAP **平均版**土壤水分」被 `_STATISTICS_WORDS` 的裸「平均」
   命中，判成取数请求，工具只剩 5 个只读工具，`set_layer_visibility` 不在其中，
   这一轮**物理上不可能**动页面。

2. 「切层 + 设日期 + 统计」组合指令中止。
   —— 同上，组合句里有「平均」⇒ 只挂只读数据工具，切层和设日期都没有工具可用。

所以这里的断言重点不是"工具越少越好"，而是**该有的一个都不能缺**。
"""

from __future__ import annotations

import json

import pytest

from app.services.agent.orchestrator import (
    _READ_ONLY_DATA_TOOL_NAMES,
    _UI_ACTION_TOOL_NAMES,
    _all_tools_anthropic,
    _tool_keepset_for_message,
    _tools_anthropic_for_message,
    _tools_openai_for_message,
    _wants_statistics,
    _wants_ui_action,
    estimate_tokens,
)


def _names(message: str) -> set[str]:
    return {str(t.get("name") or "") for t in _tools_anthropic_for_message(message)}


# ── 一、产品版本名不是统计意图 ────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "显示 SMAP 平均版土壤水分",
        "隐藏 SMAP 平均版土壤水分",
        "打开 SMAP 平均版土壤水分图层",
        "显示 SMAP 动态版土壤水分",
    ],
)
def test_version_name_is_not_a_statistics_request(message: str):
    """「平均**版**」是产品版本名，不是「算平均值」。"""
    assert _wants_statistics(message) is False


@pytest.mark.parametrize(
    "message",
    [
        "这层土壤水分的平均值是多少",
        "河南省 2025 年 12 月土壤水分平均值",
        "平均下来是多少",
        "帮我看下这层的均值",
    ],
)
def test_real_statistics_still_detected(message: str):
    """别把真取数请求一起放走——「平均值／均值／平均下来」照旧算统计。"""
    assert _wants_statistics(message) is True


# ── 二、界面动作必须拿到界面工具 ──────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "显示 SMAP 平均版土壤水分",
        "隐藏 CMFD 和 VOD",
        "把时间轴切到 2025-12-15",
        "切换底图到影像",
        "把这层色标最大值改成 0.5",
    ],
)
def test_ui_action_keeps_ui_tools(message: str):
    """只要这句话要动界面，`set_layer_visibility` / `set_timeline` 就不能缺。"""
    assert _wants_ui_action(message) is True
    names = _names(message)
    assert "set_layer_visibility" in names
    assert "set_timeline" in names


def test_ui_turn_drops_data_and_workflow_tools():
    """纯界面操作不需要取数与工作流：砍掉是「减少模型输入」，不是丢能力。"""
    names = _names("显示 SMAP 平均版土壤水分")
    assert "get_layer_statistics" not in names
    assert "run_workflow" not in names
    # 但看图要用的「这是哪一层」必须留着
    assert {"get_layer_meta", "search_layers"} <= names


# ── 三、组合指令两组工具都要 ──────────────────────────────────────


def test_combo_instruction_keeps_both_groups():
    """「切层 → 设日期 → 统计」：界面工具与取数工具必须同时在场。

    旧实现只认「有统计词」，于是这一整句被裁到只剩 5 个只读工具，
    切层和设日期都没有工具可用，只能中止 —— 老师复测的现象。
    """
    message = "显示 SMAP 平均版土壤水分并切到 2025-12-15 再算河南省平均值"
    assert _wants_statistics(message) is True
    assert _wants_ui_action(message) is True
    names = _names(message)
    assert "set_layer_visibility" in names
    assert "set_timeline" in names
    assert "get_layer_statistics" in names


def test_combo_turn_is_leaner_than_full_catalog():
    """组合指令挂的是一套「够用」的子集，仍比全量小。"""
    message = "显示 SMAP 平均版土壤水分并切到 2025-12-15 再算河南省平均值"
    lean = estimate_tokens(
        json.dumps(_tools_anthropic_for_message(message), ensure_ascii=False)
    )
    full = estimate_tokens(json.dumps(_all_tools_anthropic(), ensure_ascii=False))
    assert lean < full


# ── 四、纯取数保持原行为 ──────────────────────────────────────────


def test_pure_statistics_turn_has_no_ui_tools():
    """纯取数不挂界面写工具（原有行为，不许因为这次改动放开）。"""
    names = _names("河南省 2025 年 12 月土壤水分平均值")
    assert "set_layer_visibility" not in names
    assert "get_layer_statistics" in names


def test_statistics_keyword_alone_does_not_claim_ui_action():
    """「2025 年」不是界面动作 —— 否则裁剪会被误触发、等于没裁。"""
    assert _wants_ui_action("河南省 2025 年 12 月土壤水分平均值") is False


# ── 五、认不出就不裁 ────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    ["这一层的数据是什么", "帮我规划一个干旱分析流程", "你好"],
)
def test_unclear_message_keeps_all_tools(message: str):
    """意图认不出来时全挂，不做任何裁剪——不冒险。"""
    assert _tool_keepset_for_message(message) is None
    assert len(_tools_anthropic_for_message(message)) == len(_all_tools_anthropic())


# ── 六、两种协议一致 ────────────────────────────────────────────


def test_openai_and_anthropic_scope_agree():
    """只改一路是这套代码反复踩过的坑，两条协议的裁剪结果必须一致。"""
    for message in (
        "显示 SMAP 平均版土壤水分",
        "河南省 2025 年 12 月土壤水分平均值",
        "显示 SMAP 平均版土壤水分并切到 2025-12-15 再算河南省平均值",
    ):
        oa = {
            str((t.get("function") or {}).get("name") or "")
            for t in _tools_openai_for_message(message)
        }
        an = {str(t.get("name") or "") for t in _tools_anthropic_for_message(message)}
        assert oa == an, message


def test_tool_sets_are_disjoint():
    """界面工具与取数工具的名单不许重叠（重叠说明分类写错了）。"""
    assert not (_UI_ACTION_TOOL_NAMES & _READ_ONLY_DATA_TOOL_NAMES)
