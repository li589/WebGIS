"""GLDAS online seed: node template + graph compile attachability."""

from __future__ import annotations


def test_seed_compiles_with_gldas_download_node() -> None:
    from app.services.node_template_registry import get_node_template
    from app.services.workflow_definition_service import (
        _ensure_dirs,
        get_definition,
    )
    from app.services.workflow_graph_compiler import (
        compile_litegraph_to_workflow_definition,
    )

    # 确保 system seeds 已同步到运行时目录（CI 全新 data root 需显式触发，
    # 否则 get_definition 查不到尚未同步的定义）
    _ensure_dirs()

    tmpl = get_node_template("download/gldas_download")
    assert tmpl is not None, 'tmpl is not None'
    assert tmpl is not None
    assert tmpl.get("node_class") == "gldas_download", 'tmpl.get("node_class") == "gldas_download"'

    defn = get_definition("omega_avg_daily_gldas_online")
    assert defn is not None, 'defn is not None'
    assert defn is not None
    types = [n.get("type") for n in defn.get("nodes") or []]
    assert "download/gldas_download" in types, '"download/gldas_download" in types'
    assert "module/omega_avg_daily" in types, '"module/omega_avg_daily" in types'

    compiled = compile_litegraph_to_workflow_definition(
        workflow_id="omega_avg_daily_gldas_online",
        name=defn.get("name"),
        description=defn.get("description"),
        nodes=defn.get("nodes", []),
        links=defn.get("links", []),
    )
    module_names = [
        (n.get("params") or {}).get("module_name")
        for n in compiled.get("nodes") or []
    ]
    assert "gldas_download" in module_names, '"gldas_download" in module_names'
    assert "omega_avg_daily" in module_names, '"omega_avg_daily" in module_names'
    edges = compiled.get("edges") or []
    # 编译器归一化（_normalize_python_edges）：指向 datasource_selection /
    # daily_mat_sources / time_range / bbox / region 的 fan-in 边会被有意丢弃，
    # 数据源改由 request.datasource_selection 绑定注入。故此处不要求 n1→n7 边存在，
    # 只验证存活边不会命中被刮取的 fan-in 端口（防止未来回归）。
    scraped_fan_ins = {"datasource_selection", "daily_mat_sources", "time_range", "bbox", "region"}
    assert all(e.get("to_port") not in scraped_fan_ins for e in edges), 'all(e.get("to_port") not in scraped_fan_ins for e in edges) is truthy'
