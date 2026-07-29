"""导出编码：CSV/SHP + .cpg，以及属性编辑后编码 meta 保留。"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from app.data_io.services import export_layer as export_mod
from app.data_io.services import paths as import_paths
from app.data_io.services import vector as vector_mod
from app.data_io.services.dbf_encoding import (
    cpg_label_for_encoding,
    resolve_export_encoding,
)
from app.data_io.services.export_layer import export_layer
from app.data_io.services.vector import (
    _write_layer,
    patch_feature_attribute,
)


@pytest.fixture()
def imports_tmp(tmp_path, monkeypatch):
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    for mod in (import_paths, vector_mod, export_mod):
        monkeypatch.setattr(mod, "IMPORTS_DIR", imports_dir)
    return imports_dir


def test_resolve_export_encoding_auto_from_meta():
    assert (
        resolve_export_encoding("auto", meta={"source_encoding": "gbk"}, fmt="shp")
        == "gbk"
    )
    assert (
        resolve_export_encoding("auto", meta={"source_encoding": "utf-8"}, fmt="csv")
        == "utf-8-sig"
    )
    assert resolve_export_encoding("gb18030", meta={}, fmt="csv") == "gb18030"


def test_cpg_labels():
    assert cpg_label_for_encoding("gbk") == "GBK"
    assert cpg_label_for_encoding("utf-8") == "UTF-8"


def test_export_shp_zip_writes_cpg_gbk(imports_tmp, tmp_path: Path):
    shapefile = pytest.importorskip("shapefile")
    layer_id = "vec-enc-1"
    dest = imports_tmp / layer_id
    dest.mkdir(parents=True, exist_ok=True)
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.4, 39.9]},
                "properties": {"基地带": "测区A", "NAME": "n1"},
            }
        ],
    }
    _write_layer(
        layer_id=layer_id,
        dest=dest,
        geojson=geojson,
        source_name="demo.shp",
        extra_meta={"source_encoding": "gbk", "encoding_strict": True},
    )
    content, media, filename = export_layer(layer_id, "shp-zip", encoding="gbk")
    assert media == "application/zip"
    assert filename.endswith(".zip")
    with zipfile.ZipFile(BytesIO(content)) as zf:
        names = zf.namelist()
        assert any(n.endswith(".cpg") for n in names)
        assert any(n.endswith(".dbf") for n in names)
        cpg_name = next(n for n in names if n.endswith(".cpg"))
        assert zf.read(cpg_name).decode("ascii").strip() == "GBK"

    # 再用 GBK 读回字段名
    extract = tmp_path / "out"
    extract.mkdir()
    with zipfile.ZipFile(BytesIO(content)) as zf:
        zf.extractall(extract)
    shp = next(extract.rglob("*.shp"))
    with shapefile.Reader(str(shp), encoding="gbk") as reader:
        fields = [f[0] for f in reader.fields[1:]]
    assert any("基地" in f or f == "基地带" for f in fields) or "NAME" in fields


def test_export_csv_gbk(imports_tmp):
    layer_id = "vec-enc-csv"
    dest = imports_tmp / layer_id
    dest.mkdir(parents=True, exist_ok=True)
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                "properties": {"名称": "甲"},
            }
        ],
    }
    _write_layer(
        layer_id=layer_id,
        dest=dest,
        geojson=geojson,
        source_name="t.csv",
        extra_meta={"source_encoding": "gbk"},
    )
    content, media, _ = export_layer(layer_id, "csv", encoding="gbk")
    assert "csv" in media
    text = content.decode("gbk")
    assert "名称" in text
    assert "甲" in text


def test_patch_preserves_encoding_meta(imports_tmp):
    layer_id = "vec-enc-patch"
    dest = imports_tmp / layer_id
    dest.mkdir(parents=True, exist_ok=True)
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {"A": "1"},
            }
        ],
    }
    _write_layer(
        layer_id=layer_id,
        dest=dest,
        geojson=geojson,
        source_name="x.shp",
        extra_meta={
            "source_encoding": "gb18030",
            "encoding_sources": ["cpg"],
            "encoding_strict": True,
        },
    )
    patch_feature_attribute(layer_id, 0, "A", "2")
    meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
    assert meta["source_encoding"] == "gb18030"
    assert meta["encoding_sources"] == ["cpg"]
