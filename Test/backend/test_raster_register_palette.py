"""R1（2026-08-23 机制核查）：imported 栅格注册侧 palette 透传回归。

背景：register_geotiff_as_imported 曾把 preview.png / bounds.json meta /
OverlaySpec 三处 palette 全部写死 "wind-blue"，而 materialize 的 render_hint
按产品配置给出 cividis/ylgnbu/viridis —— 前端经 /overlay-bounds 取
meta.palette 后动态着色，导致算法产物色带断裂（wind-blue 一统天下）。

修复：注册链路加 palette 参数（默认 wind-blue 保持用户导入行为不变），
confirm_imported_raster_crs 重渲染沿用注册 palette，builder 两条物化路径
（generic GeoTIFF / .mat 单文件）按 render_hint 对齐传参。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.data_io.services import paths as import_paths
from app.data_io.services import raster_commit as commit_mod
from app.data_io.services import raster_register as register_mod
from app.data_io.services.raster_commit import commit_algorithm_geotiff
from app.data_io.services.raster_register import (
    confirm_imported_raster_crs,
    register_geotiff_as_imported,
)
from app.services.overlay_registry import get_overlay_spec, unregister_overlay


@pytest.fixture()
def imports_tmp(tmp_path, monkeypatch):
    imports_dir = tmp_path / "imports"
    for mod in (import_paths, register_mod, commit_mod):
        if hasattr(mod, "IMPORTS_DIR"):
            monkeypatch.setattr(mod, "IMPORTS_DIR", imports_dir)
        if hasattr(mod, "STAGING_DIR"):
            monkeypatch.setattr(mod, "STAGING_DIR", imports_dir / "_staging")
    monkeypatch.setattr(import_paths, "IMPORTS_DIR", imports_dir)
    monkeypatch.setattr(import_paths, "STAGING_DIR", imports_dir / "_staging")
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


def _meta_palette(imports_dir: Path, layer_id: str) -> str | None:
    bounds = json.loads(
        (imports_dir / layer_id / "bounds.json").read_text(encoding="utf-8")
    )
    return bounds.get("meta", {}).get("palette")


def test_register_with_palette_threads_into_meta_and_spec(imports_tmp, tmp_path):
    tif = tmp_path / "a.tif"
    _write_tiny_tif(tif, 1.0)
    layer_id = "imported-palette-demo01"
    try:
        register_geotiff_as_imported(
            tif,
            source_filename="a.tif",
            layer_id=layer_id,
            palette="cividis",
        )
        assert _meta_palette(imports_tmp, layer_id) == "cividis"
        spec = get_overlay_spec(layer_id)
        assert spec is not None and spec.palette == "cividis"
    finally:
        unregister_overlay(layer_id)


def test_register_default_palette_remains_wind_blue(imports_tmp, tmp_path):
    """向后兼容：不传 palette 的用户导入仍落 wind-blue（行为不变）。"""
    tif = tmp_path / "b.tif"
    _write_tiny_tif(tif, 2.0)
    layer_id = "imported-palette-demo02"
    try:
        register_geotiff_as_imported(tif, source_filename="b.tif", layer_id=layer_id)
        assert _meta_palette(imports_tmp, layer_id) == "wind-blue"
        spec = get_overlay_spec(layer_id)
        assert spec is not None and spec.palette == "wind-blue"
    finally:
        unregister_overlay(layer_id)


def test_confirm_crs_preserves_registered_palette(imports_tmp, tmp_path):
    """confirm 重渲染/重注册不得把 palette 重置回 wind-blue。"""
    tif = tmp_path / "c.tif"
    _write_tiny_tif(tif, 3.0)
    layer_id = "imported-palette-demo03"
    try:
        register_geotiff_as_imported(
            tif,
            source_filename="c.tif",
            layer_id=layer_id,
            palette="ylgnbu",
        )
        confirm_imported_raster_crs(layer_id, source_crs="EPSG:4326")
        assert _meta_palette(imports_tmp, layer_id) == "ylgnbu"
        spec = get_overlay_spec(layer_id)
        assert spec is not None and spec.palette == "ylgnbu"
    finally:
        unregister_overlay(layer_id)


def test_commit_algorithm_geotiff_threads_palette(imports_tmp, tmp_path):
    """builder generic 物化路径：commit_algorithm_geotiff 透传 palette。"""
    tif = tmp_path / "algo.tif"
    _write_tiny_tif(tif, 4.0)
    layer_id = "imported-gis-palette01-00"
    try:
        commit_algorithm_geotiff(
            tif,
            layer_id=layer_id,
            source_name="algo.tif",
            auto_confirm=False,
            palette="viridis",
        )
        assert _meta_palette(imports_tmp, layer_id) == "viridis"
        spec = get_overlay_spec(layer_id)
        assert spec is not None and spec.palette == "viridis"
    finally:
        unregister_overlay(layer_id)
