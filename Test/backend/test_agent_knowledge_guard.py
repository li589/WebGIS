"""Hard boundaries for approved Agent project knowledge."""

from unittest.mock import Mock

from app.services.agent.knowledge_guard import project_knowledge_reply
from app.services.agent.mock_orchestrator import mock_chat


def test_core_terms_use_approved_answers() -> None:
    sm = project_knowledge_reply("SM 是什么？")
    vod = project_knowledge_reply("请解释一下 VOD")
    omega = project_knowledge_reply("欧米伽是什么？")

    assert sm and "土壤体积含水量" in sm and "m³/m³" in sm
    assert vod and "植被光学厚度" in vod and "无量纲" in vod
    assert omega and "散射参数" in omega and "不是直接观测值" in omega


def test_algorithm_and_variants_use_approved_answers() -> None:
    algorithm = project_knowledge_reply("我们研究的算法是什么？")
    variants = project_knowledge_reply("Average 和 Dynamic 有什么区别？")

    assert algorithm and "τ-ω" in algorithm and "数值优化" in algorithm
    assert variants and "ω 的处理方式" in variants
    assert "时间分辨率不同" in variants


def test_unverified_project_claims_are_refused() -> None:
    metrics = project_knowledge_reply("我们算法的精度和 RMSE 是多少？")
    paper = project_knowledge_reply("我们的算法发表了哪些论文，有什么创新点？")
    omega_relation = project_knowledge_reply("omega 和 ωeff 完全一样吗？")

    assert metrics and "没有登记可核实的验证指标" in metrics
    assert paper and "无法可靠回答" in paper
    assert omega_relation and "无法可靠回答" in omega_relation

    layer_metrics = project_knowledge_reply("这个图层的精度怎么样？")
    assert layer_metrics and "没有登记可核实的验证指标" in layer_metrics


def test_data_queries_are_not_swallowed_by_knowledge_guard() -> None:
    assert project_knowledge_reply("北京今天的 VOD 是多少？") is None
    assert project_knowledge_reply("查询当前图层的 SM 均值") is None


def test_unrelated_ml_hyperparam_is_refused() -> None:
    """P0：无关术语（算法超参）在模型调用前就被兜底拒答，不串题到图层统计。"""
    for msg in (
        "Adam学习率是多少",
        "Adam 的学习率是多少",
        "learning rate 是多少",
        "batch size 默认多少",
        "dropout 是多少",
    ):
        reply = project_knowledge_reply(msg)
        assert reply is not None, f"应拒答: {msg!r}"
        assert "没有登记" in reply or "无法确定" in reply, reply


def test_hyperparam_refusal_does_not_swallow_project_terms() -> None:
    """兜底不得误伤项目内术语与正常取数。"""
    assert project_knowledge_reply("SM 是什么") is not None
    assert project_knowledge_reply("VOD 是什么意思") is not None
    assert project_knowledge_reply("土壤水分是多少") is None  # 透传取数
    assert project_knowledge_reply("广州市的土壤水分平均值") is None


def test_demo_mode_uses_the_same_knowledge_guard() -> None:
    result = mock_chat("VOD 是什么意思？")

    assert "植被光学厚度" in result["reply"]
    assert result["ui_intents"] == []


def test_chat_entry_returns_guarded_answer_before_model_call(monkeypatch) -> None:
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
            "model": "test",
            "base_url": "https://invalid.example",
        },
    )
    monkeypatch.setattr(orchestrator, "load_topic_state", lambda **_: {})
    monkeypatch.setattr(orchestrator, "load_history", lambda **_: [])
    monkeypatch.setattr(orchestrator, "append_turn", lambda **_: None)
    monkeypatch.setattr(orchestrator, "get_profile_api_key", model_call)

    result = orchestrator._run_chat_impl("我们算法的精度是多少？")

    assert "没有登记可核实的验证指标" in result["reply"]
    assert result["provider"] == "openai-knowledge-guard"
    assert result["ui_intents"] == []
    model_call.assert_not_called()


def test_read_only_query_cannot_add_or_switch_layers() -> None:
    from app.services.agent.orchestrator import _guard_read_only_ui_intents

    result = _guard_read_only_ui_intents(
        "查询北京的土壤水分是多少？",
        {
            "reply": "结果如下。",
            "ui_intents": [
                {
                    "name": "set_layer_visibility",
                    "args": {"catalog_id": "another-layer", "visible": True},
                },
                {"name": "set_timeline", "args": {"date": "2025-07-15"}},
            ],
        },
    )

    assert result["ui_intents"] == []
    assert "没有改变地图" in result["reply"]


