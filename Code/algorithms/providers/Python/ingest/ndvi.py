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
        raise FileNotFoundError(
            f"No NDVI rasters found in {input_dir} for {start_time:%Y-%m-%d} to {end_time:%Y-%m-%d}"
        )
    return records


def load_ndvi_stack(
    input_dir: str | Path,
    start_time: datetime,
    end_time: datetime,
    pattern: str = "*.tif",
) -> tuple[Any, list[datetime]]:
    """
    加载指定时间范围内的 NDVI 栅格堆叠数据。

    返回：(stack, dates)
        - stack: numpy 数组，shape (height, width, time)
        - dates: 对应的时间戳列表

    地理参考通过 discover_ndvi_rasters 打开第一个文件时获取。
    """
    import numpy as np
    import rasterio

    records = discover_ndvi_rasters(input_dir, start_time, end_time, pattern=pattern)
    arrays: list[np.ndarray] = []
    first_transform = None
    for record in records:
        with rasterio.open(record.file_path) as dataset:
            arrays.append(dataset.read(1).astype(np.float64))
            if first_transform is None:
                first_transform = dataset.transform
    stack = np.stack(arrays, axis=2)
    return stack, [record.date for record in records]


@dataclass(frozen=True, slots=True)
class NdviStackInfo:
    """NDVI 栅格堆叠的完整信息，包含地理参考"""

    stack: Any  # numpy.ndarray (height, width, time)
    dates: list[datetime]
    transform: Any  # rasterio.Affine 地理变换
    crs: Any  # rasterio.CRS 坐标参考系
    width: int
    height: int


def load_ndvi_stack_full(
    input_dir: str | Path,
    start_time: datetime,
    end_time: datetime,
    pattern: str = "*.tif",
) -> NdviStackInfo:
    """
    加载 NDVI 栅格堆叠数据，返回完整的地理参考信息。

    适用于需要输出 COG/GeoTIFF 的场景。

    返回 NdviStackInfo，其中 transform 和 crs 来自第一景影像。
    """
    records = discover_ndvi_rasters(input_dir, start_time, end_time, pattern=pattern)
    import numpy as np
    import rasterio

    arrays: list[np.ndarray] = []
    first_transform = None
    first_crs = None
    first_height = 0
    first_width = 0
    for record in records:
        with rasterio.open(record.file_path) as dataset:
            arrays.append(dataset.read(1).astype(np.float64))
            if first_transform is None:
                first_transform = dataset.transform
                first_crs = dataset.crs
                first_height = dataset.height
                first_width = dataset.width
    stack = np.stack(arrays, axis=2)
    return NdviStackInfo(
        stack=stack,
        dates=[record.date for record in records],
        transform=first_transform,
        crs=first_crs,
        width=first_width,
        height=first_height,
    )
