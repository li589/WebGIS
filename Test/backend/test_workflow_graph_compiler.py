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
    # productive work is request-bound on the single algorithm node.
    assert definition["edges"] == [], 'definition["edges"] == []'
    by_id = {n["node_id"]: n for n in definition["nodes"]}
    omega = by_id["n6"]
    assert omega["params"]["module_name"] == "omega_avg_daily", 'omega["params"]["module_name"] == "omega_avg_daily"'
    assert omega["input_bindings"].get("datasource_selection") == "request:datasource_selection", 'omega["input_bindings"].get("datasource_selection") == "request:datasource_selection"'
    assert omega["input_bindings"].get("algorithm_params") == "request:algorithm_params", 'omega["input_bindings"].get("algorithm_params") == "request:algorithm_params"'
    assert definition["outputs"][0]["source"] == "node:n6.manifest", 'definition["outputs"][0]["source"] == "node:n6.manifest"'
