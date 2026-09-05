"""Block-dir timeseries upsert: stale TIF refresh + time-window filter."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

from app.data_io.services.raster_timeseries import (
    list_block_mats,
    upsert_block_dir_timeseries,
)


def _write_block_mat(path: Path, value: float = 0.4) -> None:
    arr = np.full((8, 8), np.nan, dtype=np.float64)
    arr[2:6, 2:6] = value
    savemat(str(path), {"SM": arr, "VOD": arr, "OMEGA": arr})


def test_list_block_mats_time_window(tmp_path: Path) -> None:
    (_tmp := tmp_path).mkdir(exist_ok=True)
    for name in (
        "20251125_20251202.mat",
        "20251203_20251210.mat",
        "20260101_20260108.mat",
    ):
        (tmp_path / name).write_bytes(b"x")
    labels = [
        t
        for t, _ in list_block_mats(
            tmp_path, time_start="20251201", time_end="20251231"
        )
    ]
    assert labels == ["20251125_20251202", "20251203_20251210"]


def test_list_block_mats_canonical_viirs8_rejects_stale_partial_block(
    tmp_path: Path,
) -> None:
    for name in (
        "20251125_20251202.mat",
        "20251203_20251210.mat",
        "20251211_20251218.mat",
        "20251219_20251220.mat",  # stale partial-window artifact
        "20251219_20251226.mat",
        "20251227_20251231.mat",  # canonical year-end truncated block
    ):
        (tmp_path / name).write_bytes(b"x")
    labels = [
        t
        for t, _ in list_block_mats(
            tmp_path,
            time_start="20251201",
            time_end="20251231",
            canonical_viirs8_only=True,
        )
    ]
    assert labels == [
        "20251125_20251202",
        "20251203_20251210",
        "20251211_20251218",
        "20251219_20251226",
        "20251227_20251231",
    ]


def test_upsert_refreshes_when_mat_newer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imports = tmp_path / "imports"
    imports.mkdir()
    monkeypatch.setattr(
        "app.data_io.services.raster_timeseries.import_paths.IMPORTS_DIR",
        imports,
    )

    block_dir = tmp_path / "blocks"
    block_dir.mkdir()
    mat_path = block_dir / "20251227_20251231.mat"
    _write_block_mat(mat_path, value=0.3)

    # First publish
    first = upsert_block_dir_timeseries(
        block_dir,
        variable_id="SM",
        label="SM",
        run_id="run-test-refresh",
        grid_preset="ease2-global-9km",
        time_start="20251201",
        time_end="20251231",
    )
    layer_id = first["layer_id"]
    tif = imports / layer_id / "source_20251227_20251231.tif"
    assert tif.exists()
    old_mtime = tif.stat().st_mtime

    # Simulate progressive rewrite: mat grows later, stale tif kept
    time.sleep(0.05)
    _write_block_mat(mat_path, value=0.7)
    time.sleep(0.05)

    second = upsert_block_dir_timeseries(
        block_dir,
        variable_id="SM",
        label="SM",
        run_id="run-test-refresh",
        grid_preset="ease2-global-9km",
        time_start="20251201",
        time_end="20251231",
    )
    assert second["layer_id"] == layer_id
    assert tif.stat().st_mtime >= old_mtime
    meta = json.loads((imports / layer_id / "meta.json").read_text(encoding="utf-8"))
    assert meta["time_list"] == ["20251227_20251231"]


def test_omega_reuses_legacy_omega_block_layer_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imports = tmp_path / "imports"
    imports.mkdir()
    monkeypatch.setattr(
        "app.data_io.services.raster_timeseries.import_paths.IMPORTS_DIR",
        imports,
    )
    from app.data_io.services.raster_timeseries import stable_imported_layer_id

    run_id = "run-omega-compat"
    legacy = stable_imported_layer_id(run_id, "OMEGA_BLOCK", "OMEGA")
    (imports / legacy).mkdir()
    (imports / legacy / "meta.json").write_text("{}", encoding="utf-8")

    block_dir = tmp_path / "blocks"
    block_dir.mkdir()
    _write_block_mat(block_dir / "20251227_20251231.mat", value=0.5)

    out = upsert_block_dir_timeseries(
        block_dir,
        variable_id="OMEGA",
        label="OMEGA",
        run_id=run_id,
        grid_preset="ease2-global-9km",
    )
    assert out["layer_id"] == legacy
    assert out["product_tag"] == "OMEGA"


def test_layer_key_dedupes_across_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imports = tmp_path / "imports"
    imports.mkdir()
    monkeypatch.setattr(
        "app.data_io.services.raster_timeseries.import_paths.IMPORTS_DIR",
        imports,
    )

    first_dir = tmp_path / "blocks_a"
    first_dir.mkdir()
    _write_block_mat(first_dir / "20251227_20251231.mat", value=0.3)
    first = upsert_block_dir_timeseries(
        first_dir,
        variable_id="SM",
        label="SM",
        run_id="run-alpha",
        layer_key="method-fy-omega-doy-dynamic",
        grid_preset="ease2-global-9km",
    )

    second_dir = tmp_path / "blocks_b"
    second_dir.mkdir()
    _write_block_mat(second_dir / "20260101_20260108.mat", value=0.5)
    second = upsert_block_dir_timeseries(
        second_dir,
        variable_id="SM",
        label="SM",
        run_id="run-beta",
        layer_key="method-fy-omega-doy-dynamic",
        grid_preset="ease2-global-9km",
    )
    assert second["layer_id"] == first["layer_id"]
    meta = json.loads(
        (imports / first["layer_id"] / "meta.json").read_text(encoding="utf-8")
    )
    # 跨 run 覆盖语义：meta 以最新 run 的窗口为准
    assert meta["time_list"] == ["20260101_20260108"]


def test_layer_key_empty_falls_back_to_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imports = tmp_path / "imports"
    imports.mkdir()
    monkeypatch.setattr(
        "app.data_io.services.raster_timeseries.import_paths.IMPORTS_DIR",
        imports,
    )
    from app.data_io.services.raster_timeseries import stable_imported_layer_id

    block_dir = tmp_path / "blocks"
    block_dir.mkdir()
    _write_block_mat(block_dir / "20251227_20251231.mat", value=0.4)

    out = upsert_block_dir_timeseries(
        block_dir,
        variable_id="SM",
        label="SM",
        run_id="run-legacy",
        grid_preset="ease2-global-9km",
    )
    assert out["layer_id"] == stable_imported_layer_id("run-legacy", "SM", "SM")


def test_upsert_default_time_skips_all_nodata_trailing_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Trailing empty SM day must not become default_time (blank map / N/A)."""
    imports = tmp_path / "imports"
    imports.mkdir()
    monkeypatch.setattr(
        "app.data_io.services.raster_timeseries.import_paths.IMPORTS_DIR",
        imports,
    )

    block_dir = tmp_path / "blocks"
    block_dir.mkdir()
    _write_block_mat(block_dir / "20251230.mat", value=0.25)
    empty = np.full((8, 8), np.nan, dtype=np.float64)
    savemat(
        str(block_dir / "20251231.mat"),
        {"SM": empty, "VOD": empty, "OMEGA": empty},
    )

    out = upsert_block_dir_timeseries(
        block_dir,
        variable_id="SM",
        label="SM",
        run_id="run-default-time",
        grid_preset="ease2-global-9km",
        native_step="1d",
    )
    assert out["default_time"] == "20251230_20251230"
    meta = json.loads(
        (imports / out["layer_id"] / "meta.json").read_text(encoding="utf-8")
    )
    assert meta["default_time"] == "20251230_20251230"
    assert meta.get("palette")
    bounds = json.loads(
        (imports / out["layer_id"] / "bounds.json").read_text(encoding="utf-8")
    )
    assert bounds["meta"]["default_time"] == "20251230_20251230"


