"""Tests for chart/table emission from python provider result builder."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from shared.contracts.api_contracts import (
    ResultKind,
    WorkflowCommandType,
    WorkflowSubmitRequest,
)


def test_build_product_ref_emits_chart_and_table(tmp_path: Path):
    from app.services.python_provider_result_builder import PythonProviderResultBuilder

    chart_path = tmp_path / "demo.chart.json"
    table_path = tmp_path / "demo.table.json"
    chart_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "chart_type": "histogram",
                "title": "Demo",
                "x_label": "v",
                "y_label": "c",
                "unit": "",
                "series": [{"name": "count", "x": [0.5, 1.5], "y": [3, 7]}],
                "x": [0.5, 1.5],
                "y": [3, 7],
                "series_name": "count",
            }
        ),
        encoding="utf-8",
    )
    table_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "title": "Demo table",
                "columns": ["bin", "count"],
                "rows": [[0, 3], [1, 7]],
            }
        ),
        encoding="utf-8",
    )

    builder = PythonProviderResultBuilder()
    now = datetime.now(timezone.utc)
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        layer_id="test-layer",
        requested_outputs=[ResultKind.json, ResultKind.chart, ResultKind.table],
    )
    refs = builder.build_result_refs(
        run_id="run-test-chart-001",
        payload=payload,
        requested_at=now,
        request_payload={"module_name": "stats_histogram"},
        job_result={"status": "succeeded"},
        result_dto={
            "products": [
                {
                    "name": "chart",
                    "type": "chart_spec",
                    "uri": str(chart_path),
                    "variable": "x",
                    "tags": {"kind": "chart"},
                },
                {
                    "name": "table",
                    "type": "table_spec",
                    "uri": str(table_path),
                    "variable": "x",
                    "tags": {"kind": "table"},
                },
            ]
        },
    )
    kinds = {r.result_kind for r in refs}
    assert ResultKind.chart in kinds
    assert ResultKind.table in kinds
    chart_ref = next(r for r in refs if r.result_kind is ResultKind.chart)
    assert chart_ref.inline_data is not None
    assert chart_ref.inline_data.get("chart_type") == "histogram"
    table_ref = next(r for r in refs if r.result_kind is ResultKind.table)
    assert table_ref.inline_data is not None
    assert table_ref.inline_data.get("columns") == ["bin", "count"]


def test_omega_sf_map_layers_skip_static_omega_when_block_series_exists() -> None:
    from app.services.python_provider_result_builder import PythonProviderResultBuilder

    class CapturingBuilder(PythonProviderResultBuilder):
        def _build_product_map_layer_ref(self, **kwargs):
            return kwargs["product"]["type"]

    refs = CapturingBuilder().build_product_map_layer_refs(
        run_id="run-omega-three-layers",
        requested_at=datetime.now(timezone.utc),
        payload=WorkflowSubmitRequest(command_type=WorkflowCommandType.analysis),
        result_dto={
            "products": [
                {"type": "omega_sf_omega_pixel"},
                {"type": "omega_sf_sm_block_dir"},
                {"type": "omega_sf_vod_block_dir"},
                {"type": "omega_sf_omega_block_dir"},
            ]
        },
    )

    assert refs == [
        "omega_sf_sm_block_dir",
        "omega_sf_vod_block_dir",
        "omega_sf_omega_block_dir",
    ]


def test_histogram_and_chart_nodes_executable():
    from app.services.node_template_registry import get_node_template
    from app.services.python_provider_bridge_service import (
        _PENDING_IMPLEMENTATION_MODULES,
    )

    hist = get_node_template("stats/histogram")
    chart = get_node_template("viz/chart_generate")
    assert hist is not None and hist.get("executable") is True
    assert chart is not None and chart.get("executable") is True
    assert "stats_histogram" not in _PENDING_IMPLEMENTATION_MODULES
    assert "viz_chart_generate" not in _PENDING_IMPLEMENTATION_MODULES


def test_analysis_seeds_compile():
    from app.services.workflow_graph_compiler import (
        compile_litegraph_to_workflow_definition,
    )
    from app.services.workflow_request_resolver import _filter_invalid_edges
    import json
    from pathlib import Path

    seed_dir = (
        Path(__file__).resolve().parents[2]
        / "Code"
        / "backend"
        / "workflow_seeds"
        / "system"
    )
    for name in (
        "raster_histogram_basic.json",
        "raster_zonal_stats_aligned.json",
        "raster_timeseries_curve.json",
    ):
        data = json.loads((seed_dir / name).read_text(encoding="utf-8"))
        compiled = compile_litegraph_to_workflow_definition(
            workflow_id=data["workflow_id"],
            name=data.get("name"),
            description=data.get("description"),
            nodes=data.get("nodes"),
            links=data.get("links"),
        )
        _filter_invalid_edges(compiled)
        assert compiled["metadata"]["engine"] == "python_provider"
        assert len(compiled["nodes"]) >= 2
        assert len(compiled.get("edges") or []) >= 1, f"{name} lost all edges"
        for edge in compiled["edges"]:
            assert edge["to_port"] not in {"time_range", "bbox", "region"}
            assert edge["to_port"] in {"manifest", "data", "raster"}
