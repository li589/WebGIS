"""数据源管理子系统 P2-4 归位：COG/GeoTIFF direct 源接入测试。

职责边界（2026-08-25 架构归位）：
- data_io.direct_source：接入 API（register_direct_geotiff）+ 形态判定单一真源
- overlay_registry：lazy-load 委托 data_io 判定（不自带接入知识）
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


def _make_tif(path: Path, *, west=100.0, south=30.0, east=110.0, north=40.0) -> Path:
    """生成一个真实可读的小 GeoTIFF（EPSG:4326）。"""
    import rasterio
    from rasterio.transform import from_bounds

    data = np.arange(16, dtype=np.float32).reshape(4, 4)
    transform = from_bounds(west, south, east, north, 4, 4)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path


# ── find_direct_source：形态判定单一真源 ────────────────────────────────────


def test_find_direct_source_explicit_meta(tmp_path: Path) -> None:
    from app.data_io.services.direct_source import find_direct_source

    (tmp_path / "mydata.cog").write_bytes(b"")
    src = find_direct_source(tmp_path, {"source_filename": "mydata.cog"})
    assert src == tmp_path / "mydata.cog"


def test_find_direct_source_glob_fallback(tmp_path: Path) -> None:
    from app.data_io.services.direct_source import find_direct_source

    (tmp_path / "source.tif").write_bytes(b"")
    src = find_direct_source(tmp_path, None)
    assert src == tmp_path / "source.tif"


def test_find_direct_source_rejects_non_geotiff(tmp_path: Path) -> None:
    from app.data_io.services.direct_source import find_direct_source

    (tmp_path / "source.nc").write_bytes(b"")
    assert find_direct_source(tmp_path, {"source_filename": "source.nc"}) is None
    assert find_direct_source(tmp_path, None) is None


def test_find_direct_source_empty_dir(tmp_path: Path) -> None:
    from app.data_io.services.direct_source import find_direct_source

    assert find_direct_source(tmp_path, None) is None


# ── register_direct_geotiff：接入 API ──────────────────────────────────────


def test_register_direct_geotiff_creates_direct_layer(tmp_path, monkeypatch) -> None:
    from app.data_io.services import direct_source
    from app.services.overlay_registry import get_overlay_spec, unregister_overlay

    imports_root = tmp_path / "imports"
    monkeypatch.setattr("app.data_io.services.paths.IMPORTS_DIR", imports_root)
    # 配额检查依赖 imports 根存在
    monkeypatch.setattr(
        "app.data_io.services.paths.assert_quota_available", lambda *a, **k: None
    )

    tif = _make_tif(tmp_path / "big_cog.tif")
    result = direct_source.register_direct_geotiff(
        tif,
        layer_id="imported-direct-cog",
        palette="turbo",
        vmin=0,
        vmax=15,
    )

    assert result["layer_id"] == "imported-direct-cog"
    assert result["has_overview"] is False
    assert result["preview_generated"] is False
    dest = Path(result["dir"])
    assert (dest / "source.tif").is_file()
    assert not (dest / "preview.png").exists()  # 免烘焙

    # bounds.json 落盘且值正确
    data = json.loads((dest / "bounds.json").read_text(encoding="utf-8"))
    assert data["bounds"] == [100.0, 30.0, 110.0, 40.0]
    assert data["meta"]["has_overview"] is False
    assert data["meta"]["palette"] == "turbo"

    # overlay spec 注册成功且无 overview
    try:
        spec = get_overlay_spec("imported-direct-cog")
        assert spec is not None
        assert spec.png_filename is None
        assert spec.source_path is not None and spec.source_path.name == "source.tif"
    finally:
        unregister_overlay("imported-direct-cog")


def test_register_direct_geotiff_rejects_bad_suffix(tmp_path, monkeypatch) -> None:
    from app.data_io.services import direct_source

    monkeypatch.setattr("app.data_io.services.paths.IMPORTS_DIR", tmp_path / "imports")
    bad = tmp_path / "data.nc"
    bad.write_bytes(b"")
    with pytest.raises(ValueError, match="非法 direct 源"):
        direct_source.register_direct_geotiff(bad)


def test_register_direct_geotiff_duplicate_rejected(tmp_path, monkeypatch) -> None:
    from app.data_io.services import direct_source
    from app.services.overlay_registry import unregister_overlay

    imports_root = tmp_path / "imports"
    monkeypatch.setattr("app.data_io.services.paths.IMPORTS_DIR", imports_root)
    monkeypatch.setattr(
        "app.data_io.services.paths.assert_quota_available", lambda *a, **k: None
    )
    tif = _make_tif(tmp_path / "dup.tif")

    direct_source.register_direct_geotiff(tif, layer_id="imported-dup")
    try:
        with pytest.raises(ValueError, match="已存在"):
            direct_source.register_direct_geotiff(tif, layer_id="imported-dup")
    finally:
        unregister_overlay("imported-dup")


# ── registry 委托闭环：lazy-load 经 data_io 判定 ────────────────────────────


def test_registry_lazy_load_delegates_to_data_io(tmp_path, monkeypatch) -> None:
    """手工放置 direct 源目录（无 register API）→ lazy-load 识别注册。"""
    from app.services import overlay_registry as reg

    dest = tmp_path / "imports" / "imported-manual-direct"
    dest.mkdir(parents=True)
    tif = _make_tif(dest / "source.tif")
    (dest / "bounds.json").write_text(
        json.dumps({"bounds": [100.0, 30.0, 110.0, 40.0], "meta": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.data_io.services.paths.IMPORTS_DIR", tmp_path / "imports")

    reg.unregister_overlay("imported-manual-direct")
    try:
        spec = reg._try_load_imported_overlay("imported-manual-direct")
        assert spec is not None
        assert spec.png_filename is None
        assert spec.source_path == tif
    finally:
        reg.unregister_overlay("imported-manual-direct")
