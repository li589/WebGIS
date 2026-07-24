"""A1/A2 NDVI HDF → 9 km GeoTIFF preprocess (Matlab VNP13C1 / MOYD13C1).

Pipeline (aligned with Matlab A1_VNP13C1 / A2_MOYD13C1):
1. Extract NDVI + pixel-reliability QA from VIIRS (.h5) or MODIS (.hdf)
2. Georeference as EPSG:4326 global CMG (-180..180, -90..90)
3. Reproject to EPSG:6933
4. QA mask (reliability >= 2) + scale NDVI by 1e-4
5. Average-resample to 9 km grid (3856 x 1624, fixed EASE-Grid 2.0 extent)

Does not modify the Matlab tree. Requires rasterio (GDAL) for real HDF/H5 inputs.
Pure helpers are unit-testable without GDAL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import numpy as np

SourceKind = Literal["viirs", "modis"]

# Matlab A1/A2 gdalwarp -te / -ts for 9 km EASE-Grid 2.0
_EASE2_BOUNDS = (-17367530.45, -7314540.83, 17367530.45, 7314540.83)
_EASE2_WIDTH = 3856
_EASE2_HEIGHT = 1624
_NDVI_SCALE = 0.0001
_NDVI_VALID_MIN = -2000
_NDVI_VALID_MAX = 10000
_QA_BAD_MIN = 2

_VIIRS_NDVI_SUBDATASET = (
    'HDF5:"{path}"://HDFEOS/GRIDS/VIIRS_Grid_16Day_VI_CMG/'
    "Data_Fields/CMG_0.05_Deg_16_days_NDVI"
)
_VIIRS_QA_SUBDATASET = (
    'HDF5:"{path}"://HDFEOS/GRIDS/VIIRS_Grid_16Day_VI_CMG/'
    "Data_Fields/CMG_0.05_Deg_16_days_pixel_reliability"
)
_MODIS_NDVI_SUBDATASET = (
    'HDF4_EOS:EOS_GRID:"{path}":MODIS_Grid_16Day_VI_CMG:'
    '"CMG 0.05 Deg 16 days NDVI"'
)
_MODIS_QA_SUBDATASET = (
    'HDF4_EOS:EOS_GRID:"{path}":MODIS_Grid_16Day_VI_CMG:'
    '"CMG 0.05 Deg 16 days pixel reliability"'
)

_YDOY_IN_NAME = re.compile(r"(\d{7})")


@dataclass(frozen=True, slots=True)
class NdviHdfPreprocessResult:
    output_path: Path
    source_kind: SourceKind
    observation_date: datetime
    source_path: Path


def detect_source_kind(path: str | Path) -> SourceKind:
    suffix = Path(path).suffix.lower()
    if suffix in {".h5", ".hdf5"}:
        return "viirs"
    if suffix in {".hdf", ".he4"}:
        return "modis"
    raise ValueError(f"Unsupported NDVI HDF extension: {path}")


def parse_ydoy_from_filename(file_path: str | Path) -> datetime:
    """Parse YYYYDDD from product filename (Matlab: hdfname(10:16))."""
    name = Path(file_path).name
    # Prefer chars at Matlab index 10:16 (1-based) → slice [9:16]
    if len(name) >= 16 and name[9:16].isdigit():
        token = name[9:16]
    else:
        match = _YDOY_IN_NAME.search(name)
        if match is None:
            raise ValueError(f"Cannot parse YYYYDDD from NDVI HDF name: {file_path}")
        token = match.group(1)
    year = int(token[:4])
    doy = int(token[4:7])
    return datetime(year, 1, 1) + timedelta(days=doy - 1)


def apply_ndvi_qa_mask(
    ndvi: np.ndarray,
    qa: np.ndarray,
    *,
    scale: float = _NDVI_SCALE,
) -> np.ndarray:
    """Apply Matlab A1/A2 mask + scale → float NDVI with NaN fill."""
    out = ndvi.astype(np.float64, copy=True)
    invalid = (
        (out > _NDVI_VALID_MAX)
        | (out < _NDVI_VALID_MIN)
        | (qa.astype(np.float64) >= _QA_BAD_MIN)
    )
    out[invalid] = np.nan
    out *= scale
    return out


def discover_ndvi_hdf_files(input_dir: str | Path) -> list[Path]:
    input_dir = Path(input_dir)
    files = sorted(
        {
            *input_dir.glob("*.h5"),
            *input_dir.glob("*.hdf5"),
            *input_dir.glob("*.hdf"),
            *input_dir.glob("*.HDF"),
            *input_dir.glob("*.H5"),
        }
    )
    return files


def _subdataset_uris(path: Path, kind: SourceKind) -> tuple[str, str]:
    posix = path.as_posix()
    if kind == "viirs":
        return (
            _VIIRS_NDVI_SUBDATASET.format(path=posix),
            _VIIRS_QA_SUBDATASET.format(path=posix),
        )
    return (
        _MODIS_NDVI_SUBDATASET.format(path=posix),
        _MODIS_QA_SUBDATASET.format(path=posix),
    )


def _read_band(uri: str) -> np.ndarray:
    import rasterio

    with rasterio.open(uri) as ds:
        return ds.read(1)


def _write_geotiff_4326(path: Path, data: np.ndarray, nodata: float) -> None:
    import rasterio
    from rasterio.transform import from_bounds

    height, width = data.shape
    transform = from_bounds(-180.0, -90.0, 180.0, 90.0, width, height)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
        compress="deflate",
    ) as dst:
        dst.write(data, 1)


def preprocess_ndvi_hdf_file(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    work_dir: str | Path | None = None,
) -> NdviHdfPreprocessResult:
    """Convert one VNP13C1/MOD13C1 file to YYYYMMDD.tif at 9 km."""
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    kind = detect_source_kind(source_path)
    obs_date = parse_ydoy_from_filename(source_path)
    work_root = Path(work_dir) if work_dir else output_dir / "_tmp_ndvi_hdf"
    work_root.mkdir(parents=True, exist_ok=True)

    ndvi_uri, qa_uri = _subdataset_uris(source_path, kind)
    try:
        ndvi_raw = _read_band(ndvi_uri)
        qa_raw = _read_band(qa_uri)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Failed to read NDVI/QA subdatasets from {source_path}. "
            "Ensure GDAL/rasterio HDF drivers are available."
        ) from exc

    ndvi_scaled = apply_ndvi_qa_mask(ndvi_raw, qa_raw)
    stage_4326 = work_root / f"{obs_date:%Y%m%d}_ndvi_4326.tif"
    stage_9km = output_dir / f"{obs_date:%Y%m%d}.tif"
    _write_geotiff_4326(stage_4326, ndvi_scaled.astype(np.float32), nodata=np.nan)
    # Reproject 4326 → 6933 average in one step via temporary EPSG:4326 write
    # then warp; NaN nodata handled as float32 nan.
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject

    left, bottom, right, top = _EASE2_BOUNDS
    dst_transform = from_bounds(left, bottom, right, top, _EASE2_WIDTH, _EASE2_HEIGHT)
    with rasterio.open(stage_4326) as src:
        dest = np.full((_EASE2_HEIGHT, _EASE2_WIDTH), np.nan, dtype=np.float32)
        reproject(
            source=src.read(1),
            destination=dest,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:6933",
            resampling=Resampling.average,
            src_nodata=np.nan,
            dst_nodata=np.nan,
        )
        profile = {
            "driver": "GTiff",
            "height": _EASE2_HEIGHT,
            "width": _EASE2_WIDTH,
            "count": 1,
            "dtype": "float32",
            "crs": "EPSG:6933",
            "transform": dst_transform,
            "nodata": np.nan,
            "compress": "deflate",
        }
        with rasterio.open(stage_9km, "w", **profile) as dst:
            dst.write(dest, 1)

    return NdviHdfPreprocessResult(
        output_path=stage_9km,
        source_kind=kind,
        observation_date=obs_date,
        source_path=source_path,
    )


def convert_ndvi_hdf_directory_to_9km(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    work_dir: str | Path | None = None,
) -> list[NdviHdfPreprocessResult]:
    files = discover_ndvi_hdf_files(input_dir)
    if not files:
        raise FileNotFoundError(f"No VIIRS/MODIS NDVI HDF files in {input_dir}")
    results: list[NdviHdfPreprocessResult] = []
    for path in files:
        results.append(
            preprocess_ndvi_hdf_file(path, output_dir, work_dir=work_dir)
        )
    return results
