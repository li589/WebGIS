"""栅格单时刻 / 多时刻 zip 导出。"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from app.data_io.services import export_layer as export_mod
from app.data_io.services import paths as import_paths
from app.data_io.services.export_layer import export_layer


@pytest.fixture()
def imports_tmp(tmp_path, monkeypatch):
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    monkeypatch.setattr(import_paths, "IMPORTS_DIR", imports_dir)
    monkeypatch.setattr(export_mod, "IMPORTS_DIR", imports_dir)
    return imports_dir


def _write_tiny_tif(path: Path, tag: bytes) -> None:
    # Minimal valid-enough GeoTIFF not required — export just reads bytes.
    path.write_bytes(b"II*\x00" + tag + b"\x00" * 32)


def test_export_raster_single_time(imports_tmp: Path):
    layer_id = "imported-ts-1"
    dest = imports_tmp / layer_id
    dest.mkdir()
    _write_tiny_tif(dest / "source_20251203_20251210.tif", b"A")
    _write_tiny_tif(dest / "source_20251227_20251231.tif", b"B")
    (dest / "bounds.json").write_text("{}", encoding="utf-8")
    (dest / "meta.json").write_text(
        json.dumps(
            {
                "kind": "raster",
                "label": "SM",
                "time_list": ["20251203_20251210", "20251227_20251231"],
                "default_time": "20251227_20251231",
            }
        ),
        encoding="utf-8",
    )

    content, media, filename = export_layer(
        layer_id, "tif", time="20251203_20251210"
    )
    assert media == "image/tiff"
    assert "20251203_20251210" in filename
    assert b"A" in content


def test_export_raster_multi_times_zip(imports_tmp: Path):
    layer_id = "imported-ts-2"
    dest = imports_tmp / layer_id
    dest.mkdir()
    _write_tiny_tif(dest / "source_20251203_20251210.tif", b"A1")
    _write_tiny_tif(dest / "source_20251211_20251218.tif", b"A2")
    _write_tiny_tif(dest / "source_20251227_20251231.tif", b"A3")
    (dest / "bounds.json").write_text("{}", encoding="utf-8")
    (dest / "meta.json").write_text(
        json.dumps(
            {
                "kind": "raster",
                "label": "VOD",
                "time_list": [
                    "20251203_20251210",
                    "20251211_20251218",
                    "20251227_20251231",
                ],
            }
        ),
        encoding="utf-8",
    )

    content, media, filename = export_layer(
        layer_id,
        "tif",
        times=["20251203_20251210", "20251227_20251231"],
    )
    assert media == "application/zip"
    assert filename.endswith(".zip")
    with zipfile.ZipFile(BytesIO(content)) as zf:
        names = zf.namelist()
        assert len(names) == 2
        assert any("20251203_20251210" in n for n in names)
        assert any("20251227_20251231" in n for n in names)


def test_export_raster_all_times_star(imports_tmp: Path):
    layer_id = "imported-ts-3"
    dest = imports_tmp / layer_id
    dest.mkdir()
    for t in ("20251203_20251210", "20251211_20251218"):
        _write_tiny_tif(dest / f"source_{t}.tif", t.encode())
    (dest / "bounds.json").write_text("{}", encoding="utf-8")
    (dest / "meta.json").write_text(
        json.dumps(
            {
                "kind": "raster",
                "label": "OMEGA",
                "time_list": ["20251203_20251210", "20251211_20251218"],
            }
        ),
        encoding="utf-8",
    )
    content, media, filename = export_layer(layer_id, "tif", time="*")
    assert media == "application/zip"
    with zipfile.ZipFile(BytesIO(content)) as zf:
        assert len(zf.namelist()) == 2
        assert filename.endswith(".zip")
