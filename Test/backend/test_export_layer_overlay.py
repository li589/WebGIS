"""注册表 overlay 图层导出（prod-/ref-/method- 等非 IMPORTS_DIR 图层）。

覆盖 `_export_registry_overlay` 分支：tif 直读 / png 预览 / 格式拒绝 /
未知图层 FileNotFoundError / 时序 source_pattern 解析与多时刻 zip。
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from app.data_io.services import export_layer as export_mod
from app.data_io.services import paths as import_paths
from app.data_io.services.export_layer import export_layer
from app.services import overlay_registry


@pytest.fixture()
def imports_tmp(tmp_path, monkeypatch):
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    monkeypatch.setattr(import_paths, "IMPORTS_DIR", imports_dir)
    monkeypatch.setattr(export_mod, "IMPORTS_DIR", imports_dir)
    return imports_dir


def _write_real_tif(path: Path, value: float = 0.5) -> None:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    arr = np.full((4, 6), value, dtype="float32")
    profile = {
        "driver": "GTiff",
        "width": 6,
        "height": 4,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_origin(-180.0, 90.0, 60.0, 45.0),
        "nodata": -9999.0,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr, 1)


def _make_spec(overlay_dir: Path, *, time_series: bool = False) -> "overlay_registry.OverlaySpec":
    if time_series:
        return overlay_registry.OverlaySpec(
            layer_id="method-x-omega-doy-dynamic",
            overlay_dir=overlay_dir,
            category="time-series",
            time_pattern="preview_{time}.png",
            bounds_pattern="bounds_{time}.json",
            time_list=["20251227_20251231", "20251203_20251210"],
            default_time="20251227_20251231",
            unit="Ω",
            source_pattern=str(overlay_dir / "source_{time}.tif"),
        )
    return overlay_registry.OverlaySpec(
        layer_id="method-x-omega-static",
        overlay_dir=overlay_dir,
        category="static",
        png_filename="preview.png",
        bounds_filename="bounds.json",
        unit="SM",
        source_path=overlay_dir / "source.tif",
    )


def _patch_spec(monkeypatch, spec):
    monkeypatch.setattr(overlay_registry, "get_overlay_spec", lambda _lid: spec)


def test_export_overlay_static_tif(imports_tmp: Path, monkeypatch):
    overlay_dir = imports_tmp.parent / "ovl-static"
    _write_real_tif(overlay_dir / "source.tif", value=0.42)
    (overlay_dir / "preview.png").write_bytes(b"\x89PNG-fake")
    spec = _make_spec(overlay_dir)
    _patch_spec(monkeypatch, spec)

    content, media, filename = export_layer(spec.layer_id, "tif")
    assert media == "image/tiff"
    assert filename.startswith(spec.layer_id)
    assert filename.endswith(".tif")

    import rasterio

    with rasterio.open(BytesIO(content)) as ds:
        assert ds.width == 6 and ds.height == 4
        assert ds.crs is not None and ds.crs.to_epsg() == 4326


def test_export_overlay_static_png(imports_tmp: Path, monkeypatch):
    overlay_dir = imports_tmp.parent / "ovl-static"
    overlay_dir.mkdir(parents=True)
    (overlay_dir / "preview.png").write_bytes(b"\x89PNG-fake")
    spec = _make_spec(overlay_dir)
    _patch_spec(monkeypatch, spec)

    content, media, filename = export_layer(spec.layer_id, "png")
    assert media == "image/png"
    assert filename.endswith(".png")
    assert content == b"\x89PNG-fake"


def test_export_overlay_rejects_vector_formats(imports_tmp: Path, monkeypatch):
    overlay_dir = imports_tmp.parent / "ovl-static"
    overlay_dir.mkdir(parents=True)
    spec = _make_spec(overlay_dir)
    _patch_spec(monkeypatch, spec)

    for fmt in ("geojson", "csv", "shp-zip"):
        with pytest.raises(ValueError, match="不支持导出格式"):
            export_layer(spec.layer_id, fmt)


def test_export_overlay_unknown_layer_raises_not_found(imports_tmp: Path, monkeypatch):
    monkeypatch.setattr(overlay_registry, "get_overlay_spec", lambda _lid: None)
    with pytest.raises(FileNotFoundError, match="图层不存在"):
        export_layer("imported-does-not-exist", "tif")


def test_export_overlay_time_series_default_time(imports_tmp: Path, monkeypatch):
    overlay_dir = imports_tmp.parent / "ovl-ts"
    _write_real_tif(overlay_dir / "source_20251227_20251231.tif", value=0.7)
    _write_real_tif(overlay_dir / "source_20251203_20251210.tif", value=0.2)
    (overlay_dir / "preview_20251227_20251231.png").write_bytes(b"\x89PNG-1")
    (overlay_dir / "preview_20251203_20251210.png").write_bytes(b"\x89PNG-2")
    (overlay_dir / "meta.json").write_text(
        json.dumps({"label": "Ω", "display_name": "动态 Ω"}), encoding="utf-8"
    )
    spec = _make_spec(overlay_dir, time_series=True)
    _patch_spec(monkeypatch, spec)

    # 未指定 time → default_time（20251227_20251231），文件名带时间键
    content, media, filename = export_layer(spec.layer_id, "tif")
    assert media == "image/tiff"
    assert "20251227_20251231" in filename

    import numpy as np
    import rasterio

    with rasterio.open(BytesIO(content)) as ds:
        assert float(np.nanmax(ds.read(1))) == pytest.approx(0.7, abs=1e-3)

    # 显式另一时刻
    _content2, _m2, filename2 = export_layer(
        spec.layer_id, "tif", time="20251203_20251210"
    )
    assert "20251203_20251210" in filename2

    # 不在 time_list 的时刻被拒
    with pytest.raises(ValueError, match="时间切片不存在"):
        export_layer(spec.layer_id, "tif", time="20240101")

    # png 时序分支
    png, media_png, _ = export_layer(spec.layer_id, "png", time="20251203_20251210")
    assert media_png == "image/png"
    assert png == b"\x89PNG-2"


def test_export_overlay_time_series_multi_times_zip(imports_tmp: Path, monkeypatch):
    overlay_dir = imports_tmp.parent / "ovl-ts"
    _write_real_tif(overlay_dir / "source_20251227_20251231.tif", value=0.7)
    _write_real_tif(overlay_dir / "source_20251203_20251210.tif", value=0.2)
    spec = _make_spec(overlay_dir, time_series=True)
    _patch_spec(monkeypatch, spec)

    content, media, filename = export_layer(
        spec.layer_id,
        "tif",
        times=["20251203_20251210", "20251227_20251231"],
    )
    assert media == "application/zip"
    assert filename.endswith(".zip")
    with zipfile.ZipFile(BytesIO(content)) as zf:
        names = zf.namelist()
        assert len(names) == 2
        assert any("20251227_20251231" in n for n in names)
        assert any("20251203_20251210" in n for n in names)


def test_export_overlay_png_only_layer_rejects_tif(imports_tmp: Path, monkeypatch):
    """仅有预览 PNG、无科学数据源的 overlay，tif 导出应给出明确错误。"""
    overlay_dir = imports_tmp.parent / "ovl-pngonly"
    overlay_dir.mkdir(parents=True)
    (overlay_dir / "preview.png").write_bytes(b"\x89PNG-fake")
    spec = overlay_registry.OverlaySpec(
        layer_id="ref-png-only",
        overlay_dir=overlay_dir,
        category="static",
        png_filename="preview.png",
        bounds_filename="bounds.json",
    )
    _patch_spec(monkeypatch, spec)

    with pytest.raises(ValueError, match="无可导出的科学数据源"):
        export_layer(spec.layer_id, "tif")
