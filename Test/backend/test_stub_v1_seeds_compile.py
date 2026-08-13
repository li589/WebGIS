"""Compile smoke for stub_v1 system seeds."""

from __future__ import annotations

import pytest
import json
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
    "preprocess_mask_resample_basic",
    "gis_vector_raster_roundtrip_basic",
    "gis_contour_slope_basic",
    "stats_trend_anomaly_basic",
    "fusion_multi_source_merge_basic",
    "gis_watershed_basic",
    "stats_correlation_basic",
    "stats_correlation_report_basic",
    "stats_summary_chart_basic",
)


def test_stub_v1_seeds_compile() -> None:
    for workflow_id in _STUB_V1_SEEDS:
        path = _SEED_DIR / f"{workflow_id}.json"
        assert path.exists(), f"missing seed {path}"
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data.get("_meta") or {}
        assert meta.get("engine") == "python_provider", workflow_id
        assert "stub_v1" in meta.get("tags") or [], workflow_id
        assert meta.get("resource_profile") in {"standard", "heavy"}, workflow_id
        try:
            compiled = compile_litegraph_to_workflow_definition(
                workflow_id=workflow_id,
                name=data.get("name"),
                description=data.get("description"),
                nodes=data.get("nodes"),
                links=data.get("links"),
            )
        except WorkflowGraphCompileError as exc:
            pytest.fail(f"{workflow_id} compile failed: {exc}")
        assert compiled["metadata"]["engine"] == "python_provider", workflow_id
        assert len(compiled["nodes"]) >= 1, workflow_id
        # No stub interception leftovers: every module node has module_name
        for node in compiled["nodes"]:
            if node.get("node_type") == "module":
                assert str((node.get("params") or {}).get("module_name") or "").strip(), f"{workflow_id} node missing module_name"


def test_meta_and_heavy_modules() -> None:
    from app.services.resource_profile_resolver import (
        HEAVY_MODULE_NAMES,
        infer_resource_profile,
    )
    from shared.contracts.api_contracts import WorkflowResourceProfile

    assert "preprocess_reproject" in HEAVY_MODULE_NAMES, '"preprocess_reproject" in HEAVY_MODULE_NAMES'
    assert infer_resource_profile(
            current=WorkflowResourceProfile.standard,
            meta={"resource_profile": "heavy"},
        ) == WorkflowResourceProfile.heavy, 'infer_resource_profile(\n                current=WorkflowResourceProfile.standard,\n                meta={"resource_profile": "heavy"},\n            ) == WorkflowResourceProfile.heavy'
    assert infer_resource_profile(
            current=WorkflowResourceProfile.standard,
            definition={
                "nodes": [
                    {
                        "type": "preprocess/reproject",
                        "properties": {"module_name": "preprocess_reproject"},
                    }
                ]
            },
        ) == WorkflowResourceProfile.heavy, 'infer_resource_profile(\n                current=WorkflowResourceProfile.standard,\n                definition={\n                    "nodes": [\n                        {\n                            "type": "preprocess/reproject",\n                            "properties": {"module_name": "preprocess_reproject"},\n                        }\n                    ]\n                },\n            ) == WorkflowResourceProfile.heavy'
    assert infer_resource_profile(
            current=WorkflowResourceProfile.heavy,
            meta={"resource_profile": "standard"},
        ) == WorkflowResourceProfile.heavy, 'infer_resource_profile(\n                current=WorkflowResourceProfile.heavy,\n                meta={"resource_profile": "standard"},\n            ) == WorkflowResourceProfile.heavy'
    # Seed meta "standard" is a soft default; heavy graph modules still bump.
    assert infer_resource_profile(
            current=WorkflowResourceProfile.standard,
            meta={"resource_profile": "standard"},
            definition={
                "nodes": [
                    {
                        "type": "gis/watershed",
                        "properties": {"module_name": "gis_watershed"},
                    }
                ]
            },
        ) == WorkflowResourceProfile.heavy, 'infer_resource_profile(\n                current=WorkflowResourceProfile.standard,\n                meta={"resource_profile": "standard"},\n                definition={\n                    "nodes": [\n                        {\n                            "type": "gis/watershed",\n                            "properties": {"module_name": "gis_watershed"},\n                        }\n                    ]\n                },\n            ) == WorkflowResourceProfile.heavy'
