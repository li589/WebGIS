"""导入配额回收 + 同名覆盖再导入。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.data_io.services import paths as import_paths
from app.data_io.services import raster_commit as commit_mod
from app.data_io.services import raster_register as register_mod
from app.data_io.services.paths import (
    QuotaExceededError,
    assert_quota_available,
    get_quota_usage,
    reclaim_import_space,
    stable_import_layer_id,
)
from app.data_io.services.raster_register import register_geotiff_as_imported


@pytest.fixture()
def imports_tmp(tmp_path, monkeypatch):
    root = tmp_path / "imports_output"
    imports_dir = root / "imports"
    for mod in (import_paths, register_mod, commit_mod):
        if hasattr(mod, "IMPORTS_DIR"):
            monkeypatch.setattr(mod, "IMPORTS_DIR", imports_dir)
        if hasattr(mod, "STAGING_DIR"):
            monkeypatch.setattr(mod, "STAGING_DIR", imports_dir / "_staging")
    # raster_register imports IMPORTS_DIR from paths at import time — patch paths too
    monkeypatch.setattr(import_paths, "IMPORTS_DIR", imports_dir)
    monkeypatch.setattr(import_paths, "STAGING_DIR", imports_dir / "_staging")
    monkeypatch.setattr(import_paths, "JOBS_DIR", imports_dir / "_jobs")
    monkeypatch.setattr(import_paths, "DOC_SESSIONS_DIR", imports_dir / "_documents")
    monkeypatch.setattr(import_paths, "MAX_IMPORTS_TOTAL_BYTES", 5 * 1024 * 1024)
    monkeypatch.setattr(import_paths, "SOFT_RESERVE_BYTES", 256 * 1024)
    import_paths.ensure_imports_root()
    return imports_dir


def _write_tiny_tif(path: Path, value: float = 1.0) -> None:
    import rasterio
    from rasterio.transform import from_bounds

    transform = from_bounds(116.0, 39.0, 117.0, 40.0, 1, 1)
    data = np.array([[value]], dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=1,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data, 1)


def test_stable_id_deterministic():
    a = stable_import_layer_id("a.mat", "OMEGA", "ease2", "0")
    b = stable_import_layer_id("a.mat", "OMEGA", "ease2", "0")
    c = stable_import_layer_id("a.mat", "SM", "ease2", "0")
    assert a == b
    assert a != c
    assert a.startswith("imported-")


def test_quota_excludes_ephemeral(imports_tmp):
    staging = imports_tmp / "_staging" / "up-x"
    staging.mkdir(parents=True)
    (staging / "blob.bin").write_bytes(b"z" * (2 * 1024 * 1024))
    usage = get_quota_usage()
    # ephemeral staging 不计入 used
    assert usage["used_bytes"] < 1024
    assert usage["ephemeral_bytes"] >= 2 * 1024 * 1024


def test_reclaim_tmp_and_quota_message(imports_tmp, tmp_path):
    tmp = imports_tmp / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    junk = tmp / "old.bin"
    junk.write_bytes(b"x" * 1000)
    # needed=0 + aggressive：走完全部回收阶段（含 tmp/exports）
    result = reclaim_import_space(needed_bytes=0, aggressive=True)
    assert result["freed_bytes"] >= 1000
    assert not result.get("stopped_early")
    phase_names = [p["phase"] for p in result["phases"]]
    assert phase_names == [
        "expired_staging",
        "completed_staging",
        "pressure_staging",
        "tmp",
        "exports",
    ]
    assert not junk.exists()
    usage = get_quota_usage()
    assert "used_bytes" in usage
    assert usage["limit_bytes"] == 5 * 1024 * 1024
    assert usage["soft_reserve_bytes"] <= 256 * 1024

    # fill over limit with a large permanent import
    big = imports_tmp / "imported-filler"
    big.mkdir()
    (big / "blob.bin").write_bytes(b"y" * (6 * 1024 * 1024))
    with pytest.raises(QuotaExceededError, match="配额已满"):
        assert_quota_available(1024)


def test_update_display_name(imports_tmp):
    layer_id = "imported-rename-demo"
    dest = imports_tmp / layer_id
    dest.mkdir()
    (dest / "meta.json").write_text(
        '{"layer_id":"imported-rename-demo","kind":"raster","source_filename":"a.tif"}',
        encoding="utf-8",
    )
    (dest / "bounds.json").write_text(
        '{"bounds":[0,0,1,1],"meta":{"source_filename":"a.tif"}}',
        encoding="utf-8",
    )
    out = import_paths.update_imported_layer_display_name(layer_id, "新名字")
    assert out["display_name"] == "新名字"
    meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
    assert meta["display_name"] == "新名字"
    assert meta["label"] == "新名字"


def test_register_overwrite_same_layer_id(imports_tmp, tmp_path):
    tif1 = tmp_path / "a.tif"
    tif2 = tmp_path / "b.tif"
    _write_tiny_tif(tif1, 1.0)
    _write_tiny_tif(tif2, 2.0)
    layer_id = stable_import_layer_id("demo.mat", "OMEGA", "ease2", "0")

    first = register_geotiff_as_imported(
        tif1, source_filename="demo_OMEGA.tif", layer_id=layer_id, replace_existing=False
    )
    assert first["layer_id"] == layer_id
    assert first.get("replaced") is False

    second = register_geotiff_as_imported(
        tif2, source_filename="demo_OMEGA.tif", layer_id=layer_id, replace_existing=True
    )
    assert second["layer_id"] == layer_id
    assert second.get("replaced") is True
    # still a single directory
    assert (imports_tmp / layer_id).is_dir()
