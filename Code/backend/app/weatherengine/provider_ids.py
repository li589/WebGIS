"""Canonical weather provider IDs and legacy aliases."""

from __future__ import annotations

import os

OPEN_METEO_ONLINE_ID = "open-meteo-online"
OPEN_METEO_LOCAL_ID = "open-meteo-local"
# Legacy single-ID used before online/local split
OPEN_METEO_LEGACY_ID = "open-meteo"

PROVIDER_ID_ALIASES: dict[str, str] = {
    OPEN_METEO_LEGACY_ID: OPEN_METEO_ONLINE_ID,
}

OPEN_METEO_ONLINE_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_LOCAL_URL = "http://127.0.0.1:8080/v1/forecast"

# Self-hosted Open-Meteo only syncs concrete domains (no best_match ensemble).
# Override with BACKEND_OPEN_METEO_LOCAL_MODEL if sync uses another domain.
OPEN_METEO_LOCAL_DEFAULT_MODEL = (
    os.getenv("BACKEND_OPEN_METEO_LOCAL_MODEL", "ecmwf_ifs025").strip() or "ecmwf_ifs025"
)
_LOCAL_ENSEMBLE_ALIASES = frozenset({"best_match", "auto", ""})


def normalize_provider_id(provider_id: str | None) -> str | None:
    """Normalize provider id; map legacy ``open-meteo`` → ``open-meteo-online``."""
    if provider_id is None:
        return None
    pid = str(provider_id).strip()
    if not pid:
        return None
    return PROVIDER_ID_ALIASES.get(pid, pid)


def resolve_open_meteo_model(model: str | None, *, provider_id: str | None = None) -> str:
    """Map ensemble aliases to a concrete domain for self-hosted Open-Meteo.

    Public API accepts ``best_match``; Docker local only has synced domains
    (typically ``ecmwf_ifs025``). Requesting ``best_match`` locally returns
    HTTP 200 with all-null hourly values — blank map tiles.
    """
    resolved = (model or "best_match").strip() or "best_match"
    pid = normalize_provider_id(provider_id) or provider_id
    if pid == OPEN_METEO_LOCAL_ID and resolved in _LOCAL_ENSEMBLE_ALIASES:
        return OPEN_METEO_LOCAL_DEFAULT_MODEL
    return resolved


def provider_grid_mode(provider_id: str) -> str:
    """dense = native multi-point grid; sparse = point-sampled commercial grids."""
    pid = normalize_provider_id(provider_id) or provider_id
    if pid.startswith("open-meteo"):
        return "dense"
    return "sparse"
