"""CSV 编码探测：GBK / UTF-8 / BOM。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.data_io.services import document as document_mod
from app.data_io.services import paths as import_paths
from app.data_io.services.document import _detect_csv_encoding, create_document_session


@pytest.fixture()
def docs_tmp(tmp_path, monkeypatch):
    imports_dir = tmp_path / "imports"
    docs = imports_dir / "_documents"
    monkeypatch.setattr(import_paths, "IMPORTS_DIR", imports_dir)
    monkeypatch.setattr(import_paths, "DOC_SESSIONS_DIR", docs)
    monkeypatch.setattr(document_mod, "DOC_SESSIONS_DIR", docs)
    import_paths.ensure_imports_root()
    return docs


def test_detect_utf8_bom(docs_tmp, tmp_path: Path):
    path = tmp_path / "bom.csv"
    path.write_bytes("\ufefflng,lat\n116,40\n".encode("utf-8-sig"))
    enc, note = _detect_csv_encoding(path)
    assert enc in {"utf-8-sig", "utf-8"}
    assert note


def test_detect_gbk(docs_tmp, tmp_path: Path):
    path = tmp_path / "gbk.csv"
    path.write_bytes("经度,纬度\n116,40\n".encode("gbk"))
    enc, note = _detect_csv_encoding(path)
    assert enc.lower() in {"gbk", "gb18030"}
    session = create_document_session(path, source_name="gbk.csv")
    assert session.get("encoding_note")
    assert "经度" in (session.get("columns") or [])


def test_detect_utf8(docs_tmp, tmp_path: Path):
    path = tmp_path / "utf8.csv"
    path.write_text("lng,lat\n1,2\n", encoding="utf-8")
    enc, _note = _detect_csv_encoding(path)
    assert enc.startswith("utf-8")
