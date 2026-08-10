"""Compile smoke for stub_v1 system seeds."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.services.workflow_graph_compiler import (
    WorkflowGraphCompileError,
    compile_litegraph_to_workflow_definition,
)

_SEED_DIR = (
    Path(__file__).resolve().parents[2]
    / "Code"
    / "backend"
    / "workflow_seeds"
    / "system"
)

_STUB_V1_SEEDS = (
    "preprocess_clip_reproject_basic",
    "gis_raster_calc_reclassify_basic",
    "gis_buffer_zonal_basic",
    "stats_mean_summary_report_basic",
    "fusion_idw_interpolate_basic",
)


class StubV1SeedsCompileTests(unittest.TestCase):
    def test_stub_v1_seeds_compile(self) -> None:
        for workflow_id in _STUB_V1_SEEDS:
            path = _SEED_DIR / f"{workflow_id}.json"
            self.assertTrue(path.exists(), f"missing seed {path}")
            data = json.loads(path.read_text(encoding="utf-8"))
            meta = data.get("_meta") or {}
            self.assertEqual(meta.get("engine"), "python_provider", workflow_id)
            self.assertIn("stub_v1", meta.get("tags") or [], workflow_id)
            self.assertIn(meta.get("resource_profile"), {"standard", "heavy"}, workflow_id)
            try:
                compiled = compile_litegraph_to_workflow_definition(
                    workflow_id=workflow_id,
                    name=data.get("name"),
                    description=data.get("description"),
                    nodes=data.get("nodes"),
                    links=data.get("links"),
                )
            except WorkflowGraphCompileError as exc:
                self.fail(f"{workflow_id} compile failed: {exc}")
            self.assertEqual(
                compiled["metadata"]["engine"], "python_provider", workflow_id
            )
            self.assertGreaterEqual(len(compiled["nodes"]), 1, workflow_id)
            # No stub interception leftovers: every module node has module_name
            for node in compiled["nodes"]:
                if node.get("node_type") == "module":
                    self.assertTrue(
                        str((node.get("params") or {}).get("module_name") or "").strip(),
                        f"{workflow_id} node missing module_name",
                    )


class ResourceProfileResolverTests(unittest.TestCase):
    def test_meta_and_heavy_modules(self) -> None:
        from app.services.resource_profile_resolver import (
            HEAVY_MODULE_NAMES,
            infer_resource_profile,
        )
        from shared.contracts.api_contracts import WorkflowResourceProfile

        self.assertIn("preprocess_reproject", HEAVY_MODULE_NAMES)
        self.assertEqual(
            infer_resource_profile(
                current=WorkflowResourceProfile.standard,
                meta={"resource_profile": "heavy"},
            ),
            WorkflowResourceProfile.heavy,
        )
        self.assertEqual(
            infer_resource_profile(
                current=WorkflowResourceProfile.standard,
                definition={
                    "nodes": [
                        {
                            "type": "preprocess/reproject",
                            "properties": {"module_name": "preprocess_reproject"},
                        }
                    ]
                },
            ),
            WorkflowResourceProfile.heavy,
        )
        self.assertEqual(
            infer_resource_profile(
                current=WorkflowResourceProfile.heavy,
                meta={"resource_profile": "standard"},
            ),
            WorkflowResourceProfile.heavy,
        )


if __name__ == "__main__":
    unittest.main()