def test_upsert_ndvi_daily_dir_timeseries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ndvi_daily_dir maps 32 daily mats into unified time-series layer."""
    from app.services.overlay_registry import get_overlay_spec
    from app.services.python_provider_result_builder import _MAPPABLE_PRODUCTS

    assert "ndvi_daily_dir" in _MAPPABLE_PRODUCTS
    assert _MAPPABLE_PRODUCTS["ndvi_daily_dir"]["from_block_dir"] is True
    assert _MAPPABLE_PRODUCTS["ndvi_daily_dir"]["palette"] == "ndvi-ramp"

    imports = tmp_path / "imports"
    imports.mkdir()
    monkeypatch.setattr(
        "app.data_io.services.raster_timeseries.import_paths.IMPORTS_DIR",
        imports,
    )

    block_dir = tmp_path / "ndvi_daily"
    block_dir.mkdir()
    for day in ("20260701", "20260702", "20260703"):
        arr = np.full((8, 8), 0.5, dtype=np.float32)
        savemat(str(block_dir / f"{day}.mat"), {"NDVI": arr})

    out = upsert_block_dir_timeseries(
        block_dir,
        variable_id="NDVI",
        label="NDVI",
        run_id="run-ndvi-test",
        layer_key="ndvi",
        grid_preset="ease2-global-9km",
        palette="ndvi-ramp",
        vmin=0.0,
        vmax=1.0,
        native_step="1d",
    )
    assert out["time_list"] == [
        "20260701_20260701",
        "20260702_20260702",
        "20260703_20260703",
    ]
    spec = get_overlay_spec(out["layer_id"])
    assert spec is not None
    # 验证单日 8 位时间对 YYYYMMDD_YYYYMMDD 的自动匹配容错
    assert spec._assert_time_available("20260702") == "20260702_20260702"
    assert spec._assert_time_available("2026-07-02") == "20260702_20260702"
