"""Build GLDAS UTC overpass template MAT used by DUAL ``use_gldas_template``.

Matlab CFG points at ``gldas_utc_template_global.mat`` containing containers
``SMAP_template`` / ``FY3D_template`` / ``FY3B_template``, each with:

- ``slot_index`` (1-based index into the day's 3-hourly GLDAS slots)
- ``slot_day_offset`` (day offset from the query date)

This module synthesizes those grids from ``lon_9km`` + descending local hour,
matching ``local_overpass_to_utc_vec`` in ``daily_bundle``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ingest.mat_bundle import load_mat_file

logger = logging.getLogger(__name__)

# GLDAS NOAH025_3H UTC slot hours (8 / day)
_GLDAS_SLOT_HOURS: tuple[float, ...] = (0.0, 3.0, 6.0, 9.0, 12.0, 15.0, 18.0, 21.0)

_DEFAULT_LOCAL_HOURS: dict[str, float] = {
    "SMAP": 6.0,
    "FY3D": 2.0,
    "FY3B": 1.6666666666666667,
}


@dataclass(frozen=True, slots=True)
class GldasTemplateBuildResult:
    output_path: str
    nrows: int
    ncols: int
    containers: tuple[str, ...]


def _load_lon_grid(ancillary_mat: str | Path) -> Any:
    import numpy as np

    payload = load_mat_file(Path(ancillary_mat))
    lon = None
    for key in ("lon_9km", "lon", "longitude"):
        if key in payload:
            lon = payload[key]
            break
    if lon is None:
        raise KeyError(f"lon grid not found in {ancillary_mat}")
    lon_arr = np.asarray(lon, dtype=np.float64)
    if lon_arr.ndim != 2:
        raise ValueError(f"lon grid must be 2D, got shape={lon_arr.shape}")
    return lon_arr


def utc_to_slot_index_and_day_offset(
    utc: datetime,
    base_day: datetime,
    *,
    slot_hours: tuple[float, ...] = _GLDAS_SLOT_HOURS,
) -> tuple[int, int]:
    """Map a UTC instant to (1-based slot_index, day_offset) vs ``base_day``."""
    best: tuple[float, int, int] | None = None  # (abs_hours, slot_1based, day_offset)
    for day_offset in (-1, 0, 1):
        day = base_day + timedelta(days=day_offset)
        for slot_pos, hour in enumerate(slot_hours):
            slot_dt = day + timedelta(hours=float(hour))
            delta_h = abs((slot_dt - utc).total_seconds()) / 3600.0
            candidate = (delta_h, slot_pos + 1, day_offset)
            if best is None or candidate[0] < best[0]:
                best = candidate
    assert best is not None
    return best[1], best[2]


def build_slot_maps_for_local_hour(
    lon_grid: Any,
    local_hour: float,
    *,
    reference_day: datetime | None = None,
) -> tuple[Any, Any]:
    """Return ``(slot_index, slot_day_offset)`` 2D float arrays (vectorized)."""
    import numpy as np

    lon_arr = np.asarray(lon_grid, dtype=np.float64)
    base_day = reference_day or datetime(2025, 1, 1)
    base_day = datetime(base_day.year, base_day.month, base_day.day)
    base_epoch = base_day.timestamp()

    utc_hours = float(local_hour) - lon_arr / 15.0
    # Candidate slots: day_offset ∈ {-1,0,1} × 8 slot hours → 24 candidates
    cand_offsets = np.array([-1, 0, 1], dtype=np.float64)
    cand_hours = np.asarray(_GLDAS_SLOT_HOURS, dtype=np.float64)
    # Shape (3, 8)
    cand_abs_hours = cand_offsets[:, None] * 24.0 + cand_hours[None, :]
    # Broadcast vs utc_hours → (nrow, ncol, 3, 8)
    delta = np.abs(cand_abs_hours[None, None, :, :] - utc_hours[:, :, None, None])
    flat = delta.reshape(*lon_arr.shape, -1)
    best = np.nanargmin(
        np.where(np.isfinite(lon_arr)[:, :, None], flat, np.inf), axis=-1
    )
    # Decode: best = day_i * 8 + slot_i
    day_i = best // len(_GLDAS_SLOT_HOURS)
    slot_i = best % len(_GLDAS_SLOT_HOURS)
    slot_index = (slot_i + 1).astype(np.float64)
    day_offset = cand_offsets[day_i]
    invalid = ~np.isfinite(lon_arr)
    slot_index[invalid] = np.nan
    day_offset = day_offset.astype(np.float64)
    day_offset[invalid] = np.nan
    _ = base_epoch  # keep API parity / future absolute-time uses
    return slot_index, day_offset


def build_gldas_utc_template(
    *,
    ancillary_mat: str | Path,
    output_path: str | Path,
    local_hours: dict[str, float] | None = None,
    reference_day: datetime | None = None,
) -> GldasTemplateBuildResult:
    """Write ``gldas_utc_template_global.mat`` compatible with Matlab D2/D1."""
    from scipy.io import savemat

    hours = dict(_DEFAULT_LOCAL_HOURS)
    if local_hours:
        hours.update({str(k).upper(): float(v) for k, v in local_hours.items()})

    lon_grid = _load_lon_grid(ancillary_mat)
    payload: dict[str, Any] = {}
    containers: list[str] = []
    for name, local_hour in (
        ("SMAP_template", hours["SMAP"]),
        ("FY3D_template", hours["FY3D"]),
        ("FY3B_template", hours["FY3B"]),
    ):
        slot_index, slot_day_offset = build_slot_maps_for_local_hour(
            lon_grid, local_hour, reference_day=reference_day
        )
        payload[name] = {
            "slot_index": slot_index,
            "slot_day_offset": slot_day_offset,
        }
        containers.append(name)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    savemat(out, payload, do_compression=True)
    logger.info(
        "Wrote GLDAS UTC template %s (%dx%d) containers=%s",
        out,
        lon_grid.shape[0],
        lon_grid.shape[1],
        containers,
    )
    return GldasTemplateBuildResult(
        output_path=str(out),
        nrows=int(lon_grid.shape[0]),
        ncols=int(lon_grid.shape[1]),
        containers=tuple(containers),
    )


def default_template_path(data_root: str | Path) -> Path:
    return (
        Path(data_root)
        / "Meteorological"
        / "Weather"
        / "GLDAS_UTC_TEMPLATE"
        / "gldas_utc_template_global.mat"
    )


def ensure_gldas_utc_template(
    *,
    data_root: str | Path,
    ancillary_mat: str | Path | None = None,
    force: bool = False,
) -> Path:
    """Ensure template MAT exists under DATA_ROOT; build if missing."""
    out = default_template_path(data_root)
    if out.is_file() and not force:
        return out
    anc = (
        Path(ancillary_mat)
        if ancillary_mat
        else Path(data_root)
        / "Soil_Moisture"
        / "SMAP_Auxiliary_Data"
        / "IGBP_9km_12.mat"
    )
    if not anc.is_file():
        raise FileNotFoundError(f"ancillary mat required to build template: {anc}")
    build_gldas_utc_template(ancillary_mat=anc, output_path=out)
    return out
