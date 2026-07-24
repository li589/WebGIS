from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SMAP_DATE_PATTERN = re.compile(r"(\d{8})")


@dataclass(frozen=True, slots=True)
class SmapFieldSpec:
    output_name: str
    hdf5_path: str
    min_valid: float | None = None
    max_valid: float | None = None
    invalid_fill: float = -9999.0
    transpose: bool = True


SMAP_AM_FIELD_SPECS: tuple[SmapFieldSpec, ...] = (
    SmapFieldSpec(
        "TBh", "/Soil_Moisture_Retrieval_Data_AM/tb_h_corrected", max_valid=330.0
    ),
    SmapFieldSpec(
        "TBv", "/Soil_Moisture_Retrieval_Data_AM/tb_v_corrected", max_valid=330.0
    ),
    SmapFieldSpec(
        "Ts",
        "/Soil_Moisture_Retrieval_Data_AM/surface_temperature",
        min_valid=253.15,
        max_valid=313.15,
    ),
    SmapFieldSpec(
        "vwc",
        "/Soil_Moisture_Retrieval_Data_AM/vegetation_water_content",
        min_valid=0.0,
        max_valid=30.0,
    ),
    SmapFieldSpec("IA", "/Soil_Moisture_Retrieval_Data_AM/boresight_incidence"),
    SmapFieldSpec("sm_dca", "/Soil_Moisture_Retrieval_Data_AM/soil_moisture_dca"),
    SmapFieldSpec("sm_scav", "/Soil_Moisture_Retrieval_Data_AM/soil_moisture_scav"),
    SmapFieldSpec("vod_dca", "/Soil_Moisture_Retrieval_Data_AM/vegetation_opacity_dca"),
    SmapFieldSpec(
        "vod_sca", "/Soil_Moisture_Retrieval_Data_AM/vegetation_opacity_scav"
    ),
)


def extract_date_from_smap_filename(file_path: str | Path) -> str:
    match = SMAP_DATE_PATTERN.search(Path(file_path).name)
    if match is None:
        raise ValueError(f"Cannot parse date from SMAP filename: {file_path}")
    return match.group(1)


def _sanitize_array(data: Any, spec: SmapFieldSpec) -> Any:
    import numpy as np

    result = np.array(data, dtype=np.float64, copy=True)
    if spec.transpose:
        result = result.T
    result[result == spec.invalid_fill] = np.nan
    if spec.min_valid is not None:
        result[result < spec.min_valid] = np.nan
    if spec.max_valid is not None:
        result[result > spec.max_valid] = np.nan
    return result


def read_smap_am_fields(
    file_path: str | Path,
    field_specs: Iterable[SmapFieldSpec] | None = None,
) -> dict[str, Any]:
    import h5py

    specs = tuple(field_specs or SMAP_AM_FIELD_SPECS)
    file_path = Path(file_path)
    outputs: dict[str, Any] = {}
    with h5py.File(file_path, "r") as h5_file:
        for spec in specs:
            raw = h5_file[spec.hdf5_path][()]
            outputs[spec.output_name] = _sanitize_array(raw, spec)
    return outputs


def convert_smap_l3_file_to_mat(
    file_path: str | Path,
    output_dir: str | Path,
    field_specs: Iterable[SmapFieldSpec] | None = None,
) -> Path:
    from scipy.io import savemat

    file_path = Path(file_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    date_key = extract_date_from_smap_filename(file_path)
    output_path = output_dir / f"{date_key}.mat"
    outputs = read_smap_am_fields(file_path, field_specs=field_specs)
    savemat(output_path, outputs, do_compression=True)
    return output_path


def convert_smap_l3_directory_to_mat(
    input_dir: str | Path,
    output_dir: str | Path,
    pattern: str = "*.h5",
    field_specs: Iterable[SmapFieldSpec] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[Path]:
    input_dir = Path(input_dir)
    files = sorted(input_dir.glob(pattern))
    if start_time is not None or end_time is not None:
        filtered_files: list[Path] = []
        for file_path in files:
            date_key = extract_date_from_smap_filename(file_path)
            file_time = datetime.strptime(date_key, "%Y%m%d")
            if start_time is not None and file_time < start_time:
                continue
            if end_time is not None and file_time > end_time:
                continue
            filtered_files.append(file_path)
        files = filtered_files
    if not files:
        raise FileNotFoundError(f"No SMAP HDF5 files found in {input_dir}")
    outputs: list[Path] = []
    for file_path in files:
        outputs.append(convert_smap_l3_file_to_mat(file_path, output_dir, field_specs))
    return outputs
