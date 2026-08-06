"""GLDAS NOAH025_3H ``.nc4`` → study-grid ``.mat`` converter.

Maps GES DISC fields to DUAL temperature MAT variables expected by
``daily_bundle`` / Matlab ``D2_avg_sm_vod.m``:

- ``Ts_gldas``      ← ``AvgSurfT_inst`` (surface skin temperature, K)
- ``Tsoil1_gldas``  ← ``SoilTMP0_10cm_inst`` (K)
- ``Tsoil2_gldas``  ← ``SoilTMP10_40cm_inst`` (K)

Output naming: ``YYYYMMDD_HHMM.mat`` (UTC, from granule filename).
Grid: resampled to ``lat_9km`` / ``lon_9km`` from ``IGBP_9km_12.mat``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ingest.mat_bundle import load_mat_file

logger = logging.getLogger(__name__)

_NC4_NAME_RE = re.compile(
    r"\.A(?P<date>\d{8})\.(?P<hour>\d{4})\.",
    re.IGNORECASE,
)

_GLDS_FIELD_MAP: dict[str, str] = {
    "Ts_gldas": "AvgSurfT_inst",
    "Tsoil1_gldas": "SoilTMP0_10cm_inst",
    "Tsoil2_gldas": "SoilTMP10_40cm_inst",
}


@dataclass
class GldasConvertResult:
    input_dir: str
    output_dir: str
    total_nc4: int = 0
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    outputs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0 and not self.errors


def parse_gldas_nc4_timestamp(path: str | Path) -> datetime | None:
    """Parse UTC timestamp from ``GLDAS_NOAH025_3H.AYYYYMMDD.HHMM.*.nc4``."""
    match = _NC4_NAME_RE.search(Path(path).name)
    if match is None:
        return None
    return datetime.strptime(
        f"{match.group('date')}{match.group('hour')}", "%Y%m%d%H%M"
    )


def mat_name_for_nc4(path: str | Path) -> str | None:
    parsed = parse_gldas_nc4_timestamp(path)
    if parsed is None:
        return None
    return f"{parsed:%Y%m%d_%H%M}.mat"


def load_study_grid(ancillary_mat: str | Path) -> tuple[Any, Any]:
    """Return ``(lat_9km, lon_9km)`` 2D arrays from ancillary MAT."""
    import numpy as np

    payload = load_mat_file(Path(ancillary_mat))
    lat = None
    lon = None
    for key in ("lat_9km", "lat", "latitude"):
        if key in payload:
            lat = payload[key]
            break
    for key in ("lon_9km", "lon", "longitude"):
        if key in payload:
            lon = payload[key]
            break
    if lat is None or lon is None:
        raise KeyError(
            f"lat_9km/lon_9km not found in ancillary MAT: {ancillary_mat}"
        )
    lat_arr = np.asarray(lat, dtype=np.float64)
    lon_arr = np.asarray(lon, dtype=np.float64)
    if lat_arr.shape != lon_arr.shape:
        raise ValueError(
            f"lat/lon shape mismatch in {ancillary_mat}: "
            f"{lat_arr.shape} vs {lon_arr.shape}"
        )
    return lat_arr, lon_arr


def _interpolate_nc4_field(
    nc_path: Path,
    variable: str,
    lat_tgt: Any,
    lon_tgt: Any,
) -> Any:
    import numpy as np
    import xarray as xr
    from scipy.interpolate import RegularGridInterpolator

    with xr.open_dataset(nc_path) as ds:
        if variable not in ds:
            raise KeyError(f"{variable} not in {nc_path.name}")
        lat = np.asarray(ds["lat"].values, dtype=np.float64)
        lon = np.asarray(ds["lon"].values, dtype=np.float64)
        field = np.asarray(ds[variable].isel(time=0).values, dtype=np.float64)

    if lat.size < 2 or lon.size < 2:
        raise ValueError(f"invalid GLDAS grid in {nc_path.name}")

    interp = RegularGridInterpolator(
        (lat, lon),
        field,
        bounds_error=False,
        fill_value=np.nan,
    )
    query = np.column_stack([lat_tgt.ravel(), lon_tgt.ravel()])
    out = interp(query).reshape(lat_tgt.shape)
    return out


def convert_gldas_nc4_file(
    nc_path: str | Path,
    *,
    output_dir: str | Path,
    ancillary_mat: str | Path,
    dry_run: bool = False,
    skip_existing: bool = True,
) -> Path | None:
    """Convert one ``.nc4`` granule to ``YYYYMMDD_HHMM.mat``."""
    from scipy.io import savemat

    nc_path = Path(nc_path)
    out_name = mat_name_for_nc4(nc_path)
    if out_name is None:
        raise ValueError(f"cannot parse GLDAS timestamp from {nc_path.name}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / out_name
    if skip_existing and out_path.is_file():
        logger.info("skip existing %s", out_path)
        return out_path

    if dry_run:
        logger.info("dry_run would write %s from %s", out_path, nc_path.name)
        return out_path

    lat_tgt, lon_tgt = load_study_grid(ancillary_mat)
    payload: dict[str, Any] = {}
    for mat_key, nc_var in _GLDS_FIELD_MAP.items():
        payload[mat_key] = _interpolate_nc4_field(nc_path, nc_var, lat_tgt, lon_tgt)

    savemat(str(out_path), payload, do_compression=True)
    logger.info("wrote %s from %s", out_path, nc_path.name)
    return out_path


def convert_gldas_nc4_directory(
    *,
    input_dir: str | Path,
    output_dir: str | Path,
    ancillary_mat: str | Path,
    dry_run: bool = False,
    skip_existing: bool = True,
    max_files: int | None = None,
) -> GldasConvertResult:
    """Batch-convert ``*.nc4`` under ``input_dir`` (recursive)."""
    input_path = Path(input_dir)
    result = GldasConvertResult(
        input_dir=str(input_path),
        output_dir=str(output_dir),
    )
    if not input_path.is_dir():
        result.errors.append(f"input_dir not found: {input_path}")
        result.failed = 1
        return result

    nc_files = sorted(input_path.rglob("*.nc4"))
    if max_files is not None and max_files > 0:
        nc_files = nc_files[: int(max_files)]
    result.total_nc4 = len(nc_files)

    for nc_file in nc_files:
        out_name = mat_name_for_nc4(nc_file)
        if out_name is None:
            result.failed += 1
            result.errors.append(f"{nc_file.name}: cannot parse timestamp")
            continue
        out_path = Path(output_dir) / out_name
        if skip_existing and out_path.is_file() and not dry_run:
            result.skipped += 1
            result.outputs.append(str(out_path))
            continue
        try:
            written = convert_gldas_nc4_file(
                nc_file,
                output_dir=output_dir,
                ancillary_mat=ancillary_mat,
                dry_run=dry_run,
                skip_existing=False,
            )
            if written is not None:
                result.converted += 1
                result.outputs.append(str(written))
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            msg = f"{nc_file.name}: {exc}"
            result.errors.append(msg)
            logger.warning("convert failed %s", msg)

    return result
