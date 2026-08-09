from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.api.error_codes import AUTH_ERROR, ApiError
from app.core.config import settings
from app.services.credential_resolver import (
    CredentialContext,
    allows_sensitive_read,
    allows_write,
    resolve_credential,
)

logger = logging.getLogger(__name__)

ALLOWED_ALGORITHM_PREFIXES: tuple[str, ...] = ("algorithms.",)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def session_cookie_secure() -> bool:
    env = (settings.environment or "").lower()
    return env not in {"development", "dev", "test", "testing"}


def resolve_request_credential(
    request: Request,
    x_api_key: str | None = Security(_api_key_header),
) -> CredentialContext | None:
    return resolve_credential(request, x_api_key)


def require_session(request: Request) -> CredentialContext:
    if not settings.user_auth_enabled:
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
    if ctx is not None and ctx.role == "viewer":
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Read-only account cannot perform write operations.",
        )
    if ctx is not None:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this operation.",
        )

    if not settings.api_keys_enabled and settings.environment == "development":
        from app.services.credential_resolver import dev_bypass_allowed

        if dev_bypass_allowed(request):
            return

    from app.services.effective_config import get_backend_auth_key

    configured_key = get_backend_auth_key() or ""
    if not configured_key and not settings.api_keys_enabled:
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


def require_config_read_access(
    request: Request,
    x_api_key: str | None = Security(_api_key_header),
) -> None:
    ctx = resolve_credential(request, x_api_key)
    if ctx is not None and allows_sensitive_read(ctx):
        return
    require_write_access(request, x_api_key)


def require_gee_account_management_enabled() -> None:
    if not settings.gee_api_account_management_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="GEE API account management is disabled on this server.",
        )
