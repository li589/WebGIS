"""Unit tests for NDVI ingest (.mat/.tif) and systematic display label resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.python_provider_result_builder import _resolve_product_display_label
from ingest.ndvi import discover_ndvi_rasters


def test_discover_ndvi_rasters_mat_and_tif(tmp_path: Path) -> None:
    # Create mock .mat and .tif files
    (tmp_path / "20200101.mat").touch()
    (tmp_path / "20200102.tif").touch()
    (tmp_path / "20200201.mat").touch()

    # Query matching 2020-01-01 to 2020-01-15
    matches = discover_ndvi_rasters(tmp_path, "2020-01-01", "2020-01-15")
    assert len(matches) == 2
    names = [p.file_path.name for p in matches]
    assert "20200101.mat" in names
    assert "20200102.tif" in names


def test_discover_ndvi_rasters_empty_range_reports_existing_bounds(tmp_path: Path) -> None:
    (tmp_path / "20150101.mat").touch()
    (tmp_path / "20231231.mat").touch()

    with pytest.raises((FileNotFoundError, RuntimeError)) as ctx:
        discover_ndvi_rasters(tmp_path, "2026-09-01", "2026-10-01")

    err = str(ctx.value)
    assert "No NDVI rasters found" in err
    assert "2015-01-01" in err
    assert "2023-12-31" in err


def test_resolve_product_display_label_for_ndvi_layer() -> None:
    label = _resolve_product_display_label(
        raw_layer_id="ndvi",
        tags={"layer": "NDVI"},
        product={"variable": "NDVI"},
        local_path=Path("20200101.mat"),
    )
    assert label == "植被指数 NDVI"
    assert "产出变量" not in label


def test_resolve_product_display_label_for_ndvi_seed_workflows() -> None:
    for wf_id in ("ndvi_local_read", "ndvi_online_read"):
        label = _resolve_product_display_label(
            raw_layer_id="",
            tags={},
            product={"variable": "NDVI"},
            local_path=Path("20200101.mat"),
            workflow_id=wf_id,
        )
        assert label == "植被指数 NDVI"
        assert "产出变量" not in label


def test_ndvi_seeds_contain_output_labels() -> None:
    seeds_dir = Path("Code/backend/workflow_seeds/system")
    for name in ("ndvi_local_read.json", "ndvi_online_read.json"):
        path = seeds_dir / name
        data = json.loads(path.read_text(encoding="utf-8"))
        extra = data.get("extra", {})
        assert "group_title" in extra
        assert "NDVI" in extra["group_title"]
        assert "output_labels" in extra
        assert extra["output_labels"].get("NDVI") == "植被指数 NDVI"
        assert extra["output_labels"].get("result") == "植被指数 NDVI"
