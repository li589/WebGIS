"""Tests for LiteGraph → WorkflowDefinition compiler."""

from __future__ import annotations

import unittest

from app.services.workflow_graph_compiler import (
    WorkflowGraphCompileError,
    compile_litegraph_to_workflow_definition,
)


class WorkflowGraphCompilerTests(unittest.TestCase):
    def test_compile_data_source_to_remote_fetch(self) -> None:
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
        self.assertEqual(definition["workflow_id"], "wf_test")
        self.assertEqual(len(definition["nodes"]), 2)
        self.assertEqual(definition["nodes"][0]["params"]["module_name"], "data_source")
        self.assertEqual(
            definition["nodes"][1]["params"]["module_name"], "remote_fetch"
        )
        self.assertEqual(len(definition["edges"]), 1)
        self.assertEqual(definition["edges"][0]["from_port"], "data")
        self.assertEqual(definition["edges"][0]["to_port"], "data")
        self.assertTrue(definition["outputs"])
        self.assertIn("manifest", definition["outputs"][0]["name"])

    def test_compile_weather_engine(self) -> None:
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
        self.assertEqual(definition["metadata"]["engine"], "weather")
        self.assertEqual(definition["nodes"][0]["node_type"], "weather_grid_fetch")
        self.assertEqual(
            definition["nodes"][1]["node_type"], "weather_temperature_grid"
        )

    def test_reject_mixed_weather_and_python(self) -> None:
        with self.assertRaises(WorkflowGraphCompileError):
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

    def test_compile_object_style_links(self) -> None:
        definition = compile_litegraph_to_workflow_definition(
            workflow_id="wf_obj",
            nodes=[
                {"id": 1, "type": "data/source", "properties": {"path": "/tmp"}},
                {"id": 2, "type": "download/remote_fetch", "properties": {}},
            ],
            links=[{"0": 9, "1": 1, "2": 0, "3": 2, "4": 1, "5": "data:source"}],
        )
        self.assertEqual(len(definition["edges"]), 1)
        self.assertEqual(definition["edges"][0]["from_node"], "n1")
        self.assertEqual(definition["edges"][0]["to_node"], "n2")

    def test_empty_graph(self) -> None:
        with self.assertRaises(WorkflowGraphCompileError):
            compile_litegraph_to_workflow_definition(
                workflow_id="x", nodes=[], links=[]
            )

    def test_compile_omega_block_seed_graph_path(self) -> None:
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
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["from_node"], "n5")
        self.assertEqual(edges[0]["from_port"], "output_path")
        self.assertEqual(edges[0]["to_node"], "n6")
        self.assertEqual(edges[0]["to_port"], "input_mat")

        by_id = {n["node_id"]: n for n in definition["nodes"]}
        ts_bindings = by_id["n5"]["input_bindings"]
        omega_bindings = by_id["n6"]["input_bindings"]
        self.assertEqual(
            ts_bindings.get("datasource_selection"), "request:datasource_selection"
        )
        self.assertEqual(
            omega_bindings.get("datasource_selection"), "request:datasource_selection"
        )
        self.assertEqual(
            omega_bindings.get("algorithm_params"), "request:algorithm_params"
        )
        self.assertEqual(definition["outputs"][0]["source"], "node:n6.manifest")

    def test_compile_omega_avg_daily_seed_graph_path(self) -> None:
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
        self.assertEqual(definition["edges"], [])
        by_id = {n["node_id"]: n for n in definition["nodes"]}
        omega = by_id["n6"]
        self.assertEqual(omega["params"]["module_name"], "omega_avg_daily")
        self.assertEqual(
            omega["input_bindings"].get("datasource_selection"),
            "request:datasource_selection",
        )
        self.assertEqual(
            omega["input_bindings"].get("algorithm_params"),
            "request:algorithm_params",
        )
        self.assertEqual(definition["outputs"][0]["source"], "node:n6.manifest")


if __name__ == "__main__":
    unittest.main()
