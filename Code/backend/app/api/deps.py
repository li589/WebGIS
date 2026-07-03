from __future__ import annotations

import logging
import secrets

from fastapi import Header, HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger(__name__)

# Permitted module name prefixes for dynamic algorithm loading (P0-3 defence).
ALLOWED_ALGORITHM_PREFIXES: tuple[str, ...] = ("algorithms.",)


def require_write_access(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce API-key authentication for write endpoints.

    When ``api_keys_enabled`` is True the key is always required.
    When False we allow an unauthenticated bypass ONLY in development
    (and only when no key is configured at all), but a configured key
    is still honoured even when the flag is False.
    """
    if not settings.api_keys_enabled and settings.environment == "development":
        # Dev-only escape hatch — warn so operators notice it in logs.
        logger.warning(
            "API-key authentication is disabled for write endpoints "
            "(api_keys_enabled=False, environment=development). "
            "Do NOT use this configuration in production."
        )
        return

    configured_key = settings.api_key
    if not configured_key:
        # Key not configured at all — fail closed.
        logger.error(
            "API key is not configured but api_keys_enabled=True. "
            "Rejecting write request to prevent unauthenticated access."
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
