from pathlib import Path
import tempfile

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse

from app.api.deps import CredentialContext, get_request_user
from app.api.error_codes import AUTH_ERROR, ApiError
from app.core import config
from app.services.raster_preview_service import raster_preview_service
from app.services.result_storage import result_storage_service
import contextlib

router = APIRouter()


def _deny_if_unauthenticated(cred: CredentialContext | None) -> None:
    if cred is None and config.settings.user_auth_enabled:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )


def _deny_if_not_artifact_owner(
    artifact_run_id: str | None, cred: CredentialContext | None
) -> None:
    """Check that the caller may access this artifact's owning run.

    Mirrors ``workflow_router._deny_if_not_run_owner``: admin and
    service_key/dev_bypass callers pass; authenticated non-admin users
    must own the run; anonymous callers fail closed when auth is on.
    """
    if cred is None:
        if config.settings.user_auth_enabled:
            raise ApiError(
                AUTH_ERROR,
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        return
    if cred.role == "admin":
        return
    if cred.user_id is None:
        if cred.source in {"service_key", "dev_bypass"}:
            return
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found.",
        )
    if artifact_run_id is None:
        # Legacy artifact without run_id metadata: restrict to admin / service_key / dev_bypass.
        # Authenticated non-admin users cannot access artifacts with no ownership provenance.
        if cred.source in {"service_key", "dev_bypass"}:
            return
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found.",
        )
    from app.services.workflow_repository import SQLiteWorkflowRepository

    owner = SQLiteWorkflowRepository().get_run_user_id(artifact_run_id)
    if owner is None or owner != cred.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found.",
        )


@router.get("/artifacts/{artifact_id}", tags=["artifacts"])
def get_artifact(
    artifact_id: str,
    cred: CredentialContext | None = Depends(get_request_user),
):
    _deny_if_unauthenticated(cred)
    artifact = result_storage_service.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact not found: {artifact_id}",
        )
    _deny_if_not_artifact_owner(artifact.run_id, cred)
    if artifact.file_path is not None and artifact.file_path.exists():
        return FileResponse(
            path=artifact.file_path,
            media_type=artifact.mime_type,
            filename=artifact.file_path.name,
        )
    # MinIO 存储：直接读取数据返回，避免 307 重定向导致浏览器直连 MinIO 跨域
    data = result_storage_service.fetch_artifact_bytes(artifact_id)
    if data is not None:
        return Response(content=data, media_type=artifact.mime_type)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Artifact is unavailable: {artifact_id}",
    )


@router.get("/artifacts/{artifact_id}/preview.png", tags=["artifacts"])
def get_artifact_preview_png(
    artifact_id: str,
    palette: str = "thermal-orange",
    width: int = Query(default=768, ge=64, le=4096),
    height: int = Query(default=768, ge=64, le=4096),
    min_value: float | None = None,
    max_value: float | None = None,
    cred: CredentialContext | None = Depends(get_request_user),
):
    _deny_if_unauthenticated(cred)
    artifact = result_storage_service.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact not found: {artifact_id}",
        )
    _deny_if_not_artifact_owner(artifact.run_id, cred)
    if artifact.mime_type != "image/tiff":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Artifact is not a TIFF/COG: {artifact_id}",
        )

    # 本地存储：file_path 直接可用；MinIO：file_path=None，回退到 fetch_bytes + 临时文件
    cog_path = artifact.file_path
    temp_path: Path | None = None
    if cog_path is None or not cog_path.exists():
        raw_bytes = result_storage_service.fetch_artifact_bytes(artifact_id)
        if raw_bytes is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact bytes not found: {artifact_id}",
            )
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".tif",
            prefix=f"preview_{artifact_id}_",
            delete=False,
        ) as temp_file:
            temp_file.write(raw_bytes)
            temp_path = Path(temp_file.name)
        cog_path = temp_path

    try:
        png_bytes = raster_preview_service.render_cog_preview(
            cog_path=cog_path,
            palette=palette,
            width=width,
            height=height,
            min_value=min_value,
            max_value=max_value,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)
        ) from exc
    finally:
        if temp_path is not None and temp_path.exists():
            with contextlib.suppress(OSError):
                temp_path.unlink()
    return Response(content=png_bytes, media_type="image/png")
