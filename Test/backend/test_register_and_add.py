"""register-and-add 原子端点 + portal_workflow_map 回归锁（2026-08-25 Wave 2/3）。

用户决策（2026-08-25）：注册统一 site_compatible（grants=选集记录不限制
访问）；无映射门户无 workflow_hint。

Wave 3：有种子层映射（layer_id）的门户自动提交图层工作流；提交失败降级。
注意：不做手动 sys.path 操纵——conftest 已统一处理（手动把 provider 根
insert 到最前会触发 B-N8 包名遮蔽：algorithms.providers 不可导入）。
"""

from __future__ import annotations

import asyncio


def test_portal_workflow_map_entries():
    from app.services.portal_workflow_map import (
        PORTAL_WORKFLOW_MAP,
        get_portal_workflow_mapping,
    )

    # 首批站点（与前端 portal-workflow-map.ts 同源）
    assert set(PORTAL_WORKFLOW_MAP) == {
        "nsidc_data",
        "nasa_gldas",
        "nasa_ges_disc",
        "cds_era5",
        "esa_copernicus",
        "esa_download",
        "noaa_nomads",
        "cma_nsmc",
        "cma_data",
    }
    nsidc = get_portal_workflow_mapping("nsidc_data")
    assert nsidc is not None
    assert nsidc["workflow"] == "nsidc_smap_download"
    assert nsidc["default_dataset_keys"] == ["SPL3SMP_E"]
    assert get_portal_workflow_mapping("unknown_portal") is None


def test_build_workflow_hint_with_default_dataset():
    from app.services.portal_workflow_map import build_workflow_hint

    hint = build_workflow_hint("nsidc_data", [])
    assert hint is not None
    assert hint["dataset_keys"] == ["SPL3SMP_E"]
    assert hint["node_type"] == "download/nsidc_smap_download"
    # NSIDC 有种子层（ref-smap-sm-202512-l3）→ 自动链就绪（Wave 3）
    assert hint["layer_id"] == "ref-smap-sm-202512-l3"
    assert hint["auto_chain_ready"] is True
    # 下载类节点自动附最近 30 天建议时间范围
    assert "start_date" in hint["params"] and "end_date" in hint["params"]
    # 用户显式选集优先于默认
    hint2 = build_workflow_hint("nasa_gldas", ["GLDAS_NOAH025_3H"])
    assert hint2["dataset_keys"] == ["GLDAS_NOAH025_3H"]
    # GLDAS 暂无种子层 → hint 引导手动编排
    assert hint2["layer_id"] is None
    assert hint2["auto_chain_ready"] is False


def test_build_workflow_hint_no_mapping():
    from app.services.portal_workflow_map import build_workflow_hint

    assert build_workflow_hint("unknown_portal", ["X"]) is None


