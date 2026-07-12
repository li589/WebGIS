from pathlib import Path
import tempfile

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse

from app.services.raster_preview_service import raster_preview_service
from app.services.result_storage import result_storage_service

router = APIRouter()


@router.get("/artifacts/{artifact_id}", tags=["artifacts"])
def get_artifact(artifact_id: str):
    artifact = result_storage_service.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact not found: {artifact_id}")
    if artifact.file_path is not None and artifact.file_path.exists():
        return FileResponse(path=artifact.file_path, media_type=artifact.mime_type, filename=artifact.file_path.name)
    # MinIO 存储：直接读取数据返回，避免 307 重定向导致浏览器直连 MinIO 跨域
    data = result_storage_service.fetch_artifact_bytes(artifact_id)
    if data is not None:
        return Response(content=data, media_type=artifact.mime_type)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact is unavailable: {artifact_id}")


@router.get("/artifacts/{artifact_id}/preview.png", tags=["artifacts"])
def get_artifact_preview_png(
    artifact_id: str,
    palette: str = "thermal-orange",
    width: int = 768,
    height: int = 768,
    min_value: float | None = None,
    max_value: float | None = None,
):
    artifact = result_storage_service.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact not found: {artifact_id}")
    if artifact.mime_type != "image/tiff":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Artifact is not a TIFF/COG: {artifact_id}")

    # 本地存储：file_path 直接可用；MinIO：file_path=None，回退到 fetch_bytes + 临时文件
    cog_path = artifact.file_path
    temp_path: Path | None = None
    if cog_path is None or not cog_path.exists():
        raw_bytes = result_storage_service.fetch_artifact_bytes(artifact_id)
        if raw_bytes is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact bytes not found: {artifact_id}")
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
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
    return Response(content=png_bytes, media_type="image/png")
