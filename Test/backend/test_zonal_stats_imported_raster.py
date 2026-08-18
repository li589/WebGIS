"""zonal_stats_service 导入栅格（imported-*）路径解析与统计回归。

背景：导入栅格落盘在 OUTPUT_ROOT/imports/<layer_id>/，不在 data_root 下；
同步分区统计此前只查 data_root，导致前端「自动统计」对导入栅格恒为空结果。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

import app.data_io.services.paths as paths_mod
from app.services.zonal_stats_service import (
    _find_imported_raster_path,
    _find_raster_path,
    compute_zonal_stats,
)


@pytest.fixture()
def imported_raster_dir(tmp_path: Path) -> Path:
    """构造 IMPORTS_DIR/imported-test/<tif + bounds.json> 目录布局。"""
    import rasterio
    from rasterio.crs import CRS
    from rasterio.transform import from_bounds

    layer_dir = tmp_path / "imported-test"
    layer_dir.mkdir()
    w, s, e, n = 95.0, 20.0, 115.0, 40.0
    wpx = hpx = 10
    data = (1 + np.tile(np.arange(wpx), (hpx, 1)) + 10 * np.arange(hpx)[:, None]).astype(
        "float32"
    )
    with rasterio.open(
        layer_dir / "source_demo.tif",
        "w",
        driver="GTiff",
        height=hpx,
        width=wpx,
        count=1,
        dtype="float32",
        crs=CRS.from_epsg(4326),
        transform=from_bounds(w, s, e, n, wpx, hpx),
    ) as ds:
        ds.write(data, 1)

    (layer_dir / "bounds.json").write_text(
        json.dumps(
            {
                "bounds": [w, s, e, n],
                "meta": {"layer_id": "imported-test", "source_filename": "source_demo.tif"},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_find_imported_raster_path_prefers_bounds_meta(
    imported_raster_dir: Path,
) -> None:
    original = paths_mod.IMPORTS_DIR
    paths_mod.IMPORTS_DIR = imported_raster_dir
    try:
        found = _find_imported_raster_path("imported-test")
        assert found is not None
        assert found.name == "source_demo.tif"
    finally:
        paths_mod.IMPORTS_DIR = original


def test_find_imported_raster_path_ignores_non_imported_ids(
    imported_raster_dir: Path,
) -> None:
    original = paths_mod.IMPORTS_DIR
    paths_mod.IMPORTS_DIR = imported_raster_dir
    try:
        assert _find_imported_raster_path("aridity-cn") is None
    finally:
        paths_mod.IMPORTS_DIR = original


def test_compute_zonal_stats_for_imported_raster(
    monkeypatch: pytest.MonkeyPatch, imported_raster_dir: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(paths_mod, "IMPORTS_DIR", imported_raster_dir)

    # 多边形 100.1–109.9E / 25.1–34.9N（避开像元边界，中心落入 4×4=16 像元）
    ring = [
        [100.1, 25.1],
        [109.9, 25.1],
        [109.9, 34.9],
        [100.1, 34.9],
        [100.1, 25.1],
    ]
    results = compute_zonal_stats(
        geojson={"type": "Polygon", "coordinates": [ring]},
        overlay_layer_ids=["imported-test"],
        data_root=tmp_path / "empty-data-root",
        layer_descriptors={},
    )

    assert len(results) == 1
    row = results[0]
    assert row["count"] == 16
    assert row["min"] == pytest.approx(34.0)
    assert row["max"] == pytest.approx(67.0)
    assert row["mean"] == pytest.approx(50.5)
    assert row["std"] == pytest.approx(math.sqrt(126.25))


def test_find_raster_path_falls_back_to_imported_dir(
    monkeypatch: pytest.MonkeyPatch, imported_raster_dir: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(paths_mod, "IMPORTS_DIR", imported_raster_dir)
    found = _find_raster_path(
        "imported-test", data_root=tmp_path / "empty-data-root", desc={}
    )
    assert found is not None
    assert found.name == "source_demo.tif"
