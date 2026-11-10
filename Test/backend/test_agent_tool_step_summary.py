# -*- coding: utf-8 -*-
"""「执行流程」里的工具记录必须写出**实际取数层**（2026-11-09 实测引入）。

外部反馈原文：「『传参有误』指的是助手把交给统计工具的图层编号填成了风云产品。
执行记录把这一步显示了出来。统计工具最终从会话里取到了正确的 SMAP 动态版，
所以算出来的数值是对的。」

根因不是模型传错，而是记录本身不可信：旧写法逐字记模型传进来的 ``args``，而
工具内部会改写 catalog_id（产品粘性改回会话基线、目录层 ``method-*`` 映射成
``imported-*`` 产物），改写结果只写在返回体里、从不回写记录 ⇒ 记录里的层号
可以根本不是真正读的那一层。

危险之处：风云动态与 SMAP 动态在广州市几乎同值（0.1506/68 vs 0.1482/69），
光看数字分不出串没串，只有这一行能让用户当场核对。
"""

from __future__ import annotations

from pathlib import Path

from app.services.agent.orchestrator import _tool_step_summary


def _payload(**kw):
    base = {
        "ok": True,
        "catalog_id": "imported-38993117b963",
        "resolved_layer_id": "",
        "display_name": "SMAP 平均散射约束产品 · 土壤水分",
        "layer_source": "requested",
        "mean": 0.0643,
        "valid_pixels": 28,
    }
    base.update(kw)
    return base


class TestToolStepSummary:
    def test_requested_equals_actual_keeps_original_line(self):
        """模型传对了就不加尾巴，免得每条记录都刷噪音。"""
        args = {"catalog_id": "imported-38993117b963", "time": "2025-11-13"}
        out = _tool_step_summary("get_layer_statistics", args, _payload())
        assert "实际取" not in out
        assert out.startswith("get_layer_statistics(")
        assert "imported-38993117b963" in out

    def test_pinned_to_session_product_names_actual_layer(self):
        """模型传风云动态、被粘性改回 SMAP 平均：必须写明实际读的是哪一层。"""
        args = {"catalog_id": "imported-fa303afda71e", "time": "2025-11-13"}
        res = _payload(layer_source="session", product_pinned="这一句没点名换产品")
        out = _tool_step_summary("get_layer_statistics", args, res)
        assert "imported-fa303afda71e" in out  # 原始请求仍在（可追溯）
        assert "→ 实际取 imported-38993117b963" in out
        assert "SMAP 平均散射约束产品" in out
        assert "按会话产品" in out

    def test_directory_layer_mapping_is_labelled(self):
        """模型常传目录层 id（method-*），实际读的是盘上的 imported-* 产物。"""
        args = {"catalog_id": "method-smap-doy-avg", "time": "2025-11-13"}
        out = _tool_step_summary("get_layer_statistics", args, _payload())
        assert "method-smap-doy-avg" in out
        assert "→ 实际取 imported-38993117b963" in out
        assert "目录层映射" in out

    def test_resolved_layer_id_wins_over_catalog_id(self):
        args = {"catalog_id": "method-x"}
        res = _payload(catalog_id="method-x", resolved_layer_id="imported-aaa")
        out = _tool_step_summary("get_layer_statistics", args, res)
        assert "imported-aaa" in out

    def test_no_layer_in_args_is_labelled_as_carried_over(self):
        """没传图层（按会话/页面取数）时也要写出实际用的是哪一层。"""
        out = _tool_step_summary("get_layer_statistics", {"time": "2025-11-13"}, _payload())
        assert "→ 实际取 imported-38993117b963" in out
        assert "会话沿用" in out

    def test_tools_without_result_body_unchanged(self):
        out = _tool_step_summary("search_layers", {"keyword": "SMAP"}, {"ok": True, "layers": []})
        assert out == 'search_layers({"keyword": "SMAP"})'

    def test_no_result_yet_keeps_base_line(self):
        out = _tool_step_summary("get_layer_statistics", {"catalog_id": "imported-x"})
        assert out == 'get_layer_statistics({"catalog_id": "imported-x"})'


def test_both_tool_loops_rewrite_the_step_after_execution():
    """Anthropic 路与 DeepSeek(OpenAI 兼容) 路都在执行后回写记录。

    2026-11-07 就踩过「守卫只在一条路径上装」的坑（漏传 user_message），
    这里用源码结构守住「两条路径都要回写」，改一处漏一处会直接失败。
    """
    src = (
        Path(__file__).resolve().parents[2]
        / "Code"
        / "backend"
        / "app"
        / "services"
        / "agent"
        / "orchestrator.py"
    ).read_text(encoding="utf-8")
    assert src.count('steps[step_idx]["summary"] = _tool_step_summary(') == 2
