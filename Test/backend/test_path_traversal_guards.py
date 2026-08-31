"""安审 2026-08-22（完全审查批次2，B-1~B-4/B-8）：路径穿越姊妹点回归测试。

统一收口 ``safe_import_child``：恶意 id 必须抛 ``ValueError``（路由层 _http_err
转 400），且不得触达文件系统。zip 条目名必须剥目录分量（防 zip-slip）。
"""

from __future__ import annotations

import pytest

from app.data_io.services import document as document_mod
from app.data_io.services import export_layer as export_mod
from app.data_io.services import jobs as jobs_mod
from app.data_io.services import paths as import_paths
from app.data_io.services import resumable_upload as resumable_mod
from app.data_io.services import vector as vector_mod
from app.services import zonal_stats_service

# 覆盖 posix/Windows 双分隔符与系统目录前缀
MALICIOUS_IDS = ["../escape", "..\\escape", "a/b", "a\\b", "..", "_staging"]


@pytest.fixture()
def imports_tmp(tmp_path, monkeypatch):
    root = tmp_path / "imports_output"
    imports_dir = root / "imports"
    staging = imports_dir / "_staging"
    jobs = imports_dir / "_jobs"
    docs = imports_dir / "_documents"

    for mod in (
        import_paths,
        vector_mod,
        document_mod,
        export_mod,
        jobs_mod,
        resumable_mod,
    ):
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


@pytest.mark.parametrize("bad_id", MALICIOUS_IDS)
def test_vector_read_rejects_traversal(imports_tmp, bad_id):
    with pytest.raises(ValueError):
        vector_mod.load_vector_meta(bad_id)
    with pytest.raises(ValueError):
        vector_mod.load_vector_geojson(bad_id)


@pytest.mark.parametrize("bad_id", MALICIOUS_IDS)
def test_vector_write_rejects_traversal(imports_tmp, bad_id):
    with pytest.raises(ValueError):
        vector_mod.patch_feature_attribute(bad_id, 0, "field", 1)
    with pytest.raises(ValueError):
        vector_mod.add_vector_field(bad_id, "name")
    with pytest.raises(ValueError):
        vector_mod.delete_vector_field(bad_id, "name")


@pytest.mark.parametrize("bad_id", MALICIOUS_IDS)
def test_document_session_rejects_traversal(imports_tmp, bad_id):
    with pytest.raises(ValueError):
        document_mod._load_table(bad_id)
    with pytest.raises(ValueError):
        document_mod._save_table(bad_id, {"columns": [], "rows": []})


@pytest.mark.parametrize("bad_id", MALICIOUS_IDS)
def test_jobs_reject_traversal(imports_tmp, bad_id):
    with pytest.raises(ValueError):
        jobs_mod.get_job(bad_id)
    with pytest.raises(ValueError):
        jobs_mod.update_job(bad_id, status="x")


@pytest.mark.parametrize("bad_id", MALICIOUS_IDS)
def test_export_layer_rejects_traversal(imports_tmp, bad_id):
    with pytest.raises(ValueError):
        export_mod.export_layer(bad_id, "geojson")


@pytest.mark.parametrize("bad_id", MALICIOUS_IDS)
def test_resumable_upload_rejects_traversal(imports_tmp, bad_id):
    with pytest.raises(ValueError):
        resumable_mod._load_meta(bad_id)
    with pytest.raises(ValueError):
        resumable_mod.complete_resumable(bad_id)
    with pytest.raises(ValueError):
        resumable_mod._discard_resumable(bad_id)


@pytest.mark.parametrize("bad_id", MALICIOUS_IDS[:4])
def test_zonal_stats_resolve_rejects_traversal(imports_tmp, bad_id, tmp_path):
    assert zonal_stats_service._resolve_raster_path(bad_id, tmp_path, {}) is None


def test_zip_safe_name_strips_directory_components():
    assert export_mod._zip_safe_name("../../evil.txt") == "evil.txt"
    assert export_mod._zip_safe_name("..\\..\\evil.txt") == "evil.txt"
    assert export_mod._zip_safe_name("normal-name") == "normal-name"
    assert export_mod._zip_safe_name("") == "unnamed"


def test_legit_ids_still_work(imports_tmp):
    """合法 id 不被误伤：走通校验、落到预期目录。"""
    dest = import_paths.safe_import_child("imported-vec-abc123")
    assert dest.parent.name == "imports"
    job_path = jobs_mod._job_path("job-0123456789abcdef")
    assert job_path.name == "job-0123456789abcdef.json"
    session_dir = document_mod._session_dir("doc-abcdef012345")
    assert session_dir.parent.name == "_documents"
