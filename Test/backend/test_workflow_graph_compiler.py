"""Tests for LiteGraph → WorkflowDefinition compiler."""

from __future__ import annotations


import pytest
from app.services.workflow_graph_compiler import (
    WorkflowGraphCompileError,
    compile_litegraph_to_workflow_definition,
)


def test_compile_data_source_to_remote_fetch() -> None:
    definition = compile_litegraph_to_workflow_definition(
        workflow_id="wf_test",
        name="test",
        nodes=[
            {
                "id": 1,
                "type": "data/source",
                "title": "数据源",
                "properties": {
                    "path": "I:/Geograph_DataSet/Soil_Moisture/SMAP",
                    "dataset_key": "SMAP_L3",
                },
            },
            {
                "id": 2,
                "type": "download/remote_fetch",
                "title": "远程拉取",
                "properties": {"uri": "", "cred_profile": ""},
            },
        ],
        links=[[1, 1, 0, 2, 1, "data:source"]],  # from n1 out0 -> n2 in1 (data)
    )
    assert definition["workflow_id"] == "wf_test", 'definition["workflow_id"] == "wf_test"'
    assert len(definition["nodes"]) == 2, 'len(definition["nodes"]) == 2'
    assert definition["nodes"][0]["params"]["module_name"] == "data_source", 'definition["nodes"][0]["params"]["module_name"] == "data_source"'
    assert definition["nodes"][1]["params"]["module_name"] == "remote_fetch", 'definition["nodes"][1]["params"]["module_name"] == "remote_fetch"'
    assert len(definition["edges"]) == 1, 'len(definition["edges"]) == 1'
    assert definition["edges"][0]["from_port"] == "data", 'definition["edges"][0]["from_port"] == "data"'
    assert definition["edges"][0]["to_port"] == "data", 'definition["edges"][0]["to_port"] == "data"'
    assert definition["outputs"], 'definition["outputs"] is truthy'
    assert "manifest" in definition["outputs"][0]["name"], '"manifest" in definition["outputs"][0]["name"]'


def test_compile_weather_engine() -> None:
    definition = compile_litegraph_to_workflow_definition(
        workflow_id="wf_weather",
        nodes=[
            {
                "id": 1,
                "type": "weather/grid_fetch",
                "properties": {"layer_id": "temperature"},
            },
            {
                "id": 2,
                "type": "weather/temperature_render",
                "properties": {"latitude": 23.1, "longitude": 113.3},
            },
        ],
        links=[[1, 1, 0, 2, 0, "data:raster"]],
    )
    assert definition["metadata"]["engine"] == "weather", 'definition["metadata"]["engine"] == "weather"'
    assert definition["nodes"][0]["node_type"] == "weather_grid_fetch", 'definition["nodes"][0]["node_type"] == "weather_grid_fetch"'
    assert definition["nodes"][1]["node_type"] == "weather_temperature_grid", 'definition["nodes"][1]["node_type"] == "weather_temperature_grid"'


def test_compile_disabled_node_kept_but_edges_dropped() -> None:
    """properties.enabled=false：节点保留（executor 跳过）、悬挂边剔除、params 不泄漏 enabled。"""
    definition = compile_litegraph_to_workflow_definition(
        workflow_id="wf_disable",
        name="disable",
        nodes=[
            {
                "id": 1,
                "type": "data/source",
                "properties": {"path": "Soil_Moisture/SMAP", "dataset_key": "SMAP"},
            },
            {
                "id": 2,
                "type": "download/fy_download",
                "properties": {
                    "enabled": False,
                    "satellite": "FY3B",
                    "local_dir": "I:/x/FY3B/raw",
                },
            },
            {
                "id": 3,
                "type": "download/remote_fetch",
                "properties": {"uri": "", "cred_profile": ""},
            },
        ],
        links=[
            [0, 2, 0, 3, 1, "value:string"],
            [1, 1, 0, 3, 1, "value:string"],
        ],
    )
    nodes = {n["node_id"]: n for n in definition["nodes"]}
    assert nodes["n2"]["enabled"] is False, 'nodes["n2"]["enabled"] is False'
    assert nodes["n1"]["enabled"] is True, 'nodes["n1"]["enabled"] is True'
    assert "enabled" not in nodes["n2"]["params"], '"enabled" not in nodes["n2"]["params"]'
    edge_pairs = {(e["from_node"], e["to_node"]) for e in definition["edges"]}
    assert ("n2", "n3") not in edge_pairs, '("n2", "n3") not in edge_pairs'
    assert ("n1", "n3") in edge_pairs, '("n1", "n3") in edge_pairs'


