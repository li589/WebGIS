"""dbf_encoding：跨平台 SHP/DBF 多编码探测。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.data_io.services import dbf_encoding as enc
from app.data_io.services.vector import _shapefile_to_geojson


def test_normalize_codepage_aliases():
    assert enc.normalize_encoding_name("GBK") == "gbk"
    assert enc.normalize_encoding_name("936") == "gbk"
    assert enc.normalize_encoding_name("UTF-8") == "utf-8"
    assert enc.normalize_encoding_name("ANSI") == "gbk"
    assert enc.normalize_encoding_name("65001") == "utf-8"
    assert enc.normalize_encoding_name("windows-1252") == "cp1252"
    assert enc.normalize_encoding_name("Shift_JIS") in {"shift_jis", "cp932"}


def test_codec_available_skips_mbcs_on_non_windows():
    if sys.platform == "win32":
        assert enc.codec_available("utf-8")
    else:
        assert not enc.codec_available("mbcs")
        assert enc.codec_available("utf-8")
        assert enc.codec_available("gbk")


def test_read_cpg_and_ansi_expands_candidates(tmp_path: Path):
    shp = tmp_path / "a.shp"
    shp.write_bytes(b"")
    (tmp_path / "a.cpg").write_text("ANSI\n", encoding="ascii")
    assert enc.read_cpg_encoding(shp) == "gbk"
    candidates, sources = enc.build_encoding_candidates(shp)
    assert candidates[0] == "gbk"
    assert any(s.startswith("cpg-ansi") for s in sources)
    assert "cp1252" in candidates


def test_ldid_chinese_simplified(tmp_path: Path):
    dbf = tmp_path / "x.dbf"
    # Minimal 32-byte header with LDID 0x4D at offset 29
    head = bytearray(32)
    head[0] = 0x03
    head[29] = 0x4D
    dbf.write_bytes(bytes(head))
    assert enc.read_dbf_ldid(dbf) == 0x4D
    assert enc.ldid_to_encoding(0x4D) == "gbk"


def test_score_prefers_cjk_over_mojibake():
    good = enc.score_decoded_text(["基地带", "测区A"], encoding="gbk")
    bad = enc.score_decoded_text(["»ùµØ´ø", "\ufffd\ufffd"], encoding="utf-8")
    assert good > bad


def test_decode_dbf_bytes_gbk():
    raw = "基地带".encode("gbk")
    text, used = enc.decode_dbf_bytes(raw, ["utf-8", "gbk", "latin-1"])
    assert text == "基地带"
    assert used == "gbk"


def test_shapefile_gbk_without_cpg(tmp_path: Path):
    shapefile = pytest.importorskip("shapefile")
    base = tmp_path / "layer"
    writer = shapefile.Writer(str(base), encoding="gbk")
    writer.field("基地带", "C", 20)
    writer.field("NAME", "C", 10)
    writer.point(116.4, 39.9)
    writer.record("测区A", "north")
    writer.close()

    geojson, meta = _shapefile_to_geojson(base.with_suffix(".shp"))
    used = str(meta["source_encoding"]).lower()
    assert used in {"gbk", "gb18030", "cp936"} or used.startswith("gb")
    assert meta["encoding_strict"] is True
    props = geojson["features"][0]["properties"]
    assert "基地带" in props
    assert props["基地带"] == "测区A"
    assert props["NAME"] == "north"


def test_shapefile_cpg_utf8(tmp_path: Path):
    shapefile = pytest.importorskip("shapefile")
    base = tmp_path / "u"
    writer = shapefile.Writer(str(base), encoding="utf-8")
    writer.field("名称", "C", 20)
    writer.point(1.0, 2.0)
    writer.record("甲")
    writer.close()
    base.with_suffix(".cpg").write_text("UTF-8", encoding="ascii")

    geojson, meta = _shapefile_to_geojson(base.with_suffix(".shp"))
    assert str(meta["source_encoding"]).lower().startswith("utf-8")
    assert geojson["features"][0]["properties"]["名称"] == "甲"


def test_probe_resolution_includes_platform(tmp_path: Path):
    shapefile = pytest.importorskip("shapefile")
    base = tmp_path / "p"
    writer = shapefile.Writer(str(base), encoding="utf-8")
    writer.field("A", "C", 5)
    writer.point(0, 0)
    writer.record("x")
    writer.close()
    resolution = enc.probe_shapefile_encoding(base.with_suffix(".shp"))
    assert resolution.platform == sys.platform
    assert resolution.encoding
    assert resolution.candidates_tried
