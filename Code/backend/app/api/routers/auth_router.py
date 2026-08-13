"""User login, session cookies, account management, and API tokens."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import require_admin, require_session, session_cookie_secure
from app.api.error_codes import AUTH_ERROR, ApiError
from app.services.credential_resolver import LOOPBACK_IPS
from app.core.config import settings
from app.services import session_service
from app.services.auth_bootstrap import (
    DEV_DEFAULT_ADMIN_PASSWORD,
    DEV_DEFAULT_ADMIN_USER,
    DEV_DEFAULT_API_KEY,
)
from app.services.credential_resolver import CredentialContext
from app.services.user_repository import VALID_ROLES, get_user_repository
from app.services.user_token_repository import get_user_token_repository
from app.services.permission_repository import (
    PermissionInput,
    get_permission_repository,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthConfigResponse(BaseModel):
    auth_required: bool
    session_cookie_name: str
    roles: list[str] = Field(default_factory=lambda: sorted(VALID_ROLES))
    dev_prefill: dict[str, str] | None = None
    dev_write_api_key: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class UserPublic(BaseModel):
    id: int
    username: str
    role: Literal["admin", "standard", "demo"]
    enabled: bool = True
    permission_mode: str = "open"


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    role: Literal["admin", "standard", "demo"] = "standard"


class UpdateUserRequest(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=256)
    role: Literal["admin", "standard", "demo"] | None = None
    enabled: bool | None = None


class CreateTokenRequest(BaseModel):
    label: str | None = Field(default=None, max_length=128)
    user_id: int | None = None


class TokenCreatedResponse(BaseModel):
    id: int
    user_id: int
    username: str
    label: str | None
    token: str
    created_at: str


class TokenPublic(BaseModel):
    id: int
    user_id: int
    username: str
    label: str | None
    created_at: str
    expires_at: str | None = None


def _public_user(row: dict) -> UserPublic:
    return UserPublic(
        id=int(row["id"]),
        username=str(row["username"]),
        role=str(row["role"]),  # type: ignore[arg-type]
        enabled=bool(row.get("enabled", 1)),
        permission_mode=str(row.get("permission_mode", "open")),
    )


def _direct_client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, token: str) -> None:
    max_age = max(300, int(settings.session_ttl_hours) * 3600)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=session_cookie_secure(),
        samesite="lax",
        max_age=max_age,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=session_cookie_secure(),
        samesite="lax",
    )


def _ensure_not_last_admin(user_id: int, new_role: str | None, disabling: bool) -> None:
    repo = get_user_repository()
    user = repo.get_by_id(user_id)
    if not user or str(user["role"]) != "admin":
        return
    if repo.count_admins() <= 1 and (disabling or new_role in {"standard", "demo"}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove or demote the last admin account.",
        )


@router.get("/config", response_model=AuthConfigResponse)
def get_auth_config(request: Request) -> AuthConfigResponse:
    dev_prefill = None
    dev_write_key = None
    env = (settings.environment or "").lower()
    loopback = _direct_client_host(request) in LOOPBACK_IPS
    if env in {"development", "dev"} and settings.dev_auth_prefill and loopback:
        username = (settings.admin_username or "").strip() or DEV_DEFAULT_ADMIN_USER
        password = settings.admin_password or DEV_DEFAULT_ADMIN_PASSWORD
        dev_prefill = {"username": username, "password": password}
        dev_write_key = (settings.dev_default_api_key or DEV_DEFAULT_API_KEY).strip()
    return AuthConfigResponse(
        auth_required=settings.user_auth_enabled,
        session_cookie_name=settings.session_cookie_name,
        dev_prefill=dev_prefill,
        dev_write_api_key=dev_write_key,
    )


@router.post("/login", response_model=UserPublic)
def login(body: LoginRequest, response: Response) -> UserPublic:
    if not settings.user_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User login is disabled on this server.",
        )
    user = get_user_repository().verify_credentials(body.username, body.password)
    if user is None:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    token = session_service.create_session(
        user_id=int(user["id"]),
        username=str(user["username"]),
        role=str(user["role"]),
    )
    _set_session_cookie(response, token)
    return _public_user(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    _ctx: CredentialContext = Depends(require_session),
) -> Response:
    token = request.cookies.get(settings.session_cookie_name)
    session_service.revoke_session(token)
    _clear_session_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserPublic)
def me(ctx: CredentialContext = Depends(require_session)) -> UserPublic:
    user = get_user_repository().get_by_id(int(ctx.user_id))
    if user is None or not user.get("enabled"):
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired.",
        )
    return _public_user(user)


@router.get("/users")
def list_users(_admin: CredentialContext = Depends(require_admin)) -> list[UserPublic]:
    rows = get_user_repository().list_users()
    return [_public_user(r) for r in rows]


@router.post("/users", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def create_user(
    body: CreateUserRequest, _admin: CredentialContext = Depends(require_admin)
) -> UserPublic:
    try:
        user = get_user_repository().create_user(
            username=body.username,
            password=body.password,
            role=body.role,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _public_user(user)


@router.patch("/users/{user_id}", response_model=UserPublic)
def update_user(
    user_id: int,
    body: UpdateUserRequest,
    admin: CredentialContext = Depends(require_admin),
) -> UserPublic:
    if user_id == int(admin.user_id):
        if body.enabled is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot disable your own account.",
            )
        if body.role is not None and body.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change your own role.",
            )
    _ensure_not_last_admin(user_id, body.role, body.enabled is False)
    try:
        user = get_user_repository().update_user(
            user_id,
            password=body.password,
            role=body.role,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    if body.password is not None or body.enabled is False or body.role is not None:
        session_service.revoke_sessions_for_user(user_id)
    return _public_user(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int, admin: CredentialContext = Depends(require_admin)
) -> Response:
    if user_id == int(admin.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account.",
        )
    _ensure_not_last_admin(user_id, "demo", True)
    if not get_user_repository().delete_user(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    session_service.revoke_sessions_for_user(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tokens", response_model=list[TokenPublic])
def list_tokens(ctx: CredentialContext = Depends(require_session)) -> list[TokenPublic]:
    token_repo = get_user_token_repository()
    user_repo = get_user_repository()
    if ctx.role == "admin":
        rows = token_repo.list_all_active_tokens()
    else:
        rows = token_repo.list_tokens_for_user(int(ctx.user_id))
        rows = [{**r, "username": ctx.username or ""} for r in rows]
    result: list[TokenPublic] = []
    for row in rows:
        uid = int(row["user_id"])
        username = str(row.get("username") or "")
        if not username:
            u = user_repo.get_by_id(uid)
            username = str(u["username"]) if u else ""
        result.append(
            TokenPublic(
                id=int(row["id"]),
                user_id=uid,
                username=username,
                label=row.get("label"),
                created_at=str(row["created_at"]),
                expires_at=row.get("expires_at"),
            )
        )
    return result


@router.post(
    "/tokens", response_model=TokenCreatedResponse, status_code=status.HTTP_201_CREATED
)
def create_token(
    body: CreateTokenRequest,
    ctx: CredentialContext = Depends(require_session),
) -> TokenCreatedResponse:
    target_user_id = body.user_id if body.user_id is not None else int(ctx.user_id)
    if target_user_id != int(ctx.user_id) and ctx.role != "admin":
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
    user = get_user_repository().get_by_id(target_user_id)
    if user is None or not user.get("enabled"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    token_id, plain, created_at = get_user_token_repository().create_token(
        user_id=target_user_id,
        label=body.label,
    )
    return TokenCreatedResponse(
        id=token_id,
        user_id=target_user_id,
        username=str(user["username"]),
        label=body.label,
        token=plain,
        created_at=created_at,
    )


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(
    token_id: int,
    ctx: CredentialContext = Depends(require_session),
) -> Response:
    token_repo = get_user_token_repository()
    rows = (
        token_repo.list_all_active_tokens()
        if ctx.role == "admin"
        else token_repo.list_tokens_for_user(int(ctx.user_id))
    )
    owned = next((r for r in rows if int(r["id"]) == token_id), None)
    if owned is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Token not found."
        )
    if ctx.role != "admin" and int(owned["user_id"]) != int(ctx.user_id):
        raise ApiError(
            AUTH_ERROR, status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden."
        )
    if not token_repo.revoke_token(token_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Token not found."
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Phase B: Resource permission management (admin-only)
# ---------------------------------------------------------------------------


class PermissionRecord(BaseModel):
    id: int
    user_id: int
    resource_type: str
    resource_id: str
    permission: str
    created_at: str
    updated_at: str


class PermissionItemInput(BaseModel):
    resource_type: Literal["layer", "workflow", "data_source"]
    resource_id: str = Field(min_length=1, max_length=512)
    permission: Literal["allow", "deny"]


class SetPermissionsRequest(BaseModel):
    permissions: list[PermissionItemInput] = Field(default_factory=list, max_length=500)


class PermissionModeRequest(BaseModel):
    mode: Literal["open", "whitelist"]


def _ensure_target_user_exists(user_id: int) -> None:
    if get_user_repository().get_by_id(user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )


@router.get(
    "/users/{user_id}/permissions",
    response_model=list[PermissionRecord],
)
def list_user_permissions(
    user_id: int,
    _admin: CredentialContext = Depends(require_admin),
) -> list[PermissionRecord]:
    _ensure_target_user_exists(user_id)
    repo = get_permission_repository()
    return [
        PermissionRecord(
            id=p.id,
            user_id=p.user_id,
            resource_type=p.resource_type,
            resource_id=p.resource_id,
            permission=p.permission,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in repo.get_user_permissions(user_id)
    ]


@router.put(
    "/users/{user_id}/permissions",
    response_model=list[PermissionRecord],
)
def set_user_permissions(
    user_id: int,
    body: SetPermissionsRequest,
    _admin: CredentialContext = Depends(require_admin),
) -> list[PermissionRecord]:
    _ensure_target_user_exists(user_id)
    repo = get_permission_repository()
    try:
        records = repo.set_user_permissions(
            user_id,
            [
                PermissionInput(
                    resource_type=p.resource_type,
                    resource_id=p.resource_id,
                    permission=p.permission,
                )
                for p in body.permissions
            ],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return [
        PermissionRecord(
            id=p.id,
            user_id=p.user_id,
            resource_type=p.resource_type,
            resource_id=p.resource_id,
            permission=p.permission,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in records
    ]


@router.delete(
    "/users/{user_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_permission(
    user_id: int,
    permission_id: int,
    _admin: CredentialContext = Depends(require_admin),
) -> Response:
    _ensure_target_user_exists(user_id)
    repo = get_permission_repository()
    # Verify the permission belongs to the specified user
    perms = repo.get_user_permissions(user_id)
    if not any(p.id == permission_id for p in perms):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission record not found for this user.",
        )
    repo.delete_permission(permission_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/users/{user_id}/permission-mode")
def update_permission_mode(
    user_id: int,
    body: PermissionModeRequest,
    _admin: CredentialContext = Depends(require_admin),
) -> dict[str, Any]:
    _ensure_target_user_exists(user_id)
    repo = get_permission_repository()
    repo.set_permission_mode(user_id, body.mode)
    return {"user_id": user_id, "permission_mode": body.mode}