def test_explicit_view_command_keeps_its_intent() -> None:
    from app.services.agent.orchestrator import _guard_read_only_ui_intents

    original = {
        "reply": "已下发显示请求。",
        "ui_intents": [
            {
                "name": "set_layer_visibility",
                "args": {"catalog_id": "wanted-layer", "visible": True},
            }
        ],
    }
    result = _guard_read_only_ui_intents("打开土壤水分图层", original)

    assert len(result["ui_intents"]) == 1


def test_negation_read_only_blocks_mutating_intents() -> None:
    """否定/只读限定（不要/别/只告诉我/保持原样）优先于写动词，清空 mutating intents。

    2026-11-10 实测 A12/D01：「不要打开 GPCP，只告诉我单位」却切了选中图层+时间轴；
    「打开不存在的图层，别选其他」却显示了 GPCP——根因是 _VIEW_WRITE_VERBS 命中
    「打开」放行，掩盖了否定语义。
    """
    from app.services.agent.orchestrator import _guard_read_only_ui_intents

    mutating = [
        {"name": "set_layer_visibility", "args": {"catalog_id": "gpcp", "visible": True}},
        {"name": "set_timeline", "args": {"date": "2025-07-15"}},
    ]
    for msg in (
        "不要打开GPCP月降水，只告诉我它的单位，保持地图原样",
        "打开名为QA不存在的图层，若不存在请明确说明，不要选择其他图层",
        "只告诉我GPCP的单位",
    ):
        r = _guard_read_only_ui_intents(msg, {"reply": "测试", "ui_intents": list(mutating)})
        assert r["ui_intents"] == [], msg
        assert "只读" in r["reply"]

    # 正常写操作不受影响
    ok = _guard_read_only_ui_intents(
        "打开土壤水分图层",
        {"reply": "已下发", "ui_intents": [
            {"name": "set_layer_visibility", "args": {"catalog_id": "sm", "visible": True}}
        ]},
    )
    assert len(ok["ui_intents"]) == 1


def test_planning_intent_passes_through_knowledge_guard() -> None:
    """「设计工作流 / 只给步骤不运行」不得被定义分支当成「什么是土壤水分」拦截。"""
    for msg in (
        "设计一个广州土壤水分月均值分析工作流，逐项解释所有步骤与参数，先不要运行",
        "请设计一个广州2025年7月土壤水分月均值分析工作流，只给步骤，不运行",
        "规划一个植被光学厚度的分析流程，先别运行",
    ):
        assert project_knowledge_reply(msg) is None, msg


def test_definition_questions_still_answered() -> None:
    """定义类问题仍走知识库（不被规划排除误伤）。"""
    assert project_knowledge_reply("什么是土壤水分") is not None
    assert project_knowledge_reply("VOD 是什么意思") is not None


def test_new_session_back_reference_skips_model(monkeypatch) -> None:
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

    result = orchestrator._run_chat_impl("刚才北京的土壤水分是多少？")

    assert "没有你之前问过的记录" in result["reply"]
    assert result["provider"] == "openai-history-guard"
    assert result["usage"]["total_tokens"] < 300
    model_call.assert_not_called()


def test_simple_timeline_command_skips_model(monkeypatch) -> None:
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

    result = orchestrator._run_chat_impl(
        "请把当前土壤水分图层切换到2025年7月15日，只调整时间，不修改数据。",
        client_context={
            "active_layers": [
                {
                    "catalog_id": "current-sm",
                    "display_name": "土壤水分",
                    "selected": True,
                    "visible": True,
                }
            ]
        },
    )

    assert result["provider"] == "openai-timeline-rule"
    assert result["ui_intents"] == [
        {"name": "set_timeline", "args": {"date": "2025-07-15"}}
    ]
    assert result["usage"]["total_tokens"] < 300
    model_call.assert_not_called()


def test_statistics_turn_only_sends_read_only_data_tools() -> None:
    from app.services.agent.orchestrator import _tools_openai_for_message

    tools = _tools_openai_for_message("查询北京土壤水分是多少？")
    names = {
        str((item.get("function") or {}).get("name") or "") for item in tools
    }

    assert names == {
        "search_layers",
        "get_layer_meta",
        "get_layer_coverage",
        "get_layer_statistics",
        "sample_layer_point",
    }
    assert "set_layer_visibility" not in names
    assert "run_workflow" not in names