def test_register_and_add_endpoint_atomic(monkeypatch):
    """端点原子性：注册 site_compatible + grants 记录 + hint 映射/无映射。

    直接调用路由函数并 mock config_service（settings frozen + 注册表
    单例无 reset，端到端 DB 隔离成本高——服务层已有专属测试覆盖）。
    """
    from shared.contracts.config_contracts import RegisterAndAddRequest

    from app.api import config_routes

    async def _run(req):
        return await config_routes.register_and_add_remote_source(req)

    calls = {"sources": [], "grants": []}

    def fake_upsert_source(alias, payload):
        calls["sources"].append((alias, payload))
        return {
            "remote_source_id": alias,
            "kind": payload["kind"],
            "ref_id": payload["ref_id"],
            "remote_path": payload.get("remote_path", ""),
            "display_name": payload.get("display_name", ""),
            "cache_policy": "standard",
            "access_mode": payload["access_mode"],
            "archived": False,
            "ref_exists": True,
            "ref": None,
        }

    def fake_upsert_grant(grant_id, payload):
        calls["grants"].append((grant_id, payload))
        return {"grant_id": grant_id, **payload}

    monkeypatch.setattr(
        config_routes.config_service, "upsert_remote_source_entry", fake_upsert_source
    )
    monkeypatch.setattr(
        config_routes.config_service, "upsert_remote_dataset_grant", fake_upsert_grant
    )

    # mock 自动链提交（避免真实 Celery dispatch；Wave 3）
    submit_calls = []

    class _FakeAccepted:
        def __init__(self, run_id: str):
            self.run_id = run_id

    def fake_submit_workflow(payload):
        submit_calls.append(payload)
        return _FakeAccepted(f"run-{len(submit_calls)}")

    from app.services.workflow import service_container as _sc

    monkeypatch.setattr(
        _sc.submission_service, "submit_workflow", fake_submit_workflow
    )

    # ① 有映射门户 + 显式选集（GLDAS 无种子层 → 不自动提交）
    resp = asyncio.run(_run(
        RegisterAndAddRequest(
            alias="nasa_gldas",
            kind="portal",
            ref_id="nasa_gldas",
            display_name="GLDAS",
            dataset_keys=["GLDAS_NOAH025_3H"],
        )
    ))
    # 注册统一 site_compatible（用户决策：弃 legacy）
    assert calls["sources"][0][1]["access_mode"] == "site_compatible"
    # 选集写入 grants（记录，不限制访问）
    assert len(calls["grants"]) == 1
    assert calls["grants"][0][0] == "nasa_gldas__GLDAS_NOAH025_3H"
    # hint 跟随选集；无种子层 → 不触发自动链
    assert resp.workflow_hint is not None
    assert resp.workflow_hint.dataset_keys == ["GLDAS_NOAH025_3H"]
    assert resp.workflow_hint.workflow == "gldas_download"
    assert resp.run_id is None

    # ② 有种子层映射（NSIDC）+ 空选集 → 自动提交图层工作流
    calls["grants"].clear()
    resp2 = asyncio.run(_run(
        RegisterAndAddRequest(
            alias="nsidc_data",
            kind="portal",
            ref_id="nsidc_data",
            dataset_keys=[],
        )
    ))
    assert calls["grants"] == []
    assert resp2.workflow_hint.dataset_keys == ["SPL3SMP_E"]
    # 自动链：提交了 ref-smap-sm-202512-l3 层的 analysis 工作流
    assert len(submit_calls) == 1
    assert submit_calls[0].layer_id == "ref-smap-sm-202512-l3"
    assert submit_calls[0].command_type.value == "analysis"
    # 参数不注入（layer 工作流参数由 python_provider bridge 按 layer
    # 配置自组装——注入下载节点参数会致 SMAP 日期解析失败，实测教训）
    assert not submit_calls[0].parameters
    assert resp2.run_id == "run-1"
    assert "已自动提交" in resp2.auto_chain_message

    # ③ 无映射门户 → hint=None 但注册成功
    resp3 = asyncio.run(_run(
        RegisterAndAddRequest(
            alias="some_portal",
            kind="portal",
            ref_id="unknown_portal",
            dataset_keys=["X"],
        )
    ))
    assert resp3.workflow_hint is None
    assert resp3.remote_source.remote_source_id == "some_portal"
    assert resp3.run_id is None

    # ④ 存储源：无 grants（dataset 概念仅门户）+ 无 hint
    calls["grants"].clear()
    resp4 = asyncio.run(_run(
        RegisterAndAddRequest(
            alias="nas-1",
            kind="storage_profile",
            ref_id="nas-1",
            remote_path="/data/fy",
        )
    ))
    assert calls["grants"] == []
    assert resp4.workflow_hint is None
    assert resp4.run_id is None
    assert calls["sources"][-1][1]["remote_path"] == "/data/fy"


def test_register_and_add_auto_chain_failure_degrades(monkeypatch):
    """自动链提交失败（容量满/异常）→ 降级提示，注册本身成功。"""
    import asyncio

    from shared.contracts.config_contracts import RegisterAndAddRequest

    from app.api import config_routes

    def fake_upsert_source(alias, payload):
        return {
            "remote_source_id": alias,
            "kind": payload["kind"],
            "ref_id": payload["ref_id"],
            "remote_path": payload.get("remote_path", ""),
            "display_name": payload.get("display_name", ""),
            "cache_policy": "standard",
            "access_mode": payload["access_mode"],
            "archived": False,
            "ref_exists": True,
            "ref": None,
        }

    monkeypatch.setattr(
        config_routes.config_service, "upsert_remote_source_entry", fake_upsert_source
    )
    monkeypatch.setattr(
        config_routes.config_service,
        "upsert_remote_dataset_grant",
        lambda gid, p: {"grant_id": gid, **p},
    )

    def boom(payload):
        raise RuntimeError("capacity exhausted")

    from app.services.workflow import service_container as _sc

    monkeypatch.setattr(_sc.submission_service, "submit_workflow", boom)

    async def _run(req):
        return await config_routes.register_and_add_remote_source(req)

    resp = asyncio.run(_run(
        RegisterAndAddRequest(
            alias="nsidc_data",
            kind="portal",
            ref_id="nsidc_data",
            dataset_keys=[],
        )
    ))
    # 注册成功（不因自动链失败而 500）
    assert resp.remote_source.remote_source_id == "nsidc_data"
    assert resp.run_id is None
    assert "自动提交工作流失败" in resp.auto_chain_message
