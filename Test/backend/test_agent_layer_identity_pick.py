# -*- coding: utf-8 -*-
"""同名图层靠「来源 / 产品形态」定位（2026-11-11 用户实测）。

老师复测：新开对话只发「显示 SMAP 土壤水分图层」，页面仍停在风云 VOD。
根因两条，都跟「页面上四个层都叫土壤水分」有关：

1. ``_resolve_layer`` 命中多个同名层后直接反问，没用 catalog_id 里的身份
   （``imported-nas-smap-avg-sm`` → source=smap / product_family=average）；
2. ``_STAT_VERB`` 里裸的「平均」把「**平均版**」判成了统计请求，于是「开启一层」
   变成「取这个月的平均值」，还回「这层算不出数值」。

这里把两条边界钉死：身份能读出来就必须收窄，收不窄也必须把候选说得能区分。
"""

from app.services.agent.mock_orchestrator import mock_chat


def _ctx() -> dict:
    return {
        "map_ready": True,
        "timeline": {"date": "2025-11-13", "hour": 0},
        "active_layers": [
            {
                "catalog_id": "imported-nas-fy-raw-vod",
                "name": "植被光学厚度",
                "visible": True,
                "selected": True,
            },
            {
                "catalog_id": "imported-nas-smap-avg-sm",
                "name": "土壤水分",
                "visible": False,
                "selected": False,
            },
            {
                "catalog_id": "imported-nas-smap-raw-sm",
                "name": "土壤水分",
                "visible": False,
                "selected": False,
            },
        ],
    }


def _run(message: str) -> dict:
    return mock_chat(message, session_id="s-identity", client_context=_ctx(), state={})


def test_average_variant_picks_avg_layer():
    """「SMAP 平均版」必须落到 avg 那一层，而不是报"取不到数"。"""
    out = _run("显示 SMAP 平均版土壤水分")
    intents = [i for i in out.get("ui_intents") or [] if isinstance(i, dict)]
    assert [i["name"] for i in intents] == ["set_layer_visibility"]
    assert intents[0]["args"]["catalog_id"] == "imported-nas-smap-avg-sm"
    assert intents[0]["args"]["visible"] is True
    # 不许跑到统计分支去
    assert "算不出数值" not in out["reply"]


def test_raw_variant_picks_raw_layer():
    out = _run("显示 SMAP 动态版土壤水分")
    intents = [i for i in out.get("ui_intents") or [] if isinstance(i, dict)]
    assert [i["name"] for i in intents] == ["set_layer_visibility"]
    assert intents[0]["args"]["catalog_id"] == "imported-nas-smap-raw-sm"


def test_hide_variant_also_uses_identity():
    """隐藏同样要认出版本，不能回到"算不出数"。"""
    out = _run("隐藏 SMAP 平均版土壤水分")
    intents = [i for i in out.get("ui_intents") or [] if isinstance(i, dict)]
    assert [i["name"] for i in intents] == ["set_layer_visibility"]
    assert intents[0]["args"]["catalog_id"] == "imported-nas-smap-avg-sm"
    assert intents[0]["args"]["visible"] is False


def test_receipt_names_the_variant():
    """回执必须能区分版本，否则「已显示土壤水分」等于没说。"""
    out = _run("显示 SMAP 平均版土壤水分")
    assert "平均版" in out["reply"]


def test_ambiguous_smap_asks_with_distinguishable_names():
    """只说了 SMAP、没说版本：可以反问，但候选必须能区分。"""
    out = _run("显示 SMAP 土壤水分图层")
    assert out.get("ui_intents") == []
    assert "平均版" in out["reply"]
    assert "动态版" in out["reply"]


def test_bare_variable_still_asks():
    """连来源都没说，仍然不许猜。"""
    out = _run("显示土壤水分")
    assert out.get("ui_intents") == []
    assert "平均版" in out["reply"]
