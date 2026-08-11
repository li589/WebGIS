"""导出 ArcGIS 轻量选项：bbox / fields / output_crs；batch 透传 time。"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.data_io.services import export_layer as export_mod
from app.data_io.services import paths as import_paths
from app.data_io.services import vector as vector_mod
from app.data_io.services.export_layer import export_layer, export_layers_batch_zip
from app.data_io.services.vector import _write_layer


@pytest.fixture()
def imports_tmp(tmp_path, monkeypatch):
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    for mod in (import_paths, vector_mod, export_mod):
        monkeypatch.setattr(mod, "IMPORTS_DIR", imports_dir)
    return imports_dir


def _write_geo_tif(path: Path, *, value: float = 1.0) -> None:
    data = np.full((8, 8), value, dtype=np.float32)
    transform = from_origin(100.0, 40.0, 0.5, 0.5)  # west=100, north=40
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=8,
        width=8,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as ds:
        ds.write(data, 1)


def test_export_vector_fields_and_bbox(imports_tmp: Path):
    layer_id = "imported-vec-opts"
    dest = imports_tmp / layer_id
    dest.mkdir(parents=True, exist_ok=True)
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.4, 39.9]},
                "properties": {"name": "in", "code": "A", "extra": 1},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [10.0, 10.0]},
                "properties": {"name": "out", "code": "B", "extra": 2},
            },
        ],
    }
    _write_layer(
        layer_id=layer_id,
        dest=dest,
        geojson=geojson,
        source_name="demo.geojson",
    )
    content, media, _filename = export_layer(
        layer_id,
        "geojson",
        fields=["name", "code"],
        bbox={"west": 100, "south": 30, "east": 130, "north": 50, "crs": "EPSG:4326"},
    )
    assert media == "application/geo+json"
    fc = json.loads(content.decode("utf-8"))
    assert len(fc["features"]) == 1
    props = fc["features"][0]["properties"]
    assert props == {"name": "in", "code": "A"}
    assert "extra" not in props


def test_export_raster_clip_bbox(imports_tmp: Path):
    layer_id = "imported-ras-clip"
    dest = imports_tmp / layer_id
    dest.mkdir()
    _write_geo_tif(dest / "source.tif", value=3.0)
    (dest / "bounds.json").write_text("{}", encoding="utf-8")
    (dest / "meta.json").write_text(
        json.dumps({"kind": "raster", "label": "SM"}), encoding="utf-8"
    )
    # clip to west half roughly
    content, media, filename = export_layer(
        layer_id,
        "tif",
        bbox={"west": 100.0, "south": 36.0, "east": 102.0, "north": 40.0, "crs": "EPSG:4326"},
    )
    assert media == "image/tiff"
    assert filename.endswith(".tif")
    with rasterio.open(BytesIO(content)) as ds:
        assert ds.width < 8 or ds.height < 8
        assert ds.crs.to_string() in {"EPSG:4326", "OGC:CRS84"} or "4326" in str(ds.crs)


def test_export_batch_passes_time(imports_tmp: Path):
    layer_id = "imported-batch-t"
    dest = imports_tmp / layer_id
    dest.mkdir()
    _write_geo_tif(dest / "source_20251203_20251210.tif", value=1.0)
    _write_geo_tif(dest / "source_20251227_20251231.tif", value=2.0)
    (dest / "bounds.json").write_text("{}", encoding="utf-8")
    (dest / "meta.json").write_text(
        json.dumps(
            {
                "kind": "raster",
                "time_list": ["20251203_20251210", "20251227_20251231"],
            }
        ),
        encoding="utf-8",
    )
    result = export_layers_batch_zip(
        [layer_id],
        format="tif",
        time="20251203_20251210",
    )
    zip_path = Path(str(result["download_path"]))
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert any("20251203_20251210" in n for n in names)
        assert not any("20251227_20251231" in n for n in names if not n.endswith(".error.txt"))
