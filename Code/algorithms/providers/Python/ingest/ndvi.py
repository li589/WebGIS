from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


NDVI_DATE_PATTERN = re.compile(r"(\d{8})")


@dataclass(frozen=True, slots=True)
class NdviRasterRecord:
    file_path: Path
    date: datetime


def extract_date_from_ndvi_filename(file_path: str | Path) -> datetime:
    match = NDVI_DATE_PATTERN.search(Path(file_path).name)
    if match is None:
        raise ValueError(f"Cannot parse date from NDVI filename: {file_path}")
    return datetime.strptime(match.group(1), "%Y%m%d")


def discover_ndvi_rasters(
    input_dir: str | Path,
    start_time: datetime,
    end_time: datetime,
    pattern: str = "*.tif",
) -> list[NdviRasterRecord]:
    input_dir = Path(input_dir)
    records: list[NdviRasterRecord] = []
    for file_path in sorted(input_dir.glob(pattern)):
        date = extract_date_from_ndvi_filename(file_path)
        if start_time <= date <= end_time:
            records.append(NdviRasterRecord(file_path=file_path, date=date))
    if not records:
        raise FileNotFoundError(f"No NDVI rasters found in {input_dir} for {start_time:%Y-%m-%d} to {end_time:%Y-%m-%d}")
    return records


def load_ndvi_stack(
    input_dir: str | Path,
    start_time: datetime,
    end_time: datetime,
    pattern: str = "*.tif",
) -> tuple[Any, list[datetime]]:
    import numpy as np
    import rasterio

    records = discover_ndvi_rasters(input_dir, start_time, end_time, pattern=pattern)
    arrays: list[np.ndarray] = []
    for record in records:
        with rasterio.open(record.file_path) as dataset:
            arrays.append(dataset.read(1).astype(np.float64))
    stack = np.stack(arrays, axis=2)
    return stack, [record.date for record in records]
