"""Per-user workspace snapshot sync (cross-device layer workspace).

GET  /workspace        → { revision, updated_at, payload | null }
PUT  /workspace        → 乐观并发保存（base_revision 不符返回 409 + 服务端现状）
DELETE /workspace      → 清空（登出异地设备时可选清理）

payload 为前端契约（version/snapshot/dismissed），服务端只做体量与结构下限校验。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.api.deps import require_session
from app.api.error_codes import AUTH_ERROR, CONFLICT_ERROR, ApiError
from app.services.credential_resolver import CredentialContext
from app.services.user_workspace_store import (
    WorkspaceConflictError,
    WorkspacePayloadTooLargeError,
    get_user_workspace_store,
)

router = APIRouter(prefix="/workspace", tags=["workspace"])


class WorkspacePayloadModel(BaseModel):
    version: int = Field(ge=1, le=1)
    snapshot: dict[str, Any]
    dismissed: dict[str, Any] | None = None


class WorkspaceGetResponse(BaseModel):
    revision: int
    updated_at: str | None = None
    payload: WorkspacePayloadModel | None = None


class WorkspacePutRequest(BaseModel):
    payload: WorkspacePayloadModel
    base_revision: int | None = None


class WorkspacePutResponse(BaseModel):
    revision: int
    updated_at: str


def _require_user_id(ctx: CredentialContext) -> int:
    if ctx.user_id is None:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace sync requires a logged-in user account.",
        )
    return int(ctx.user_id)


@router.get("", response_model=WorkspaceGetResponse)
def get_workspace(
    ctx: CredentialContext = Depends(require_session),
) -> WorkspaceGetResponse:
    record = get_user_workspace_store().get(_require_user_id(ctx))
    payload = None
    if record.payload is not None:
        payload = WorkspacePayloadModel.model_validate(record.payload)
    return WorkspaceGetResponse(
        revision=record.revision,
        updated_at=record.updated_at or None,
        payload=payload,
    )


@router.put("", response_model=WorkspacePutResponse)
def put_workspace(
    req: WorkspacePutRequest,
    ctx: CredentialContext = Depends(require_session),
) -> WorkspacePutResponse:
    if ctx.role == "demo":
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo account cannot sync workspace.",
        )
    user_id = _require_user_id(ctx)
    try:
        record = get_user_workspace_store().put(
            user_id, req.payload.model_dump(), req.base_revision
        )
    except WorkspaceConflictError as exc:
        raise ApiError(
            CONFLICT_ERROR,
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Workspace was updated from another device.",
                "revision": exc.server_revision,
                "updated_at": exc.server_updated_at,
            },
        ) from exc
    except WorkspacePayloadTooLargeError as exc:
        raise ApiError(
            CONFLICT_ERROR,
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc
    return WorkspacePutResponse(revision=record.revision, updated_at=record.updated_at)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(ctx: CredentialContext = Depends(require_session)):
    if ctx.role == "demo":
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo account cannot modify workspace.",
        )
    get_user_workspace_store().delete(_require_user_id(ctx))
