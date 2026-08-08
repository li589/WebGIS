"""统一导入/导出服务单测（小 fixture，不依赖 Celery）。"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from app.data_io.services import document as document_mod
from app.data_io.services import export_layer as export_mod
from app.data_io.services import jobs as jobs_mod
from app.data_io.services import paths as import_paths
from app.data_io.services import upload as upload_mod
from app.data_io.services import vector as vector_mod
from app.data_io.services.document import (
    apply_document_ops,
    commit_document_session,
    create_document_session,
)
from app.data_io.services.export_layer import export_layer
from app.data_io.services.upload import (
    append_chunk,
    complete_upload,
    init_upload,
    resolve_upload_path,
)
from app.data_io.services.vector import import_vector_from_paths


@pytest.fixture()
def imports_tmp(tmp_path, monkeypatch):
    root = tmp_path / "imports_output"
    imports_dir = root / "imports"
    staging = imports_dir / "_staging"
    jobs = imports_dir / "_jobs"
    docs = imports_dir / "_documents"

    for mod in (import_paths, upload_mod, vector_mod, document_mod, export_mod, jobs_mod):
        if hasattr(mod, "IMPORTS_DIR"):
            monkeypatch.setattr(mod, "IMPORTS_DIR", imports_dir)
        if hasattr(mod, "STAGING_DIR"):
            monkeypatch.setattr(mod, "STAGING_DIR", staging)
        if hasattr(mod, "JOBS_DIR"):
            monkeypatch.setattr(mod, "JOBS_DIR", jobs)
        if hasattr(mod, "DOC_SESSIONS_DIR"):
            monkeypatch.setattr(mod, "DOC_SESSIONS_DIR", docs)

    import_paths.ensure_imports_root()
    return root


def test_chunked_upload_roundtrip(imports_tmp):
    payload = b"hello-import-chunk"
    meta = init_upload(filename="demo.txt", size=len(payload))
    upload_id = meta["upload_id"]
    append_chunk(upload_id, payload, offset=0)
    done = complete_upload(upload_id)
    path = resolve_upload_path(upload_id)
    assert path.exists()
    assert path.read_bytes() == payload
    assert done["size"] == len(payload)
    # 幂等 complete：网络重试不应报会话丢失
    again = complete_upload(upload_id)
    assert again["upload_id"] == upload_id
    assert resolve_upload_path(upload_id).exists()


def test_bigtiff_magic_accepted(imports_tmp, tmp_path):
    from app.data_io.services.upload_validation import sniff_magic

    # BigTIFF little-endian magic II+\x00
    big = tmp_path / "soil.tif"
    big.write_bytes(b"II+\x00" + b"\x00" * 32)
    sniff_magic(big, declared_ext="tif")

    # classic still ok
    classic = tmp_path / "classic.tif"
    classic.write_bytes(b"II*\x00" + b"\x00" * 32)
    sniff_magic(classic, declared_ext="tif")


def test_vector_geojson_import_and_export(imports_tmp):
    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [120.1, 30.2]},
                "properties": {"name": "a"},
            }
        ],
    }
    path = imports_tmp / "pts.geojson"
    path.write_text(json.dumps(gj), encoding="utf-8")
    result = import_vector_from_paths([path], source_name="pts.geojson")
    assert result["feature_count"] == 1
    layer_id = result["layer_id"]

    content, media, filename = export_layer(layer_id, "geojson")
    assert filename.endswith(".geojson")
    assert b"120.1" in content

    content_csv, _media_csv, name_csv = export_layer(layer_id, "csv")
    assert name_csv.endswith(".csv")
    assert b"name" in content_csv


def test_document_ops_and_commit(imports_tmp):
    csv_path = imports_tmp / "sites.csv"
    csv_path.write_text("lon,lat,tag\n121.0,31.0,foo-bar\n122.0,32.0,baz\n", encoding="utf-8")
    session = create_document_session(csv_path, source_name="sites.csv")
    assert session["row_count"] == 2

    session = apply_document_ops(
        session["session_id"],
        [
            {"op": "rename", "from": "tag", "to": "label"},
            {"op": "find_replace", "field": "label", "find": "-", "replace": "_"},
            {"op": "split", "field": "label", "separator": "_", "into": ["a", "b"]},
            {"op": "filter", "field": "a", "contains": "foo"},
        ],
    )
    assert session["row_count"] == 1

    committed = commit_document_session(
        session["session_id"],
        x_field="lon",
        y_field="lat",
        source_crs="EPSG:4326",
    )
    assert committed["point_count"] == 1
    assert committed["layer_id"]
    assert committed.get("xy_swap_applied") is False


def test_document_swap_xy_force_and_auto(imports_tmp):
    # 颠倒：x=lat, y=lng → auto 应交换
    csv_path = imports_tmp / "swapped.csv"
    csv_path.write_text("x,y\n39.9,116.4\n40.0,116.5\n", encoding="utf-8")
    session = create_document_session(csv_path, source_name="swapped.csv")
    auto = commit_document_session(
        session["session_id"],
        x_field="x",
        y_field="y",
        source_crs="EPSG:4326",
        swap_xy=None,
    )
    assert auto["xy_swap_applied"] is True
    feat = auto["preview_geojson"]["features"][0]
    assert feat["geometry"]["coordinates"][0] == pytest.approx(116.4, abs=1e-6)

    csv2 = imports_tmp / "force.csv"
    csv2.write_text("x,y\n116.0,39.0\n", encoding="utf-8")
    s2 = create_document_session(csv2, source_name="force.csv")
    forced = commit_document_session(
        s2["session_id"],
        x_field="x",
        y_field="y",
        source_crs="EPSG:4326",
        swap_xy=True,
    )
    assert forced["xy_swap_applied"] is True
    assert forced["preview_geojson"]["features"][0]["geometry"]["coordinates"] == [
        39.0,
        116.0,
    ]


def test_export_shp_zip_requires_pyshp_or_skips(imports_tmp):
    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                "properties": {"id": 1},
            }
        ],
    }
    path = imports_tmp / "one.geojson"
    path.write_text(json.dumps(gj), encoding="utf-8")
    layer_id = import_vector_from_paths([path])["layer_id"]
    try:
        content, media, filename = export_layer(layer_id, "shp-zip")
    except RuntimeError as exc:
        if "pyshp" in str(exc).lower() or "shapefile" in str(exc).lower():
            pytest.skip("pyshp not installed")
        raise
    assert media == "application/zip"
    assert filename.endswith(".zip")
    with zipfile.ZipFile(BytesIO(content)) as zf:
        names = zf.namelist()
    assert any(n.endswith(".shp") for n in names)
    assert any(n.endswith(".dbf") for n in names)

def test_reject_executable_extension(imports_tmp):
    with pytest.raises(ValueError, match='拒绝|不支持'):
        init_upload(filename='evil.exe', size=16)


def test_reject_zip_path_traversal(imports_tmp, tmp_path):
    from app.data_io.services.archive_safe import ArchiveSecurityError, safe_extract_zip

    bomb = tmp_path / 'trav.zip'
    with zipfile.ZipFile(bomb, 'w') as zf:
        zf.writestr('../escape.txt', 'pwn')
    dest = tmp_path / 'out'
    with pytest.raises(ArchiveSecurityError, match='非法|穿越'):
        safe_extract_zip(bomb, dest)


def test_safe_zip_extract_ok(imports_tmp, tmp_path):
    from app.data_io.services.archive_safe import safe_extract_zip

    archive = tmp_path / 'ok.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('folder/a.geojson', '{\"type\":\"FeatureCollection\",\"features\":[]}')
    dest = tmp_path / 'out'
    files = safe_extract_zip(archive, dest)
    assert len(files) == 1
    assert files[0].name == 'a.geojson'


def test_delete_imported_layer_dir(imports_tmp):
    """DELETE /import/layers/{id} 清理 imports 目录（服务层等价校验）。"""
    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                "properties": {"n": "a"},
            }
        ],
    }
    path = imports_tmp / "del.geojson"
    path.write_text(json.dumps(gj), encoding="utf-8")
    layer_id = import_vector_from_paths([path])["layer_id"]
    assert layer_id.startswith("imported")
    dest = import_paths.IMPORTS_DIR / layer_id
    assert dest.exists()
    # 模拟路由删除
    import shutil

    shutil.rmtree(dest)
    assert not dest.exists()


def test_shp_sidecar_error_lists_received(imports_tmp, tmp_path):
    from app.data_io.services.vector import _collect_shp_group

    alone = tmp_path / "only.shp"
    alone.write_bytes(b"00")
    with pytest.raises(ValueError, match="浏览器不会自动|一并选择|当前收到"):
        _collect_shp_group([alone])


def test_content_disposition_allows_chinese_filename():
    from app.data_io.services.http_files import content_disposition_attachment

    headers = content_disposition_attachment("气候区划.geojson")
    cd = headers["Content-Disposition"]
    # latin-1 encodable
    cd.encode("latin-1")
    assert "filename*=" in cd
    assert "UTF-8''" in cd


def test_list_features_sort_where_and_patch(imports_tmp):
    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                "properties": {"name": "b", "score": 2},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [3.0, 4.0]},
                "properties": {"name": "a", "score": 9},
            },
        ],
    }
    path = imports_tmp / "attr.geojson"
    path.write_text(json.dumps(gj), encoding="utf-8")
    layer_id = import_vector_from_paths([path])["layer_id"]

    from app.data_io.services.vector import (
        list_vector_features,
        patch_feature_attribute,
        batch_set_feature_attribute,
        add_vector_field,
    )

    sorted_res = list_vector_features(layer_id, sort="name")
    assert sorted_res["features"][0]["properties"]["name"] == "a"
    assert sorted_res["indexes"][0] == 1

    where_res = list_vector_features(layer_id, where="score>5")
    assert where_res["total"] == 1
    assert where_res["features"][0]["properties"]["name"] == "a"

    patch_feature_attribute(layer_id, 0, "name", "bb")
    batch_set_feature_attribute(layer_id, [0, 1], "tag", "x")
    added = add_vector_field(layer_id, "note", default="")
    assert "note" in (added.get("fields") or [])
    after = list_vector_features(layer_id, limit=10)
    assert after["features"][0]["properties"]["name"] == "bb"
    assert after["features"][0]["properties"]["tag"] == "x"


def test_export_batch_zip_and_jobs(imports_tmp):
    from app.data_io.services.export_layer import export_layers_batch_zip
    from app.data_io.services.jobs import cancel_job, create_job, list_jobs
    from app.data_io.services.upload import cleanup_expired_staging, init_upload

    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                "properties": {"n": "a"},
            }
        ],
    }
    path = imports_tmp / "b1.geojson"
    path.write_text(json.dumps(gj), encoding="utf-8")
    layer_id = import_vector_from_paths([path])["layer_id"]
    result = export_layers_batch_zip([layer_id], format="geojson")
    assert Path(result["download_path"]).exists()

    job_id = create_job(kind="export_batch", payload={})
    assert list_jobs(limit=5)
    cancelled = cancel_job(job_id)
    assert cancelled["status"] == "cancelled"

    # staging TTL：伪造过期目录
    meta = init_upload(filename="old.geojson", size=4)
    upload_id = meta["upload_id"]
    dest = import_paths.STAGING_DIR / upload_id
    meta_path = dest / "meta.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["created_at"] = 0
    meta_path.write_text(json.dumps(data), encoding="utf-8")
    removed = cleanup_expired_staging(ttl_seconds=60)
    assert removed >= 1
