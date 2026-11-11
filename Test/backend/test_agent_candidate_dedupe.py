# -*- coding: utf-8 -*-
"""候选去重回归测试（2026-11-10 外部实测：列表里同一条出现两遍）。

场景：页面上已经挂着一个产品族的成员（如「SMAP 平均 · 植被光学厚度」），
再问同变量。``_same_variable_candidates`` 分两段收集——① 页面层（用前端传的
``overlay_layer_id``）② 目录产品族成员（用 ``stable_imported_layer_id`` 反算的
``overlay_layer_id``）。当两者 id 对不上时，主键去重失效，同一条候选被列两遍，
用户看到「SMAP 平均散射约束产品 · 植被光学厚度」出现两次。

修复：主键（overlay_layer_id）失效时，追加「显示名 + 来源」兜底去重。
"""

from types import SimpleNamespace

from app.services.agent import mock_orchestrator as mo


def _fake_catalog_item(layer_id: str) -> SimpleNamespace:
    return SimpleNamespace(layer_id=layer_id, display_name="SMAP 平均散射约束产品")


def _fake_identity_fields(cid: str, display_name: str = ""):
    return {
        "product_group_label": "SMAP 平均散射约束产品",
        "group_members": [
            {
                "overlay_layer_id": "imported-169f6402583c",  # 目录反算的 oid
                "variable": "vod",
                "variable_label": "植被光学厚度",
            }
        ],
        "source": "smap",
    }


def test_same_name_source_dedupes_across_page_and_catalog(monkeypatch):
    """页面层 oid 与目录 oid 不同、但显示名+来源相同 ⇒ 只列一次。"""
    # 页面上挂着一个「SMAP 平均 · 植被光学厚度」层，但 overlay_layer_id 是旧副本
    # （与目录反算的 imported-169f6402583c 不同）
    page_layers = [
        {
            "catalog_id": "method-smap-omega-doy-avg",
            "overlay_layer_id": "imported-38993117b963",  # 历史旧副本 id
            "name": "SMAP 平均散射约束产品 · 植被光学厚度",
            "visible": True,
            "selected": True,
        }
    ]
    from app.services.agent import server_tools_runtime as srt

    monkeypatch.setattr(srt, "_qualified_layer_name", lambda oid, base: base)
    monkeypatch.setattr(srt, "_layer_identity_fields", lambda lid: {"source": "smap"})

    # 目录里 method-smap-omega-doy-avg 产品族，成员 oid 是 imported-169f6402583c
    from app.services import layer_catalog as lc

    monkeypatch.setattr(
        lc, "get_layer_catalog", lambda: SimpleNamespace(items=[_fake_catalog_item("method-smap-omega-doy-avg")])
    )
    from app.services.agent import layer_identity as li

    monkeypatch.setattr(li, "identity_fields", _fake_identity_fields)

    cands = mo._same_variable_candidates("vod", page_layers)

    names = [c["name"] for c in cands]
    # 去重后「SMAP 平均散射约束产品 · 植被光学厚度」只出现一次
    assert names.count("SMAP 平均散射约束产品 · 植被光学厚度") == 1, names


def test_distinct_names_still_both_listed(monkeypatch):
    """不同产品族（name 不同）不能被兜底键误伤，仍各自列出。"""
    page_layers = [
        {
            "catalog_id": "method-smap-omega-doy-avg",
            "overlay_layer_id": "imported-38993117b963",
            "name": "SMAP 平均散射约束产品 · 植被光学厚度",
            "visible": True,
            "selected": True,
        }
    ]
    from app.services.agent import server_tools_runtime as srt

    monkeypatch.setattr(srt, "_qualified_layer_name", lambda oid, base: base)
    monkeypatch.setattr(srt, "_layer_identity_fields", lambda lid: {"source": "smap"})
    from app.services import layer_catalog as lc

    monkeypatch.setattr(
        lc,
        "get_layer_catalog",
        lambda: SimpleNamespace(
            items=[
                _fake_catalog_item("method-smap-omega-doy-avg"),
                _fake_catalog_item("method-smap-omega-doy-dynamic"),
            ]
        ),
    )
    from app.services.agent import layer_identity as li

    def _fields(cid, display_name=""):
        if cid == "method-smap-omega-doy-dynamic":
            return {
                "product_group_label": "SMAP 动态散射约束产品",
                "group_members": [
                    {
                        "overlay_layer_id": "imported-5427e1020d63",
                        "variable": "vod",
                        "variable_label": "植被光学厚度",
                    }
                ],
                "source": "smap",
            }
        return _fake_identity_fields(cid, display_name)

    monkeypatch.setattr(li, "identity_fields", _fields)

    cands = mo._same_variable_candidates("vod", page_layers)

    names = [c["name"] for c in cands]
    assert "SMAP 平均散射约束产品 · 植被光学厚度" in names
    assert "SMAP 动态散射约束产品 · 植被光学厚度" in names
    # 两条不同产品族，都不重复
    assert len(names) == len(set(names))
