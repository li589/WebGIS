"""数据导入/导出扩展路由：分块上传、矢量、文档、科学栅格、导出。"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.api.deps import require_write_access
from app.data_io.services import paths as import_paths
from app.data_io.services.document import (
    apply_document_ops,
    commit_document_session,
    create_document_session,
    preview_document_session,
)
from app.data_io.services.export_layer import (
    export_layer,
    export_layers_batch_zip,
    list_export_encodings,
)
from app.data_io.services.http_files import content_disposition_attachment
from app.data_io.services.jobs import cancel_job, enqueue_job, get_job, list_jobs
from app.data_io.services.raster_science import list_raster_variables
from app.data_io.services.upload import (
    append_chunk,
    complete_upload,
    discard_upload,
    init_upload,
    resolve_upload_path,
)
from app.data_io.services.vector import (
    add_vector_field,
    batch_set_feature_attribute,
    delete_vector_field,
    import_vector_from_paths,
    list_vector_features,
    load_vector_geojson,
    load_vector_meta,
    patch_feature_attribute,
    rename_vector_field,
)

router = APIRouter(tags=["data-io"])


class UploadInitBody(BaseModel):
    filename: str
    size: int
    content_type: str | None = None


class UploadCompleteBody(BaseModel):
    upload_id: str


class VectorImportBody(BaseModel):
    upload_ids: list[str] = Field(default_factory=list)
    source_name: str | None = None
    async_mode: bool = False


class RasterInspectBody(BaseModel):
    upload_id: str


class RasterCommitBody(BaseModel):
    upload_id: str
    variable_id: str | None = None
    """单变量（兼容旧客户端）。与 variable_ids 二选一，优先 variable_ids。"""
    variable_ids: list[str] = Field(default_factory=list)
    time_index: int = 0
    source_name: str | None = None
    async_mode: bool = False
    source_crs: str | None = None
    grid_preset: str | None = None
    bounds: list[float] | None = None
    """源 CRS 下 [west, south, east, north]。"""
    invalid_values: list[float] = Field(default_factory=list)
    """导入前替换为 nodata 的无效值列表。"""
    nodata: float | None = None
    auto_confirm: bool = True
    """若提供 source_crs 且非 WGS84 等价系，提交后自动重投影到 WGS84。"""
    lng_offset: float = 0.0
    lat_offset: float = 0.0


class DocumentOpsBody(BaseModel):
    ops: list[dict[str, Any]]


class DocumentCommitBody(BaseModel):
    x_field: str
    y_field: str
    source_crs: str = "EPSG:4326"
    target_crs: str = "EPSG:4326"
    lng_offset: float = 0.0
    lat_offset: float = 0.0
    async_mode: bool = False


class VectorRenameBody(BaseModel):
    old_name: str
    new_name: str


class FeaturePatchBody(BaseModel):
    field: str
    value: Any = None


class FeatureBatchBody(BaseModel):
    indexes: list[int]
    field: str
    value: Any = None


class FieldAddBody(BaseModel):
    name: str
    default: Any = ""


class ExportBody(BaseModel):
    layer_id: str
    format: str = "geojson"
    # auto | utf-8 | utf-8-sig | gbk | gb18030 | big5 | cp1252 | …
    encoding: str | None = "auto"


class ExportBatchBody(BaseModel):
    layer_ids: list[str] = Field(default_factory=list)
    format: str = "geojson"
    encoding: str | None = "auto"
    async_mode: bool = False


class BatchGroupBody(BaseModel):
    kind: str
    upload_ids: list[str] = Field(default_factory=list)
    source_name: str | None = None
    variable_id: str | None = None
    time_index: int = 0


class ImportBatchBody(BaseModel):
    groups: list[BatchGroupBody] = Field(default_factory=list)


def _http_err(exc: Exception, *, not_found: bool = False) -> HTTPException:
    if isinstance(exc, FileNotFoundError) or not_found:
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, import_paths.QuotaExceededError):
        return HTTPException(status_code=507, detail=str(exc))
    if isinstance(exc, (ValueError, RuntimeError)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _raster_commit_sync(body: RasterCommitBody) -> dict[str, Any]:
    from app.data_io.services.raster_commit import commit_raster_upload

    return commit_raster_upload(
        upload_id=body.upload_id,
        variable_id=body.variable_id,
        variable_ids=list(body.variable_ids or []),
        time_index=body.time_index,
        source_name=body.source_name,
        source_crs=body.source_crs,
        grid_preset=body.grid_preset,
        bounds=body.bounds,
        invalid_values=list(body.invalid_values or []),
        nodata=body.nodata,
        auto_confirm=body.auto_confirm,
        lng_offset=body.lng_offset,
        lat_offset=body.lat_offset,
    )


# ── 分块上传 ────────────────────────────────────────────────────────────


@router.post("/import/upload/init", dependencies=[Depends(require_write_access)])
async def upload_init(body: UploadInitBody) -> dict[str, Any]:
    try:
        return init_upload(
            filename=body.filename, size=body.size, content_type=body.content_type
        )
    except Exception as exc:
        raise _http_err(exc) from exc


@router.post(
    "/import/upload/{upload_id}/chunk", dependencies=[Depends(require_write_access)]
)
async def upload_chunk(
    upload_id: str,
    file: UploadFile = File(...),
    offset: int | None = Form(default=None),
) -> dict[str, Any]:
    try:
        data = await file.read()
        return append_chunk(upload_id, data, offset=offset)
    except Exception as exc:
        raise _http_err(exc) from exc
    finally:
        await file.close()


@router.post("/import/upload/complete", dependencies=[Depends(require_write_access)])
async def upload_complete(body: UploadCompleteBody) -> dict[str, Any]:
    try:
        return complete_upload(body.upload_id)
    except Exception as exc:
        raise _http_err(exc) from exc


@router.delete(
    "/import/upload/{upload_id}", dependencies=[Depends(require_write_access)]
)
async def upload_discard(upload_id: str) -> dict[str, Any]:
    discard_upload(upload_id)
    return {"ok": True, "upload_id": upload_id}


@router.get("/import/jobs", dependencies=[Depends(require_write_access)])
async def import_jobs_list(limit: int = 20) -> dict[str, Any]:
    return {"items": list_jobs(limit=limit)}


@router.get("/import/jobs/{job_id}", dependencies=[Depends(require_write_access)])
async def import_job_status(job_id: str) -> dict[str, Any]:
    try:
        return get_job(job_id)
    except Exception as exc:
        raise _http_err(exc, not_found=True) from exc


@router.post(
    "/import/jobs/{job_id}/cancel", dependencies=[Depends(require_write_access)]
)
async def import_job_cancel(job_id: str) -> dict[str, Any]:
    try:
        return cancel_job(job_id)
    except Exception as exc:
        raise _http_err(exc, not_found=True) from exc


@router.get(
    "/import/jobs/{job_id}/download", dependencies=[Depends(require_write_access)]
)
async def import_job_download(job_id: str) -> FileResponse:
    try:
        job = get_job(job_id)
    except Exception as exc:
        raise _http_err(exc, not_found=True) from exc
    result = job.get("result") or {}
    path_str = result.get("download_path") if isinstance(result, dict) else None
    if not path_str:
        raise HTTPException(status_code=404, detail="该任务无可下载文件")
    path = Path(str(path_str))
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="导出文件已失效")
    exports_root = (import_paths.IMPORTS_DIR / "_exports").resolve()
    try:
        path.resolve().relative_to(exports_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法下载路径") from exc
    filename = result.get("filename") if isinstance(result, dict) else path.name
    return FileResponse(
        path,
        media_type="application/zip",
        filename=str(filename or path.name),
    )


# ── 批导入 ─────────────────────────────────────────────────────────────


@router.post("/import/batch", dependencies=[Depends(require_write_access)])
async def import_batch(body: ImportBatchBody) -> dict[str, Any]:
    if not body.groups:
        raise HTTPException(status_code=400, detail="groups 不能为空")
    batch_id = f"batch-{uuid.uuid4().hex[:12]}"
    job_ids: list[str] = []
    try:
        for group in body.groups:
            kind = group.kind.strip().lower()
            if not group.upload_ids:
                continue
            paths = [resolve_upload_path(uid) for uid in group.upload_ids]
            source_name = group.source_name or paths[0].name
            if kind == "vector":
                job = enqueue_job(
                    "vector",
                    {
                        "paths": [str(p) for p in paths],
                        "source_name": source_name,
                    },
                    force_async=True,
                )
                job_ids.append(job["job_id"])
            elif kind == "document":
                job = enqueue_job(
                    "document",
                    {"path": str(paths[0]), "source_name": source_name},
                    force_async=True,
                )
                job_ids.append(job["job_id"])
            elif kind == "raster":
                job = enqueue_job(
                    "raster_commit",
                    {
                        "path": str(paths[0]),
                        "upload_id": group.upload_ids[0],
                        "variable_id": group.variable_id,
                        "time_index": group.time_index,
                        "source_name": source_name,
                    },
                    force_async=True,
                )
                job_ids.append(job["job_id"])
            else:
                raise ValueError(f"不支持的批导入类型: {kind}")
    except Exception as exc:
        raise _http_err(exc) from exc
    if not job_ids:
        raise HTTPException(status_code=400, detail="没有有效的导入组")
    return {"batch_id": batch_id, "job_ids": job_ids}


# ── 矢量 ───────────────────────────────────────────────────────────────


@router.post("/import/vector", dependencies=[Depends(require_write_access)])
async def import_vector(body: VectorImportBody) -> dict[str, Any]:
    if not body.upload_ids:
        raise HTTPException(status_code=400, detail="upload_ids 不能为空")
    try:
        paths = [resolve_upload_path(uid) for uid in body.upload_ids]
        total = sum(p.stat().st_size for p in paths)
        force_async = body.async_mode or total > import_paths.CHUNK_SYNC_THRESHOLD_BYTES

        def handler(payload: dict[str, Any]) -> dict[str, Any]:
            ps = [Path(p) for p in payload["paths"]]
            return import_vector_from_paths(ps, source_name=payload.get("source_name"))

        if force_async:
            job = enqueue_job(
                "vector",
                {
                    "paths": [str(p) for p in paths],
                    "source_name": body.source_name or paths[0].name,
                },
                handler,
                force_async=True,
            )
            return {"job_id": job["job_id"], "status": job["status"], "async": True}

        result = import_vector_from_paths(
            paths, source_name=body.source_name or paths[0].name
        )
        return {"async": False, **result}
    except Exception as exc:
        raise _http_err(exc) from exc


@router.post("/import/vector/multipart", dependencies=[Depends(require_write_access)])
async def import_vector_multipart(
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="未上传文件")
    tmp = Path(tempfile.mkdtemp(prefix="vec-upload-"))
    try:
        paths: list[Path] = []
        for f in files:
            name = Path(f.filename or "upload.bin").name
            dest = tmp / name
            with dest.open("wb") as out:
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            paths.append(dest)
            await f.close()
        result = import_vector_from_paths(paths, source_name=paths[0].name)
        return {"async": False, **result}
    except Exception as exc:
        raise _http_err(exc) from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@router.get(
    "/import/layers/{layer_id}/meta", dependencies=[Depends(require_write_access)]
)
async def vector_meta(layer_id: str) -> dict[str, Any]:
    try:
        return load_vector_meta(layer_id)
    except Exception as exc:
        raise _http_err(exc, not_found=True) from exc


@router.get(
    "/import/layers/{layer_id}/geojson", dependencies=[Depends(require_write_access)]
)
async def vector_geojson(layer_id: str, preview: bool = True) -> dict[str, Any]:
    try:
        return load_vector_geojson(layer_id, preview=preview)
    except Exception as exc:
        raise _http_err(exc, not_found=True) from exc


@router.get(
    "/import/layers/{layer_id}/features", dependencies=[Depends(require_write_access)]
)
async def vector_features(
    layer_id: str,
    limit: int = 100,
    offset: int = 0,
    field: str | None = None,
    contains: str | None = None,
    sort: str | None = None,
    where: str | None = None,
) -> dict[str, Any]:
    try:
        return list_vector_features(
            layer_id,
            limit=limit,
            offset=offset,
            field_filter=field,
            value_contains=contains,
            sort=sort,
            where=where,
        )
    except Exception as exc:
        raise _http_err(exc, not_found=True) from exc


@router.patch(
    "/import/layers/{layer_id}/features/{feature_index}",
    dependencies=[Depends(require_write_access)],
)
async def vector_feature_patch(
    layer_id: str, feature_index: int, body: FeaturePatchBody
) -> dict[str, Any]:
    try:
        return patch_feature_attribute(layer_id, feature_index, body.field, body.value)
    except Exception as exc:
        raise _http_err(exc) from exc


@router.post(
    "/import/layers/{layer_id}/features/batch",
    dependencies=[Depends(require_write_access)],
)
async def vector_feature_batch(layer_id: str, body: FeatureBatchBody) -> dict[str, Any]:
    try:
        return batch_set_feature_attribute(
            layer_id, body.indexes, body.field, body.value
        )
    except Exception as exc:
        raise _http_err(exc) from exc


@router.post(
    "/import/layers/{layer_id}/fields", dependencies=[Depends(require_write_access)]
)
async def vector_field_add(layer_id: str, body: FieldAddBody) -> dict[str, Any]:
    try:
        return add_vector_field(layer_id, body.name, body.default)
    except Exception as exc:
        raise _http_err(exc) from exc


@router.delete(
    "/import/layers/{layer_id}/fields/{name}",
    dependencies=[Depends(require_write_access)],
)
async def vector_field_delete(layer_id: str, name: str) -> dict[str, Any]:
    try:
        return delete_vector_field(layer_id, name)
    except Exception as exc:
        raise _http_err(exc) from exc


@router.post(
    "/import/layers/{layer_id}/rename-field",
    dependencies=[Depends(require_write_access)],
)
async def vector_rename_field(layer_id: str, body: VectorRenameBody) -> dict[str, Any]:
    try:
        return rename_vector_field(layer_id, body.old_name, body.new_name)
    except Exception as exc:
        raise _http_err(exc) from exc


@router.delete(
    "/import/layers/{layer_id}", dependencies=[Depends(require_write_access)]
)
async def delete_imported_layer(layer_id: str) -> dict[str, Any]:
    """删除已导入矢量/栅格落盘目录（仅允许 imported-* 前缀）。"""
    safe = Path(layer_id).name
    if safe != layer_id or ".." in layer_id or "/" in layer_id or "\\" in layer_id:
        raise HTTPException(status_code=400, detail="非法 layer_id")
    if not (safe.startswith("imported-") or safe.startswith("imported_")):
        if not safe.startswith("imported"):
            raise HTTPException(status_code=400, detail="仅允许删除导入图层")
    dest = import_paths.IMPORTS_DIR / safe
    if not dest.exists() or not dest.is_dir():
        raise HTTPException(status_code=404, detail=f"图层不存在: {safe}")
    if safe.startswith("_"):
        raise HTTPException(status_code=400, detail="禁止删除系统目录")
    try:
        from app.services.overlay_registry import unregister_overlay

        unregister_overlay(safe)
    except Exception:
        pass
    shutil.rmtree(dest, ignore_errors=True)
    return {"ok": True, "layer_id": safe}


# ── 科学栅格 ───────────────────────────────────────────────────────────


@router.post("/import/raster/inspect", dependencies=[Depends(require_write_access)])
async def raster_inspect(body: RasterInspectBody) -> dict[str, Any]:
    try:
        path = resolve_upload_path(body.upload_id)
        info = list_raster_variables(path)
        return {"upload_id": body.upload_id, "filename": path.name, **info}
    except Exception as exc:
        raise _http_err(exc) from exc


@router.post("/import/raster/commit", dependencies=[Depends(require_write_access)])
async def raster_commit(body: RasterCommitBody) -> dict[str, Any]:
    try:
        path = resolve_upload_path(body.upload_id)
        ext = path.suffix.lower()
        # 科学格式默认偏异步，避免大 MAT 同步抽取导致代理 502
        force_async = (
            body.async_mode
            or path.stat().st_size > import_paths.CHUNK_SYNC_THRESHOLD_BYTES
        )
        if (
            ext in {".mat", ".nc", ".hdf", ".h5", ".he5"}
            and path.stat().st_size > 8 * 1024 * 1024
        ):
            force_async = True
        if force_async:
            job = enqueue_job(
                "raster_commit",
                {
                    "path": str(path),
                    "upload_id": body.upload_id,
                    "variable_id": body.variable_id,
                    "variable_ids": body.variable_ids,
                    "time_index": body.time_index,
                    "source_name": body.source_name or path.name,
                    "source_crs": body.source_crs,
                    "grid_preset": body.grid_preset,
                    "bounds": body.bounds,
                    "invalid_values": body.invalid_values,
                    "nodata": body.nodata,
                    "auto_confirm": body.auto_confirm,
                    "lng_offset": body.lng_offset,
                    "lat_offset": body.lat_offset,
                },
                force_async=True,
            )
            return {"async": True, "job_id": job["job_id"], "status": job["status"]}
        return {"async": False, **_raster_commit_sync(body)}
    except Exception as exc:
        raise _http_err(exc) from exc


# ── 文档 ───────────────────────────────────────────────────────────────


@router.post("/import/document", dependencies=[Depends(require_write_access)])
async def import_document(body: RasterInspectBody) -> dict[str, Any]:
    """复用 upload_id 字段打开文档会话。"""
    try:
        path = resolve_upload_path(body.upload_id)
        return create_document_session(path, source_name=path.name)
    except Exception as exc:
        raise _http_err(exc) from exc


@router.post("/import/document/multipart", dependencies=[Depends(require_write_access)])
async def import_document_multipart(file: UploadFile = File(...)) -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix="doc-upload-"))
    try:
        name = Path(file.filename or "table.csv").name
        dest = tmp / name
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        return create_document_session(dest, source_name=name)
    except Exception as exc:
        raise _http_err(exc) from exc
    finally:
        await file.close()
        shutil.rmtree(tmp, ignore_errors=True)


@router.get(
    "/import/document/{session_id}", dependencies=[Depends(require_write_access)]
)
async def document_preview(session_id: str) -> dict[str, Any]:
    try:
        return preview_document_session(session_id)
    except Exception as exc:
        raise _http_err(exc, not_found=True) from exc


@router.post(
    "/import/document/{session_id}/ops", dependencies=[Depends(require_write_access)]
)
async def document_ops(session_id: str, body: DocumentOpsBody) -> dict[str, Any]:
    try:
        return apply_document_ops(session_id, body.ops)
    except Exception as exc:
        raise _http_err(exc) from exc


@router.post(
    "/import/document/{session_id}/commit", dependencies=[Depends(require_write_access)]
)
async def document_commit(session_id: str, body: DocumentCommitBody) -> dict[str, Any]:
    try:
        payload = {
            "session_id": session_id,
            "x_field": body.x_field,
            "y_field": body.y_field,
            "source_crs": body.source_crs,
            "target_crs": body.target_crs,
            "lng_offset": body.lng_offset,
            "lat_offset": body.lat_offset,
        }
        if body.async_mode:
            job = enqueue_job("document_commit", payload, force_async=True)
            return {"async": True, "job_id": job["job_id"], "status": job["status"]}
        result = commit_document_session(
            session_id,
            x_field=body.x_field,
            y_field=body.y_field,
            source_crs=body.source_crs,
            target_crs=body.target_crs,
            lng_offset=body.lng_offset,
            lat_offset=body.lat_offset,
        )
        return {"async": False, **result}
    except Exception as exc:
        raise _http_err(exc) from exc


# ── 导出 ───────────────────────────────────────────────────────────────


@router.get("/export/encodings", dependencies=[Depends(require_write_access)])
async def export_encodings_endpoint() -> dict[str, Any]:
    return {"encodings": list_export_encodings()}


@router.post("/export/layer", dependencies=[Depends(require_write_access)])
async def export_layer_endpoint(body: ExportBody) -> Response:
    try:
        content, media_type, filename = export_layer(
            body.layer_id,
            body.format,
            encoding=body.encoding,
        )
    except Exception as exc:
        raise _http_err(exc) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers=content_disposition_attachment(filename),
    )


@router.post("/export/batch", dependencies=[Depends(require_write_access)])
async def export_batch_endpoint(body: ExportBatchBody) -> Response:
    if not body.layer_ids:
        raise HTTPException(status_code=400, detail="layer_ids 不能为空")
    force_async = body.async_mode or len(body.layer_ids) > 2
    try:
        if force_async:
            job = enqueue_job(
                "export_batch",
                {
                    "layer_ids": body.layer_ids,
                    "format": body.format,
                    "encoding": body.encoding,
                },
                force_async=True,
            )
            return Response(
                content=json.dumps(
                    {"job_id": job["job_id"], "status": job["status"], "async": True},
                    ensure_ascii=False,
                ),
                media_type="application/json",
            )
        result = export_layers_batch_zip(
            body.layer_ids,
            format=body.format,
            encoding=body.encoding,
        )
        path = Path(str(result["download_path"]))
        return FileResponse(
            path,
            media_type="application/zip",
            filename=str(result.get("filename") or path.name),
        )
    except Exception as exc:
        raise _http_err(exc) from exc
