from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_write_access(x_api_key: str | None = Header(default=None)) -> None:
    configured_api_key = settings.api_key.strip()
    if not configured_api_key:
        return

    if x_api_key is None or not secrets.compare_digest(x_api_key, configured_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
