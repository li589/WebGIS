"""Tests for GIS analysis publish path, exclusivity, and tool catalog."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_analysis_tools_catalog_loads():
    from app.services.analysis_tool_catalog import get_tool, list_tools_for_layer, load_analysis_tools

    tools = load_analysis_tools()
    assert len(tools) >= 5
    ids = {t.tool_id for t in tools}
    assert "gis.buffer" in ids
    # 直方图工具已从分析面板移除（保留 workflow seed 供编辑器手动编排）
    assert "stats.histogram" not in ids
    assert get_tool("gis.clip") is not None

    weather = list_tools_for_layer(layer_id="wind", is_weather=True)
    assert weather.layer_kind == "weather"
    enabled = [t for t in weather.items if t.enabled]
    assert all(t.tool_id == "gis.buffer" or "point" in t.input_kinds for t in enabled) or len(enabled) <= 1

    raster = list_tools_for_layer(layer_id="imported-abc", has_raster=True)
    assert raster.layer_kind == "raster"
    assert any(t.tool_id == "gis.reclassify" and t.enabled for t in raster.items)


def test_analysis_seeds_compile():
    from app.services.workflow_graph_compiler import (
        compile_litegraph_to_workflow_definition,
    )
    from app.services.workflow_request_resolver import _filter_invalid_edges

    seed_dir = (
        Path(__file__).resolve().parents[2]
        / "Code"
        / "backend"
        / "workflow_seeds"
        / "system"
    )
    for name in (
        "analysis_buffer.json",
        "analysis_zonal_stats.json",
        "analysis_clip.json",
        "analysis_histogram.json",
        "analysis_reclassify.json",
    ):
        data = json.loads((seed_dir / name).read_text(encoding="utf-8"))
        assert "ui-panel" in (data.get("_meta") or {}).get("tags", [])
        compiled = compile_litegraph_to_workflow_definition(
            workflow_id=data["workflow_id"],
            name=data.get("name"),
            description=data.get("description"),
            nodes=data.get("nodes"),
            links=data.get("links"),
        )
        _filter_invalid_edges(compiled)
        assert compiled["metadata"]["engine"] == "python_provider"
        assert len(compiled["nodes"]) >= 1


def test_generic_raster_map_layer_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    from rasterio.transform import from_bounds

    from app.services.python_provider_result_builder import PythonProviderResultBuilder
    from shared.contracts.api_contracts import (
        ResultKind,
        WorkflowCommandType,
        WorkflowSubmitRequest,
    )

    tif = tmp_path / "smoke.tif"
    transform = from_bounds(100.0, 28.0, 101.0, 29.0, 8, 8)
    with rasterio.open(
        tif,
        "w",
        driver="GTiff",
        height=8,
        width=8,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as ds:
        ds.write(np.ones((8, 8), dtype="float32"), 1)

    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    monkeypatch.setattr(
        "app.data_io.services.paths.IMPORTS_DIR",
        imports_dir,
    )
    monkeypatch.setattr(
        "app.data_io.services.raster_register.IMPORTS_DIR",
        imports_dir,
    )

    builder = PythonProviderResultBuilder()
    refs = builder.build_product_map_layer_refs(
        run_id="run-gis-raster-001",
        requested_at=datetime.now(timezone.utc),
        payload=WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            layer_id="analysis:test",
            requested_outputs=[ResultKind.map_layer],
        ),
        result_dto={
            "products": [
                {
                    "name": "clip.tif",
                    "type": "raster",
                    "uri": str(tif),
                    "variable": "raster",
                    "tags": {"module": "preprocess_clip", "kind": "raster"},
                }
            ]
        },
    )
    assert len(refs) == 1
    assert refs[0].result_kind is ResultKind.map_layer
    assets = (refs[0].inline_data or {}).get("layer_assets") or {}
    assert str(assets.get("overlay_layer_id") or "").startswith("imported-")


def test_exclusivity_cancel_then_accept(monkeypatch: pytest.MonkeyPatch):
    from app.services.workflow.submission_service import WorkflowSubmissionService
    from shared.contracts.api_contracts import (
        ExecutionStatus,
        WorkflowCommandType,
        WorkflowRunStatusResponse,
        WorkflowSubmitRequest,
    )

    repo = MagicMock()
    prior = WorkflowRunStatusResponse(
        run_id="run-old",
        status=ExecutionStatus.running,
        command_type=WorkflowCommandType.analysis,
        progress=40,
        message="running",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        status_url="/x",
        events_url="/y",
        executor_metadata={"analysis_exclusivity_key": "layer-a:gis.clip"},
    )
    repo.list_runs.return_value = [prior]
    repo.get_run_request_json.return_value = None

    lifecycle = MagicMock()
    svc = WorkflowSubmissionService(repository=repo)
    svc.set_lifecycle_service(lifecycle)

    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        layer_id="layer-a",
        parameters={"analysis_exclusivity_key": "layer-a:gis.clip"},
    )
    # Avoid full submit path — unit-test cancel helper only
    n = svc._cancel_exclusive_analysis_runs(payload)
    assert n == 1
    lifecycle.cancel_workflow_run.assert_called_once_with("run-old")


def test_build_analysis_contour_request_injects_path(tmp_path: Path, monkeypatch):
    from app.services import analysis_run_service as ars
    from shared.contracts.api_contracts import AnalysisRunRequest

    tif = tmp_path / "a.tif"
    tif.write_bytes(b"not-a-real-tif")  # path only for injection test

    def fake_resolve(overlay_id: str):
        return tif

    monkeypatch.setattr(ars, "resolve_overlay_source_path", fake_resolve)

    seed = {
        "_meta": {"engine": "python_provider"},
        "workflow_id": "analysis_contour",
        "nodes": [
            {
                "id": 1,
                "type": "data/source",
                "properties": {"path": "old", "dataset_key": "input_path"},
            },
            {"id": 2, "type": "gis/contour", "properties": {"interval": 100}},
        ],
        "links": [],
    }
    monkeypatch.setattr(
        "app.services.workflow_definition_service.get_definition",
        lambda wid: seed if wid == "analysis_contour" else None,
    )

    req = AnalysisRunRequest(
        tool_id="gis.contour",
        layer_id="imported-xyz",
        overlay_layer_id="imported-xyz",
        params={"interval": 50},
    )
    payload = ars.build_analysis_submit_request(req)
    assert payload.parameters.get("analysis_exclusivity_key") == "imported-xyz:gis.contour"
    algo = payload.algorithm_request
    assert not isinstance(algo, dict)
    graph = algo.workflow_definition
    assert isinstance(graph, dict)
    nodes = graph["nodes"]
    assert nodes[0]["properties"]["path"] == str(tif)
    assert nodes[1]["properties"]["interval"] == 50
