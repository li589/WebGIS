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
                    "properties": {"path": "I:/Geograph_DataSet/SMAP", "dataset_key": "SMAP_L3"},
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
        self.assertEqual(definition["nodes"][1]["params"]["module_name"], "remote_fetch")
        self.assertEqual(len(definition["edges"]), 1)
        self.assertEqual(definition["edges"][0]["from_port"], "data")
        self.assertEqual(definition["edges"][0]["to_port"], "data")
        self.assertTrue(definition["outputs"])
        self.assertIn("manifest", definition["outputs"][0]["name"])

    def test_reject_weather_engine(self) -> None:
        with self.assertRaises(WorkflowGraphCompileError):
            compile_litegraph_to_workflow_definition(
                workflow_id="wf_bad",
                nodes=[
                    {
                        "id": 1,
                        "type": "weather/forecast_fetch",
                        "properties": {},
                    }
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
            compile_litegraph_to_workflow_definition(workflow_id="x", nodes=[], links=[])


if __name__ == "__main__":
    unittest.main()