def test_compile_all_nodes_disabled_rejected() -> None:
    with pytest.raises(WorkflowGraphCompileError):
        compile_litegraph_to_workflow_definition(
            workflow_id="wf_all_off",
            nodes=[
                {
                    "id": 1,
                    "type": "data/source",
                    "properties": {"enabled": False, "path": "x", "dataset_key": "k"},
                },
            ],
            links=[],
        )


def test_reject_mixed_weather_and_python() -> None:
    with pytest.raises(WorkflowGraphCompileError):
        compile_litegraph_to_workflow_definition(
            workflow_id="wf_mixed",
            nodes=[
                {
                    "id": 1,
                    "type": "weather/forecast_fetch",
                    "properties": {},
                },
                {
                    "id": 2,
                    "type": "data/source",
                    "properties": {"path": "/tmp"},
                },
            ],
            links=[],
        )


def test_compile_object_style_links() -> None:
    definition = compile_litegraph_to_workflow_definition(
        workflow_id="wf_obj",
        nodes=[
            {"id": 1, "type": "data/source", "properties": {"path": "/tmp"}},
            {"id": 2, "type": "download/remote_fetch", "properties": {}},
        ],
        links=[{"0": 9, "1": 1, "2": 0, "3": 2, "4": 1, "5": "data:source"}],
    )
    assert len(definition["edges"]) == 1, 'len(definition["edges"]) == 1'
    assert definition["edges"][0]["from_node"] == "n1", 'definition["edges"][0]["from_node"] == "n1"'
    assert definition["edges"][0]["to_node"] == "n2", 'definition["edges"][0]["to_node"] == "n2"'


def test_empty_graph() -> None:
    with pytest.raises(WorkflowGraphCompileError):
        compile_litegraph_to_workflow_definition(
            workflow_id="x", nodes=[], links=[]
        )


def test_compile_omega_block_seed_graph_path() -> None:
    import json
    from pathlib import Path

    seed_path = (
        Path(__file__).resolve().parents[2]
        / "Code"
        / "backend"
        / "workflow_seeds"
        / "system"
        / "omega_block_smap_single.json"
    )
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    definition = compile_litegraph_to_workflow_definition(
        workflow_id=seed["workflow_id"],
        name=seed.get("name"),
        nodes=seed.get("nodes") or [],
        links=seed.get("links") or [],
    )
    # Fan-in from data/source into timeseries.datasource_selection is scraped away.
    # Productive edge: timeseries.output_path → omega_block.input_mat
    edges = definition["edges"]
    assert len(edges) == 1, 'len(edges) == 1'
    assert edges[0]["from_node"] == "n5", 'edges[0]["from_node"] == "n5"'
    assert edges[0]["from_port"] == "output_path", 'edges[0]["from_port"] == "output_path"'
    assert edges[0]["to_node"] == "n6", 'edges[0]["to_node"] == "n6"'
    assert edges[0]["to_port"] == "input_mat", 'edges[0]["to_port"] == "input_mat"'

    by_id = {n["node_id"]: n for n in definition["nodes"]}
    ts_bindings = by_id["n5"]["input_bindings"]
    omega_bindings = by_id["n6"]["input_bindings"]
    assert ts_bindings.get("datasource_selection") == "request:datasource_selection", 'ts_bindings.get("datasource_selection") == "request:datasource_selection"'
    assert omega_bindings.get("datasource_selection") == "request:datasource_selection", 'omega_bindings.get("datasource_selection") == "request:datasource_selection"'
    assert omega_bindings.get("algorithm_params") == "request:algorithm_params", 'omega_bindings.get("algorithm_params") == "request:algorithm_params"'
    assert definition["outputs"][0]["source"] == "node:n6.manifest", 'definition["outputs"][0]["source"] == "node:n6.manifest"'


