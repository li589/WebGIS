# -*- coding: utf-8 -*-
"""search_layers 变量英文缩写别名归一化回归测试（2026-11-10 实测缺陷）。

根因：「SMAP 的 VOD」里用户说英文缩写 VOD，但图层名/成员变量写的是中文
「植被光学厚度」，name_blob 里没有 vod 字串 ⇒ 分词后 smap/vod 两个 token
只命中 smap 一个，达不到 need=2 门槛，名称匹配整段失败，全部跌进 description
回落，风云产品反而靠描述里「SMAP 辅助数据」拿到低分排到真 SMAP 前面。

修复：_match_score 对每个 token 按变量别名展开（vod→植被光学厚度/vegetation
optical…），任一别名命中即算该 token 命中。
"""

from types import SimpleNamespace

from app.services.agent import server_tools_runtime as srt


def _fake_item(layer_id: str, display_name: str, description: str) -> SimpleNamespace:
    return SimpleNamespace(
        layer_id=layer_id,
        display_name=display_name,
        description=description,
        tags=[],
        status="active",
        category="derived_product",
    )


def _fake_catalog(monkeypatch, items):
    from app.services import layer_catalog as lc

    monkeypatch.setattr(lc, "get_layer_catalog", lambda: SimpleNamespace(items=items))


def _fake_identity(monkeypatch, mapping):
    """mapping: catalog_id -> identity_fields dict（source/group_members 等）。"""
    from app.services.agent import layer_identity as li

    def _fields(cid, display_name=""):
        return mapping.get(cid, {})

    monkeypatch.setattr(li, "identity_fields", _fields)
    # _layer_identity_fields 内部走 identity_fields，直接复用即可；但为稳妥，
    # 也把 _local_time_keys 等可能触发 IO 的辅助函数拍平。
    monkeypatch.setattr(srt, "_local_time_keys", lambda lid: [])


def test_smap_vod_outranks_fy_when_query_uses_english_vod(monkeypatch):
    """问「SMAP 的 VOD」，SMAP 产品应排在风云产品之前。"""
    items = [
        _fake_item(
            "method-fy-omega-doy-dynamic",
            "风云卫星 动态散射约束产品",
            "风云卫星亮温与 SMAP 辅助数据联合反演：8 天合成产出土壤水分（SM）、植被",
        ),
        _fake_item(
            "method-smap-omega-doy-avg",
            "SMAP 平均散射约束产品",
            "omega_avg_daily / omega_block 经典 D1→D2 链",
        ),
        _fake_item(
            "method-smap-omega-doy-dynamic",
            "SMAP 动态散射约束产品",
            "动态散射约束反演",
        ),
    ]
    _fake_catalog(monkeypatch, items)
    _fake_identity(
        monkeypatch,
        {
            "method-fy-omega-doy-dynamic": {
                "is_product_group": True,
                "source": "fy",
                "group_members": [
                    {"overlay_layer_id": "imported-abc", "variable": "vod",
                     "variable_label": "植被光学厚度"},
                ],
            },
            "method-smap-omega-doy-avg": {
                "is_product_group": True,
                "source": "smap",
                "group_members": [
                    {"overlay_layer_id": "imported-def", "variable": "vod",
                     "variable_label": "植被光学厚度"},
                ],
            },
            "method-smap-omega-doy-dynamic": {
                "is_product_group": True,
                "source": "smap",
                "group_members": [
                    {"overlay_layer_id": "imported-ghi", "variable": "vod",
                     "variable_label": "植被光学厚度"},
                ],
            },
        },
    )

    result = srt._search_layers({"query": "SMAP 的 VOD"}, cred=None, client_context=None)

    assert result["ok"] is True
    layers = result["layers"]
    ids = [L["layer_id"] for L in layers]
    # SMAP 的两个产品都必须排在风云产品前面
    smap_pos = [i for i, lid in enumerate(ids) if lid.startswith("method-smap")]
    fy_pos = [i for i, lid in enumerate(ids) if lid.startswith("method-fy")]
    assert smap_pos and fy_pos, ids
    assert max(smap_pos) < min(fy_pos), ids


def test_smap_vod_does_not_lose_candidates_when_english_used(monkeypatch):
    """英文 VOD 问法不能把 SMAP 产品整段过滤掉（曾经名称匹配失败后靠描述兜底）。"""
    items = [
        _fake_item(
            "method-smap-omega-doy-avg",
            "SMAP 平均散射约束产品",
            "omega_avg_daily 经典链",
        ),
    ]
    _fake_catalog(monkeypatch, items)
    _fake_identity(
        monkeypatch,
        {
            "method-smap-omega-doy-avg": {
                "is_product_group": True,
                "source": "smap",
                "group_members": [
                    {"overlay_layer_id": "imported-def", "variable": "vod",
                     "variable_label": "植被光学厚度"},
                ],
            },
        },
    )

    result = srt._search_layers({"query": "SMAP VOD"}, cred=None, client_context=None)

    assert result["ok"] is True
    assert result["count"] >= 1
    assert any("smap" in L["layer_id"] for L in result["layers"])


def test_sm_english_alias_still_hits(monkeypatch):
    """英文 SM 缩写同样应命中「土壤水分」（回归别名展开不只覆盖 vod）。"""
    items = [
        _fake_item(
            "method-smap-omega-doy-avg",
            "SMAP 平均散射约束产品",
            "经典链",
        ),
    ]
    _fake_catalog(monkeypatch, items)
    _fake_identity(
        monkeypatch,
        {
            "method-smap-omega-doy-avg": {
                "is_product_group": True,
                "source": "smap",
                "group_members": [
                    {"overlay_layer_id": "imported-def", "variable": "sm",
                     "variable_label": "土壤水分"},
                ],
            },
        },
    )

    result = srt._search_layers({"query": "SMAP SM"}, cred=None, client_context=None)

    assert result["ok"] is True
    assert result["count"] >= 1
