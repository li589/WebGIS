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