def test_compile_omega_avg_daily_seed_graph_path() -> None:
    import json
    from pathlib import Path

    seed_path = (
        Path(__file__).resolve().parents[2]
        / "Code"
        / "backend"
        / "workflow_seeds"
        / "system"
        / "omega_avg_daily_smap_single.json"
    )
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    definition = compile_litegraph_to_workflow_definition(
        workflow_id=seed["workflow_id"],
        name=seed.get("name"),
        nodes=seed.get("nodes") or [],
        links=seed.get("links") or [],
    )
    # Fan-in data/source → omega_avg_daily.datasource_selection is scraped;
    # productive work is request-bound on the single algorithm node. M3：补发布
    # output/map_layer 节点后，omega.manifest → map_layer.data 成为唯一边，
    # 终端输出改为 map_layer 节点的 manifest。
    edges = definition["edges"]
    assert len(edges) == 1, 'len(edges) == 1'
    assert edges[0]["from_node"] == "n6", 'edges[0]["from_node"] == "n6"'
    assert edges[0]["from_port"] == "manifest", 'edges[0]["from_port"] == "manifest"'
    assert edges[0]["to_node"] == "n8", 'edges[0]["to_node"] == "n8"'
    assert edges[0]["to_port"] == "data", 'edges[0]["to_port"] == "data"'
    by_id = {n["node_id"]: n for n in definition["nodes"]}
    omega = by_id["n6"]
    assert omega["params"]["module_name"] == "omega_avg_daily", 'omega["params"]["module_name"] == "omega_avg_daily"'
    assert omega["input_bindings"].get("datasource_selection") == "request:datasource_selection", 'omega["input_bindings"].get("datasource_selection") == "request:datasource_selection"'
    assert omega["input_bindings"].get("algorithm_params") == "request:algorithm_params", 'omega["input_bindings"].get("algorithm_params") == "request:algorithm_params"'
    map_layer = by_id["n8"]
    assert map_layer["params"]["module_name"] == "output_map_layer", 'map_layer["params"]["module_name"] == "output_map_layer"'
    assert map_layer["params"]["layer_id"] == "method-smap-omega-doy-avg", 'map_layer["params"]["layer_id"] == "method-smap-omega-doy-avg"'
    assert definition["outputs"][0]["source"] == "node:n8.manifest", 'definition["outputs"][0]["source"] == "node:n8.manifest"'


def test_compile_online_seed_download_nodes_bind_request_datasource() -> None:
    """在线种子下载节点必须绑定 request:datasource_selection（凭据回退回归）。

    模板缺 datasource_selection 输入端口时下载节点 inputs 为空 dict，
    ``portal_credentials_resolve`` 懒解析标志无法下发 → earthdata 凭据
    注入失败（run-64ed5b9e3d77 回归）。
    """
    import json
    from pathlib import Path

    for seed_name, download_modules in (
        ("omega_sf_fenkuai_fy_online", {"fy_download"}),
        ("omega_sf_fenkuai_smap_online", {"nsidc_smap_download"}),
    ):
        seed_path = (
            Path(__file__).resolve().parents[2]
            / "Code"
            / "backend"
            / "workflow_seeds"
            / "system"
            / f"{seed_name}.json"
        )
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        definition = compile_litegraph_to_workflow_definition(
            workflow_id=seed["workflow_id"],
            name=seed.get("name"),
            nodes=seed.get("nodes") or [],
            links=seed.get("links") or [],
        )
        matched = 0
        for node in definition["nodes"]:
            module_name = (node.get("params") or {}).get("module_name")
            if module_name not in download_modules:
                continue
            matched += 1
            assert node["input_bindings"].get("datasource_selection") == (
                "request:datasource_selection"
            ), f"{seed_name}:{node['node_id']} must bind request:datasource_selection"
        assert matched > 0, f"{seed_name} should contain {download_modules} node(s)"
