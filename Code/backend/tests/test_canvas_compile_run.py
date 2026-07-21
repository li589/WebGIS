"""Compile LiteGraph canvas and execute with WorkflowRunner (local config_read)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


class CanvasCompileRunTests(unittest.TestCase):
    def test_compile_and_run_data_source_to_config_read(self) -> None:
        import contracts.job  # noqa: F401
        from app.services.workflow_graph_compiler import compile_litegraph_to_workflow_definition
        from contracts.job import JobRequest
        from contracts.product import OutputSpec
        from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
        from modules.registry import list_modules
        from workflow.executor import WorkflowRunner
        from workflow.serialization import coerce_workflow_definition

        self.assertIn("config_read", list_modules())

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            cfg = workspace / "demo.json"
            cfg.write_text(json.dumps({"k": 42}), encoding="utf-8")

            compiled = compile_litegraph_to_workflow_definition(
                workflow_id="canvas_e2e",
                nodes=[
                    {
                        "id": 1,
                        "type": "data/source",
                        "properties": {"path": str(cfg), "dataset_key": ""},
                    },
                    {
                        "id": 2,
                        "type": "config/read",
                        "properties": {"format": "json"},
                    },
                ],
                links=[{"0": 1, "1": 1, "2": 0, "3": 2, "4": 1, "5": "data:source"}],
            )
            definition = coerce_workflow_definition(compiled)

            start = datetime(2023, 1, 1, tzinfo=timezone.utc)
            end = datetime(2023, 1, 2, tzinfo=timezone.utc)
            request = JobRequest(
                job_id="job-canvas-e2e",
                pipeline_name="workflow",
                task_type="canvas",
                region=RegionSpec(kind="bbox", value={"west": 0, "south": 0, "east": 1, "north": 1}),
                time_range=TimeRange(start=start, end=end),
                datasource_selection={},
                algorithm_params={},
                output_spec=OutputSpec(),
                workflow_definition=definition,
            )
            rt = RuntimeContext(
                job_id="job-canvas-e2e",
                run_id="run-canvas-e2e",
                workspace=workspace,
                tmp_dir=workspace / "tmp",
                cache_dir=workspace / "cache",
            )
            (workspace / "tmp").mkdir(exist_ok=True)
            (workspace / "cache").mkdir(exist_ok=True)

            result = WorkflowRunner().run(definition, request, rt)
            self.assertIn("manifest", result.outputs)
            self.assertEqual(result.execution_order, ["n1", "n2"])
            # Ensure config was actually read
            n2_out = result.node_outputs["n2"]
            self.assertEqual(n2_out.get("config"), {"k": 42})


if __name__ == "__main__":
    unittest.main()
