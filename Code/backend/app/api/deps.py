from __future__ import annotations

import logging
import os
import secrets

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

logger = logging.getLogger(__name__)

# Permitted module name prefixes for dynamic algorithm loading (P0-3 defence).
ALLOWED_ALGORITHM_PREFIXES: tuple[str, ...] = ("algorithms.",)

# OpenAPI security scheme（D-2）：写端点 X-API-Key 鉴权在 OpenAPI 文档中显式声明，
# Swagger UI 出现 Authorize 入口；auto_error=False 保持自定义 401/503 语义。
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_LOOPBACK_IPS = frozenset({"127.0.0.1", "::1", "localhost"})


def _direct_client_host(request: Request) -> str:
    """TCP peer address; unaffected by trust_proxy / X-Forwarded-For."""
    return request.client.host if request.client else "unknown"


def _dev_auth_bypass_explicit() -> bool:
    return os.getenv("BACKEND_DEV_AUTH_BYPASS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def require_write_access(
    request: Request,
    x_api_key: str | None = Security(_api_key_header),
) -> None:
    """Enforce API-key authentication for write endpoints.

    When ``api_keys_enabled`` is True the key is always required.

    Development escape hatch (``api_keys_enabled=False`` + ``environment=development``):
    unauthenticated writes are allowed only from loopback clients, or when
    ``BACKEND_DEV_AUTH_BYPASS=true`` is set explicitly (shared-lab override).
    Remote clients without the flag fall through to normal key checks (fail-closed
    if no key is configured).

    Auth key resolution: env cold-start + DB overlay via EffectiveSecrets
    (``backend_auth``), not Settings alone.
    """
    if not settings.api_keys_enabled and settings.environment == "development":
        direct_host = _direct_client_host(request)
        if _dev_auth_bypass_explicit() or direct_host in _LOOPBACK_IPS:
            logger.warning(
                "API-key authentication bypassed for write endpoints "
                "(api_keys_enabled=False, environment=development, direct_host=%s, "
                "explicit_bypass=%s). Do NOT use this configuration in production.",
                direct_host,
                _dev_auth_bypass_explicit(),
            )
            return
        logger.warning(
            "Development auth bypass denied for non-loopback direct_host=%s; "
            "requiring API key (set BACKEND_DEV_AUTH_BYPASS=true to override).",
            direct_host,
        )

    from app.services.effective_config import get_backend_auth_key

    configured_key = get_backend_auth_key() or ""
    if not configured_key:
        # Key not configured at all — fail closed.
        logger.error(
            "API key is not configured; rejecting write request to prevent "
            "unauthenticated access."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key not configured on the server.",
        )

    if x_api_key is None or not secrets.compare_digest(x_api_key, configured_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )


# Sensitive /config GET surfaces (masked keys, paths, portal/remote metadata).
# Same gate as writes: production needs X-API-Key; development loopback may bypass.
require_config_read_access = require_write_access


def require_gee_account_management_enabled() -> None:
    """Block GEE account mutating APIs when management is disabled."""
    if not settings.gee_api_account_management_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="GEE API account management is disabled on this server.",
        )
