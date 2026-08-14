from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.api.error_codes import AUTH_ERROR, ApiError
from app.core import config
from app.services.credential_resolver import (
    CredentialContext,
    allows_sensitive_read,
    allows_write,
    can_create_workflow,
    can_data_transfer,
    can_manage_config,
    can_run_workflow,
    resolve_credential,
)

logger = logging.getLogger(__name__)

ALLOWED_ALGORITHM_PREFIXES: tuple[str, ...] = ("algorithms.",)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def session_cookie_secure() -> bool:
    env = (config.settings.environment or "").lower()
    return env not in {"development", "dev", "test", "testing"}


def resolve_request_credential(
    request: Request,
    x_api_key: str | None = Security(_api_key_header),
) -> CredentialContext | None:
    return resolve_credential(request, x_api_key)


def get_request_user(
    request: Request,
    x_api_key: str | None = Security(_api_key_header),
) -> CredentialContext | None:
    """Resolve and return the credential context for the current request.

    Phase C: Used by workflow_router to pass ``user_id`` and ``role`` to
    ``submission_service.submit_workflow`` for per-user concurrency control.
    """
    return resolve_credential(request, x_api_key)


def require_session(request: Request) -> CredentialContext:
    if not config.settings.user_auth_enabled:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User login is disabled on this server.",
        )
    ctx = resolve_credential(request, None)
    if ctx is None or ctx.source != "session":
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return ctx


def require_admin(
    ctx: CredentialContext = Depends(require_session),
) -> CredentialContext:
    if ctx.role != "admin":
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
    return ctx


def require_write_access(
    request: Request,
    x_api_key: str | None = Security(_api_key_header),
) -> None:
    """Enforce RBAC for write endpoints via session, user token, or service key."""
    ctx = resolve_credential(request, x_api_key)
    if ctx is not None and allows_write(ctx):
        return
    if ctx is not None and ctx.role == "demo":
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo account cannot perform write operations.",
        )
    if ctx is not None:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this operation.",
        )

    if (
        not config.settings.api_keys_enabled
        and config.settings.environment == "development"
    ):
        from app.services.credential_resolver import dev_bypass_allowed

        if dev_bypass_allowed(request):
            return

    from app.services.effective_config import get_backend_auth_key

    configured_key = get_backend_auth_key() or ""
    if not configured_key and not config.settings.api_keys_enabled:
        logger.error("API key is not configured; rejecting write request.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key not configured on the server.",
        )

    raise ApiError(
        AUTH_ERROR,
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


def require_workflow_run_access(
    request: Request,
    x_api_key: str | None = Security(_api_key_header),
) -> None:
    """工作流运行权限：admin + standard + demo（受并发上限约束）。"""
    ctx = resolve_credential(request, x_api_key)
    if ctx is not None and can_run_workflow(ctx):
        return

    if (
        not config.settings.api_keys_enabled
        and config.settings.environment == "development"
    ):
        from app.services.credential_resolver import dev_bypass_allowed

        if dev_bypass_allowed(request):
            return

    if ctx is not None:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to run workflows.",
        )
    raise ApiError(
        AUTH_ERROR,
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


def require_config_read_access(
    request: Request,
    x_api_key: str | None = Security(_api_key_header),
) -> None:
    ctx = resolve_credential(request, x_api_key)
    if ctx is not None and allows_sensitive_read(ctx):
        return
    require_write_access(request, x_api_key)


def require_gee_account_management_enabled() -> None:
    if not config.settings.gee_api_account_management_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="GEE API account management is disabled on this server.",
        )


def require_config_management_access(
    request: Request,
    x_api_key: str | None = Security(_api_key_header),
) -> None:
    """配置管理权限：仅 admin 可写配置（API Key / GEE / 天气 / 远程存储等）。"""
    ctx = resolve_credential(request, x_api_key)
    if ctx is not None and can_manage_config(ctx):
        return
    if ctx is not None:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required for configuration management.",
        )
    raise ApiError(
        AUTH_ERROR,
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


def require_workflow_create_access(
    request: Request,
    x_api_key: str | None = Security(_api_key_header),
) -> None:
    """工作流定义创建/修改权限：admin + standard。demo 不可。"""
    ctx = resolve_credential(request, x_api_key)
    if ctx is not None and can_create_workflow(ctx):
        return
    if ctx is not None and ctx.role == "demo":
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo account cannot create or modify workflow definitions.",
        )
    if ctx is not None:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this operation.",
        )
    raise ApiError(
        AUTH_ERROR,
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


def require_data_transfer_access(
    request: Request,
    x_api_key: str | None = Security(_api_key_header),
) -> None:
    """数据上传/下载权限：admin + standard 无限制；demo 受全局开关管控。"""
    ctx = resolve_credential(request, x_api_key)
    if ctx is not None and can_data_transfer(ctx):
        return
    if ctx is not None and ctx.role == "demo":
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Data transfer is not enabled for demo accounts. "
            "Contact an administrator.",
        )
    if ctx is not None:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for data transfer.",
        )
    raise ApiError(
        AUTH_ERROR,
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


# ---------------------------------------------------------------------------
# Phase B: Resource-level access control
# ---------------------------------------------------------------------------


def check_resource_access(
    ctx: CredentialContext | None,
    resource_type: str,
    resource_id: str,
) -> None:
    """Raise 401/403 if the user lacks access to ``resource_type/resource_id``.

    *admin* always bypasses. When user auth is enabled, unauthenticated
    callers (``ctx is None``) fail closed with 401 — overlay/tile routes
    must not enumerate protected layers anonymously.

    When user auth is disabled, ``ctx is None`` is allowed (legacy open mode).

    Authenticated principals without ``user_id`` only bypass when they are
    infrastructure sources (``service_key`` / ``dev_bypass``). Session or
    user-token contexts with a missing ``user_id`` fail closed.
    """
    if ctx is None:
        if config.settings.user_auth_enabled:
            raise ApiError(
                AUTH_ERROR,
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        return
    if ctx.role == "admin":
        return
    if ctx.user_id is None:
        if ctx.source in {"service_key", "dev_bypass"}:
            return
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Resource access denied. Contact an administrator.",
        )
    from app.services.permission_repository import get_permission_repository

    repo = get_permission_repository()
    if not repo.check_resource_access(int(ctx.user_id), resource_type, resource_id):
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Resource access denied. Contact an administrator.",
        )
