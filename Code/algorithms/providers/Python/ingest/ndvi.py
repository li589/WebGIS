from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
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


def _parse_ndvi_time(t: datetime | str) -> datetime:
    if isinstance(t, datetime):
        return t
    s = str(t).strip()
    if len(s) == 8 and s.isdigit():
        return datetime.strptime(s, "%Y%m%d")
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def discover_ndvi_rasters(
    input_dir: str | Path,
    start_time: datetime | str,
    end_time: datetime | str,
    pattern: str = "*.tif",
    composite_days: int = 16,
) -> list[NdviRasterRecord]:
    input_dir = Path(input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(
            f"NDVI directory does not exist: {input_dir} (error_code=coverage_gap)"
        )

    start_dt = _parse_ndvi_time(start_time)
    end_dt = _parse_ndvi_time(end_time)

    # 优先检测 pattern (默认 *.tif)；若为默认 tif 模式则同时包含 *.mat
    if pattern in ("*.tif", "*.tiff"):
        files = sorted(
            set(
                list(input_dir.glob("*.tif"))
                + list(input_dir.glob("*.tiff"))
                + list(input_dir.glob("*.mat"))
            )
        )
    else:
        files = sorted(input_dir.glob(pattern))

    records: list[NdviRasterRecord] = []
    all_dates: list[datetime] = []
    for file_path in files:
        try:
            date = extract_date_from_ndvi_filename(file_path)
            all_dates.append(date)
            # 兼容 16 天合成产品：若文件代表合成周期，周期 [date, date + composite_days] 与 [start_dt, end_dt] 存在重叠即可入选
            if (date <= end_dt) and (
                date + timedelta(days=max(0, composite_days)) >= start_dt
            ):
                records.append(NdviRasterRecord(file_path=file_path, date=date))
        except ValueError:
            continue

    if not records:
        if all_dates:
            min_date = min(all_dates)
            max_date = max(all_dates)
            raise FileNotFoundError(
                f"No NDVI rasters found in {input_dir} for {start_dt:%Y-%m-%d} to {end_dt:%Y-%m-%d}. "
                f"Available date range in directory is {min_date:%Y-%m-%d} to {max_date:%Y-%m-%d}. (error_code=coverage_gap)"
            )
        raise FileNotFoundError(
            f"No NDVI rasters found in {input_dir} for {start_dt:%Y-%m-%d} to {end_dt:%Y-%m-%d}. (error_code=coverage_gap)"
        )
    return records


def _read_ndvi_array_from_file(file_path: Path) -> tuple[Any, Any, Any]:
    """读取单个栅格或 MAT 文件中的 NDVI 数组，返回 (array, transform, crs)。"""
    import numpy as np

    suffix = file_path.suffix.lower()
    if suffix in (".tif", ".tiff", ".geotiff", ".cog"):
        import rasterio

        with rasterio.open(file_path) as dataset:
            arr = dataset.read(1).astype(np.float64)
            return arr, dataset.transform, dataset.crs

    if suffix == ".mat":
        import rasterio
        from rasterio.transform import from_bounds
        from scipy.io import loadmat

        mat_data = loadmat(str(file_path))
        data_arr = None
        if "NDVI" in mat_data and isinstance(mat_data["NDVI"], np.ndarray):
            data_arr = mat_data["NDVI"]
        else:
            for k, v in mat_data.items():
                if not k.startswith("__") and isinstance(v, np.ndarray) and v.ndim == 2:
                    data_arr = v
                    break
        if data_arr is None:
            raise ValueError(f"No 2D NDVI array found in MAT file: {file_path}")

        arr = data_arr.astype(np.float64)
        height, width = arr.shape
        # 中国区域默认 9km / 0.05° 常用参考边界
        transform = from_bounds(73.0, 18.0, 135.0, 53.0, width, height)
        crs = rasterio.crs.CRS.from_epsg(4326)
        return arr, transform, crs

    raise ValueError(f"Unsupported NDVI raster file format: {file_path}")


def load_ndvi_stack(
    input_dir: str | Path,
    start_time: datetime,
    end_time: datetime,
    pattern: str = "*.tif",
) -> tuple[Any, list[datetime]]:
    """
    加载指定时间范围内的 NDVI 栅格堆叠数据。支持 GeoTIFF (*.tif) 与 MATLAB (*.mat)。

    返回：(stack, dates)
        - stack: numpy 数组，shape (height, width, time)
        - dates: 对应的时间戳列表
    """
    import numpy as np

    records = discover_ndvi_rasters(input_dir, start_time, end_time, pattern=pattern)
    arrays: list[np.ndarray] = []
    for record in records:
        arr, _, _ = _read_ndvi_array_from_file(record.file_path)
        arrays.append(arr)
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
    加载 NDVI 栅格堆叠数据，返回完整的地理参考信息。支持 GeoTIFF (*.tif) 与 MATLAB (*.mat)。
    """
    import numpy as np

    records = discover_ndvi_rasters(input_dir, start_time, end_time, pattern=pattern)
    arrays: list[np.ndarray] = []
    first_transform = None
    first_crs = None
    first_height = 0
    first_width = 0
    for record in records:
        arr, transform, crs = _read_ndvi_array_from_file(record.file_path)
        arrays.append(arr)
        if first_transform is None:
            first_transform = transform
            first_crs = crs
            first_height, first_width = arr.shape
    stack = np.stack(arrays, axis=2)
    return NdviStackInfo(
        stack=stack,
        dates=[record.date for record in records],
        transform=first_transform,
        crs=first_crs,
        width=first_width,
        height=first_height,
    )
