"""Shared download limits for remote transports."""

from __future__ import annotations

import os

DEFAULT_MAX_REMOTE_BYTES = 512 * 1024 * 1024  # 512 MiB
DEFAULT_CONNECT_TIMEOUT = 30.0


def get_max_remote_bytes(default: int = DEFAULT_MAX_REMOTE_BYTES) -> int:
    """Resolve max download size from BACKEND_REMOTE_MAX_BYTES (bytes).

    Real geo products (HDF5 / GeoTIFF / NetCDF) often exceed 512 MiB; raise via env
    on NAS e2e hosts. Invalid values fall back to ``default``.
    """
    raw = os.getenv("BACKEND_REMOTE_MAX_BYTES", "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default
