"""栅格 MAT 导出：多波段变量 + lat/lon 坐标变换。"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from scipy.io import loadmat

from app.data_io.services import export_layer as export_mod
from app.data_io.services import paths as import_paths
from app.data_io.services.export_layer import export_layer, export_layers_batch_zip


@pytest.fixture()
def imports_tmp(tmp_path, monkeypatch):
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    monkeypatch.setattr(import_paths, "IMPORTS_DIR", imports_dir)
    monkeypatch.setattr(export_mod, "IMPORTS_DIR", imports_dir)
    return imports_dir


def _write_multi_band_tif(path: Path) -> None:
    data = np.stack(
        [
            np.full((6, 8), 1.5, dtype=np.float32),
            np.full((6, 8), 2.5, dtype=np.float32),
        ],
        axis=0,
    )
    # west=100, north=40, pixel 0.5°
    transform = from_origin(100.0, 40.0, 0.5, 0.5)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=6,
        width=8,
        count=2,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as ds:
        ds.write(data)


def test_export_mat_multiband_with_lat_lon(imports_tmp: Path):
    layer_id = "imported-mat-1"
    dest = imports_tmp / layer_id
    dest.mkdir()
    _write_multi_band_tif(dest / "source.tif")
    (dest / "bounds.json").write_text("{}", encoding="utf-8")
    (dest / "meta.json").write_text(
        json.dumps(
            {
                "kind": "raster",
                "variable_ids": ["SM", "VOD"],
                "label": "bundle",
            }
        ),
        encoding="utf-8",
    )

    content, media, filename = export_layer(layer_id, "mat")
    assert media == "application/x-matlab-data"
    assert filename.endswith(".mat")
    assert filename.startswith(layer_id)

    mat = loadmat(BytesIO(content), squeeze_me=True)
    assert "SM" in mat
    assert "VOD" in mat
    assert mat["SM"].shape == (6, 8)
    assert float(np.nanmean(mat["SM"])) == pytest.approx(1.5)
    assert float(np.nanmean(mat["VOD"])) == pytest.approx(2.5)
    # 像素中心：首格 (100.25, 39.75)
    assert mat["lon"].shape == (6, 8)
    assert mat["lat"].shape == (6, 8)
    assert float(mat["lon"][0, 0]) == pytest.approx(100.25, abs=1e-6)
    assert float(mat["lat"][0, 0]) == pytest.approx(39.75, abs=1e-6)
    crs = mat.get("crs")
    crs_s = crs.item() if hasattr(crs, "item") else str(crs)
    assert "4326" in crs_s


def test_export_mat_reproject_to_3857_keeps_wgs84_latlon(imports_tmp: Path):
    layer_id = "imported-mat-3857"
    dest = imports_tmp / layer_id
    dest.mkdir()
    _write_multi_band_tif(dest / "source.tif")
    (dest / "bounds.json").write_text("{}", encoding="utf-8")
    (dest / "meta.json").write_text(
        json.dumps({"kind": "raster", "variable_id": "SM"}),
        encoding="utf-8",
    )
    content, _media, _fn = export_layer(layer_id, "mat", output_crs="EPSG:3857")
    mat = loadmat(BytesIO(content), squeeze_me=True)
    assert "SM" in mat or "band_1" in mat
    assert "lat" in mat and "lon" in mat
    assert "x" in mat and "y" in mat
    # lon/lat 仍应在中国附近（WGS84）
    assert 90 < float(np.nanmean(mat["lon"])) < 120
    assert 30 < float(np.nanmean(mat["lat"])) < 50


def test_export_batch_mat_merges_same_grid(imports_tmp: Path):
    ids = []
    for name, value in (("imported-a", 1.0), ("imported-b", 9.0)):
        dest = imports_tmp / name
        dest.mkdir()
        data = np.full((4, 4), value, dtype=np.float32)
        transform = from_origin(110.0, 35.0, 0.25, 0.25)
        with rasterio.open(
            dest / "source.tif",
            "w",
            driver="GTiff",
            height=4,
            width=4,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=transform,
        ) as ds:
            ds.write(data, 1)
        (dest / "bounds.json").write_text("{}", encoding="utf-8")
        (dest / "meta.json").write_text(
            json.dumps({"kind": "raster", "variable_id": name[-1].upper()}),
            encoding="utf-8",
        )
        ids.append(name)

    result = export_layers_batch_zip(ids, format="mat")
    path = Path(str(result["download_path"]))
    assert path.suffix == ".mat"
    mat = loadmat(str(path), squeeze_me=True)
    # 变量名带 layer 前缀
    keys = [k for k in mat.keys() if not k.startswith("__")]
    assert any("A" in k or "a" in k.lower() for k in keys)
    assert "lat" in mat and "lon" in mat
