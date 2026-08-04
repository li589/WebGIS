"""科学栅格：列出 nc/hdf/mat 变量，并抽取 2D 场为 GeoTIFF。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from app.data_io.services.grid_presets import (
    align_array_to_grid_preset,
    list_grid_presets,
    match_grid_preset,
    resolve_geo_reference,
    suggest_grid_preset,
)

logger = logging.getLogger(__name__)


def list_raster_variables(path: Path) -> dict[str, Any]:
    ext = path.suffix.lower()
    if ext in {".tif", ".tiff"}:
        return {
            "format": "geotiff",
            "variables": [
                {"id": "band:1", "name": "band_1", "shape": None, "dtype": None}
            ],
            "needs_variable_select": False,
            "grid_presets": list_grid_presets(),
            "suggested_grid_preset": None,
            "suggested_crs": "EPSG:4326",
        }
    if ext == ".nc":
        info = _list_netcdf(path)
    elif ext in {".h5", ".hdf", ".he5"}:
        info = _list_hdf(path)
    elif ext == ".mat":
        info = _list_mat(path)
    else:
        raise ValueError(f"不支持的栅格格式: {ext}")

    suggested = None
    suggested_transposed = False
    for var in info.get("variables") or []:
        shape = var.get("shape")
        preset_id, needs_transpose = match_grid_preset(shape)
        if preset_id:
            var["suggested_grid_preset"] = preset_id
            var["needs_transpose"] = needs_transpose
            var["axis_hint"] = (
                "matlab_hdf5_reversed_dims" if needs_transpose else "rows_cols_match"
            )
            if suggested is None:
                suggested = preset_id
                suggested_transposed = needs_transpose
    info["grid_presets"] = list_grid_presets()
    info["suggested_grid_preset"] = suggested
    info["suggested_needs_transpose"] = suggested_transposed
    info["suggested_crs"] = (
        next(
            (
                p["crs"]
                for p in info["grid_presets"]
                if p["id"] == suggested and p.get("crs")
            ),
            "EPSG:4326",
        )
        if suggested
        else "EPSG:4326"
    )
    return info


def _list_netcdf(path: Path) -> dict[str, Any]:
    variables: list[dict[str, Any]] = []
    try:
        from netCDF4 import Dataset  # type: ignore

        with Dataset(str(path), "r") as ds:
            for name, var in ds.variables.items():
                if len(getattr(var, "shape", ())) >= 2:
                    fill = getattr(var, "_FillValue", None)
                    if fill is None:
                        fill = getattr(var, "missing_value", None)
                    variables.append(
                        {
                            "id": name,
                            "name": name,
                            "shape": list(var.shape),
                            "dtype": str(getattr(var, "dtype", "")),
                            "fill_value": float(fill) if fill is not None else None,
                        }
                    )
        return {
            "format": "netcdf",
            "variables": variables,
            "needs_variable_select": True,
        }
    except Exception:
        pass
    try:
        import scipy.io as sio  # type: ignore

        ds = sio.netcdf_file(str(path), "r", mmap=False)
        try:
            for name, var in ds.variables.items():
                shape = list(getattr(var, "data", getattr(var, "shape", [])))
                if hasattr(var, "data"):
                    shape = list(np.asarray(var.data).shape)
                if len(shape) >= 2:
                    variables.append(
                        {"id": name, "name": name, "shape": shape, "dtype": "float"}
                    )
        finally:
            ds.close()
        return {
            "format": "netcdf-classic",
            "variables": variables,
            "needs_variable_select": True,
        }
    except Exception as exc:
        raise RuntimeError(f"无法读取 NetCDF: {exc}") from exc


def _walk_h5(obj: Any, prefix: str = "") -> list[dict[str, Any]]:
    import h5py  # type: ignore

    out: list[dict[str, Any]] = []
    if isinstance(obj, h5py.Dataset):
        shape = list(obj.shape)
        if len(shape) >= 2:
            fill = obj.attrs.get("_FillValue", obj.attrs.get("missing_value"))
            try:
                fill_v = (
                    float(np.asarray(fill).reshape(-1)[0]) if fill is not None else None
                )
            except Exception:
                fill_v = None
            out.append(
                {
                    "id": prefix,
                    "name": prefix,
                    "shape": shape,
                    "dtype": str(obj.dtype),
                    "fill_value": fill_v,
                }
            )
        return out
    if isinstance(obj, h5py.Group):
        for key in obj.keys():
            child = obj[key]
            path = f"{prefix}/{key}" if prefix else key
            out.extend(_walk_h5(child, path))
    return out


def _list_hdf(path: Path) -> dict[str, Any]:
    try:
        import h5py  # type: ignore

        with h5py.File(str(path), "r") as f:
            variables = _walk_h5(f)
        if variables:
            return {
                "format": "hdf5",
                "variables": variables,
                "needs_variable_select": True,
            }
    except Exception:
        pass

    try:
        from osgeo import gdal  # type: ignore

        gdal.UseExceptions()
        ds = gdal.Open(str(path))
        if ds is None:
            raise RuntimeError("GDAL 无法打开文件")
        count = ds.GetSubDatasets()
        variables = []
        if count:
            for i, (sub_name, desc) in enumerate(count):
                variables.append(
                    {
                        "id": sub_name,
                        "name": desc or sub_name,
                        "shape": None,
                        "dtype": None,
                    }
                )
        else:
            variables.append(
                {"id": "gdal:1", "name": path.name, "shape": None, "dtype": None}
            )
        return {
            "format": "hdf-gdal",
            "variables": variables,
            "needs_variable_select": True,
        }
    except Exception as exc:
        raise RuntimeError(f"无法读取 HDF（需 h5py 或 GDAL）: {exc}") from exc


def _decode_matlab_char(dataset: Any) -> str | None:
    """Decode MATLAB HDF5 char arrays (often uint16 columns) to text."""
    try:
        raw = np.asarray(dataset)
        if raw.dtype == np.uint16 or raw.dtype == np.uint8:
            flat = raw.reshape(-1, order="F") if raw.ndim > 1 else raw.ravel()
            chars = "".join(chr(int(c)) for c in flat if int(c) > 0)
            return chars or None
        if raw.dtype.kind in {"U", "S"}:
            return str(raw.astype(str)).strip() or None
    except Exception:
        return None
    return None


def _list_mat(path: Path) -> dict[str, Any]:
    """仅列变量元数据，避免整表 loadmat（大文件易导致代理 502）。"""
    variables: list[dict[str, Any]] = []
    file_meta: dict[str, Any] = {}

    # v7.3 HDF5 first — large SMAP/omega mats usually land here
    try:
        import h5py  # type: ignore

        with h5py.File(str(path), "r") as f:

            def _visit(name: str, obj: Any) -> None:
                if name.startswith("#refs#"):
                    return
                if not hasattr(obj, "shape") or not hasattr(obj, "dtype"):
                    return
                shape = list(obj.shape)
                if name in {"date_start", "date_end", "date_range_str"}:
                    decoded = _decode_matlab_char(obj)
                    if decoded:
                        file_meta[name] = decoded
                    return
                if len(shape) >= 2 and obj.dtype.kind in {"f", "i", "u"}:
                    variables.append(
                        {
                            "id": name,
                            "name": name.split("/")[-1],
                            "shape": shape,
                            "dtype": str(obj.dtype),
                            "fill_value": None,
                        }
                    )

            f.visititems(_visit)
        if variables:
            return {
                "format": "mat-v73",
                "variables": variables,
                "needs_variable_select": True,
                "file_meta": file_meta,
            }
    except Exception:
        pass

    try:
        from scipy.io import whosmat  # type: ignore

        info = whosmat(str(path))
        for name, shape, _dtype in info:
            if name.startswith("__"):
                continue
            if len(shape) >= 2:
                variables.append(
                    {
                        "id": name,
                        "name": name,
                        "shape": list(shape),
                        "dtype": str(_dtype),
                    }
                )
        if variables:
            return {
                "format": "mat-v5",
                "variables": variables,
                "needs_variable_select": True,
                "file_meta": file_meta,
            }
    except Exception:
        pass

    raise RuntimeError("无法读取 MAT（v5/v7.3）")


def apply_invalid_values(
    array: Any,
    *,
    invalid_values: list[float] | None = None,
    nodata: float | None = None,
) -> Any:
    """将无效值替换为 nodata（默认 NaN）。"""
    a = np.asarray(array, dtype=np.float32)
    out_nodata = np.float32(nodata) if nodata is not None else np.float32(np.nan)
    if invalid_values:
        for v in invalid_values:
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if np.isnan(fv):
                continue
            a = np.where(np.isclose(a, fv, equal_nan=False), out_nodata, a)
    # 保留已有 NaN / Inf 为 nodata
    a = np.where(np.isfinite(a), a, out_nodata)
    return a


def extract_variable_to_geotiff(
    path: Path,
    *,
    variable_id: str,
    output_tif: Path,
    time_index: int = 0,
    source_crs: str | None = None,
    grid_preset: str | None = None,
    bounds: list[float] | None = None,
    invalid_values: list[float] | None = None,
    nodata: float | None = None,
    axis_order: str = "auto",
) -> dict[str, Any]:
    ext = path.suffix.lower()
    if ext in {".tif", ".tiff"}:
        output_tif.write_bytes(path.read_bytes())
        return {"path": str(output_tif), "source": "copy"}

    array, _src_transform, _src_crs = _load_2d_array(
        path, variable_id=variable_id, time_index=time_index
    )

    # 自动推断无效值（调用方未指定时）：带上 _FillValue / missing_value 元数据
    applied_invalid = list(invalid_values or [])
    if not applied_invalid:
        try:
            detected = auto_detect_invalid_values(path, variable_id)
            applied_invalid = list(detected.get("suggested_invalid_values") or [])
        except Exception:
            try:
                detected = detect_sentinel_values(array)
                applied_invalid = list(detected.get("suggested_invalid_values") or [])
            except Exception:
                applied_invalid = []

    array = apply_invalid_values(
        array, invalid_values=applied_invalid or None, nodata=nodata
    )

    # 对齐预设行列：修复 MATLAB v7.3/HDF5 维度颠倒导致的全球图左右拉伸/南北压缩
    effective_preset = grid_preset or suggest_grid_preset(getattr(array, "shape", None))
    array, did_transpose = align_array_to_grid_preset(
        array, effective_preset, axis_order=axis_order
    )

    try:
        import rasterio
    except ImportError as exc:
        raise RuntimeError("缺少 rasterio，无法写出 GeoTIFF") from exc

    height, width = int(array.shape[0]), int(array.shape[1])
    transform, crs, resolved_bounds = resolve_geo_reference(
        height=height,
        width=width,
        grid_preset=effective_preset,
        source_crs=source_crs,
        bounds=bounds,
    )

    dtype_name = (
        array.dtype.name
        if array.dtype.name
        in {"float32", "float64", "int16", "int32", "uint8", "uint16"}
        else "float32"
    )
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": dtype_name,
        "crs": crs,
        "transform": transform,
        "compress": "deflate",
    }
    # Prefer a finite nodata sentinel so GeoTIFF readers / warp mark voids
    # correctly. Float NaN as Profile.nodata is poorly supported by some
    # rasterio/GDAL paths and previously left nodata=None → black previews.
    if nodata is not None and np.isfinite(float(nodata)):
        write_nodata = float(nodata)
    elif np.issubdtype(np.dtype(dtype_name), np.floating):
        write_nodata = float(-9999.0)
    else:
        write_nodata = None
    if write_nodata is not None:
        profile["nodata"] = write_nodata

    data = array.astype(profile["dtype"], copy=False)
    if write_nodata is not None and np.issubdtype(data.dtype, np.floating):
        data = np.where(np.isfinite(data), data, write_nodata).astype(
            profile["dtype"], copy=False
        )
    with rasterio.open(output_tif, "w", **profile) as dst:
        dst.write(data, 1)

    return {
        "path": str(output_tif),
        "width": width,
        "height": height,
        "crs": crs,
        "bounds": resolved_bounds,
        "grid_preset": effective_preset,
        "variable_id": variable_id,
        "nodata": write_nodata,
        "axis_transposed": did_transpose,
        "invalid_values_applied": applied_invalid,
    }


def _load_2d_array(
    path: Path, *, variable_id: str, time_index: int
) -> tuple[Any, Any, Any]:
    ext = path.suffix.lower()
    if ext == ".nc":
        return _load_netcdf_2d(path, variable_id, time_index)
    if ext in {".h5", ".hdf", ".he5"}:
        return _load_hdf_2d(path, variable_id, time_index)
    if ext == ".mat":
        return _load_mat_2d(path, variable_id, time_index)
    raise ValueError(f"不支持抽取: {ext}")


def _as_2d(arr: Any, time_index: int) -> Any:
    a = np.asarray(arr)
    if a.ndim == 2:
        return a
    if a.ndim > 2:
        idx = min(max(0, time_index), a.shape[0] - 1)
        sliced = a[idx, ...]
        while sliced.ndim > 2:
            sliced = sliced[0]
        return sliced
    raise ValueError("变量不是二维或可切片为二维的数组")


def _load_netcdf_2d(
    path: Path, variable_id: str, time_index: int
) -> tuple[Any, Any, Any]:
    try:
        from netCDF4 import Dataset  # type: ignore

        with Dataset(str(path), "r") as ds:
            var = ds.variables[variable_id]
            data = _as_2d(var[...], time_index)
            return np.ma.filled(np.ma.array(data), np.nan), None, None
    except Exception:
        import scipy.io as sio  # type: ignore

        ds = sio.netcdf_file(str(path), "r", mmap=False)
        try:
            var = ds.variables[variable_id]
            data = _as_2d(var.data, time_index)
            return np.asarray(data, dtype=np.float32), None, None
        finally:
            ds.close()


def _load_hdf_2d(path: Path, variable_id: str, time_index: int) -> tuple[Any, Any, Any]:
    if (
        variable_id.startswith("HDF")
        or "://" in variable_id
        or variable_id.startswith("gdal:")
    ):
        from osgeo import gdal  # type: ignore

        gdal.UseExceptions()
        src = variable_id if not variable_id.startswith("gdal:") else str(path)
        ds = gdal.Open(src)
        if ds is None:
            raise RuntimeError(f"GDAL 无法打开: {variable_id}")
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray()
        gt = ds.GetGeoTransform()
        proj = ds.GetProjection()
        transform = None
        if gt:
            from rasterio.transform import Affine

            transform = Affine.from_gdal(*gt)
        return np.asarray(arr), transform, proj or None

    import h5py  # type: ignore

    with h5py.File(str(path), "r") as f:
        ds = f[variable_id]
        data = _as_2d(ds[...], time_index)
        return np.asarray(data), None, None


def _load_mat_2d(path: Path, variable_id: str, time_index: int) -> tuple[Any, Any, Any]:
    # 优先 v7.3 HDF5（大文件常见），避免 scipy 整文件加载失败/超时
    try:
        import h5py  # type: ignore

        with h5py.File(str(path), "r") as f:
            if variable_id in f:
                ds = f[variable_id]
                arr = _as_2d(ds[...], time_index)
                return np.asarray(arr, dtype=np.float32), None, None
            # 支持 QC/field 这类嵌套路径
            if "/" in variable_id:
                ds = f
                for part in variable_id.split("/"):
                    ds = ds[part]
                arr = _as_2d(ds[...], time_index)
                return np.asarray(arr, dtype=np.float32), None, None
    except Exception:
        pass

    try:
        from scipy.io import loadmat  # type: ignore

        # nested keys: only top-level for scipy; QC fields need struct walk
        top = variable_id.split("/", 1)[0]
        data = loadmat(str(path), squeeze_me=True, variable_names=[top])
        if top not in data:
            raise KeyError(variable_id)
        obj = data[top]
        if "/" in variable_id and hasattr(obj, "dtype") and obj.dtype.names:
            field = variable_id.split("/", 1)[1]
            if field in obj.dtype.names:
                obj = obj[field]
                while (
                    isinstance(obj, np.ndarray)
                    and obj.dtype == object
                    and obj.size == 1
                ):
                    obj = obj.flat[0]
        arr = _as_2d(obj, time_index)
        return np.asarray(arr, dtype=np.float32), None, None
    except Exception as exc:
        raise RuntimeError(f"无法读取 MAT 变量 {variable_id}: {exc}") from exc


def describe_path_meta(path: Path) -> str:
    return json.dumps({"name": path.name, "size": path.stat().st_size})


#: 地理数据中常见的无效值（哨兵值）集合，覆盖通用填充值、整型极值、
#: float32 极值、科学数据填充值及分类数据填充值等常见场景。
COMMON_SENTINEL_VALUES: list[float] = [
    # 通用填充值
    -9999.0,
    -999.0,
    9999.0,
    999.0,
    # int16 极值
    -32768.0,
    32767.0,
    # uint16 相关极值
    -65536.0,
    65535.0,
    # float32 极值
    -3.4e38,
    3.4e38,
    # 科学数据常用填充值
    1e20,
    -1e20,
    1e30,
    -1e30,
    # 分类数据常用填充值
    -1.0,
]


def detect_sentinel_values(
    array: Any,
    *,
    fill_value: float | None = None,
    missing_value: float | None = None,
    sample_size: int = 100000,
) -> dict[str, Any]:
    """检测数组中的无效值（哨兵值）。

    通过采样统计常见哨兵值的出现频率，同时检测 Inf 与 NaN，
    用于自动推断栅格数据的无效值集合。

    参数:
        array: 输入的 numpy 数组。
        fill_value: 元数据中声明的 ``_FillValue``，若提供则纳入候选。
        missing_value: 元数据中声明的 ``missing_value``，若提供则纳入候选。
        sample_size: 采样上限，避免对超大数组进行全量扫描。

    返回:
        包含以下字段的 dict:

        - ``sentinels``: 每个哨兵值的统计信息列表
          ``[{value, count, percentage}]``，按出现次数降序排列。
        - ``inf_count``: 采样中 Inf 值的个数。
        - ``nan_count``: 采样中 NaN 值的个数。
        - ``suggested_invalid_values``: 建议作为无效值的列表
          （频率 > 0.01% 的哨兵值 + 元数据填充值）。
        - ``metadata_fill_values``: 来自元数据的填充值列表。
    """
    a = np.asarray(array)
    total = int(a.size)
    if total == 0:
        return {
            "sentinels": [],
            "inf_count": 0,
            "nan_count": 0,
            "suggested_invalid_values": [],
            "metadata_fill_values": [],
        }

    # 采样：取前 sample_size 个元素，避免全量扫描大数组
    if total > sample_size:
        sample = a.flat[:sample_size]
    else:
        sample = a.ravel()
    sample_count = int(sample.size)

    # 转为 float64 统一比较
    sample_float = sample.astype(np.float64, copy=False)

    # 统计 NaN 与 Inf
    nan_count = int(np.isnan(sample_float).sum())
    inf_count = int(np.isinf(sample_float).sum())

    # 收集元数据填充值（去重、排除 NaN）
    metadata_fill_values: list[float] = []
    for mv in (fill_value, missing_value):
        if mv is None:
            continue
        try:
            fv = float(mv)
        except (TypeError, ValueError):
            continue
        if np.isnan(fv):
            continue
        if fv not in metadata_fill_values:
            metadata_fill_values.append(fv)

    # 候选哨兵值 = 通用哨兵 + 元数据填充值（去重）
    candidates: list[float] = []
    for v in COMMON_SENTINEL_VALUES:
        if v not in candidates:
            candidates.append(v)
    for v in metadata_fill_values:
        if v not in candidates:
            candidates.append(v)

    # 仅在有限值中统计哨兵（排除 NaN / Inf）
    finite_mask = np.isfinite(sample_float)
    finite_sample = sample_float[finite_mask]

    sentinels: list[dict[str, Any]] = []
    for v in candidates:
        count = int(np.count_nonzero(finite_sample == v))
        if count > 0:
            sentinels.append(
                {
                    "value": v,
                    "count": count,
                    "percentage": round(count / sample_count * 100, 6),
                }
            )

    # 按出现次数降序排列
    sentinels.sort(key=lambda s: s["count"], reverse=True)

    # 建议无效值：频率 > 0.01% 的哨兵 + 元数据填充值
    suggested: list[float] = []
    for s in sentinels:
        if s["percentage"] > 0.01:
            if s["value"] not in suggested:
                suggested.append(s["value"])
    for v in metadata_fill_values:
        if v not in suggested:
            suggested.append(v)

    return {
        "sentinels": sentinels,
        "inf_count": inf_count,
        "nan_count": nan_count,
        "suggested_invalid_values": suggested,
        "metadata_fill_values": metadata_fill_values,
    }


def _read_fill_metadata(
    path: Path, variable_id: str
) -> tuple[float | None, float | None]:
    """从 NetCDF / HDF / MAT 元数据中读取 ``_FillValue`` 与 ``missing_value``。

    读取逻辑参考 :func:`_list_netcdf` 与 :func:`_walk_h5`，按文件扩展名
    分派到 netCDF4 或 h5py；GDAL 子数据集路径不走 h5py。

    参数:
        path: 栅格文件路径。
        variable_id: 变量标识。

    返回:
        ``(fill_value, missing_value)`` 元组，无法读取时对应项为 None。
    """
    ext = path.suffix.lower()
    fill_value: float | None = None
    missing_value: float | None = None

    if ext == ".nc":
        try:
            from netCDF4 import Dataset  # type: ignore

            with Dataset(str(path), "r") as ds:
                if variable_id in ds.variables:
                    var = ds.variables[variable_id]
                    fv = getattr(var, "_FillValue", None)
                    mv = getattr(var, "missing_value", None)
                    if fv is not None:
                        fill_value = float(np.asarray(fv).reshape(-1)[0])
                    if mv is not None:
                        missing_value = float(np.asarray(mv).reshape(-1)[0])
        except Exception as exc:  # 发布就绪修复（P1-5）：不再静默吞错
            logger.warning(
                "读取 NetCDF fill/missing 元数据失败 path=%s variable=%s: %s",
                path,
                variable_id,
                exc,
            )
    elif ext in {".h5", ".hdf", ".he5", ".mat"}:
        # GDAL 子数据集路径不走 h5py
        if not (
            variable_id.startswith("HDF")
            or "://" in variable_id
            or variable_id.startswith("gdal:")
        ):
            try:
                import h5py  # type: ignore

                with h5py.File(str(path), "r") as f:
                    if variable_id in f:
                        obj = f[variable_id]
                        fv = obj.attrs.get("_FillValue", None)
                        mv = obj.attrs.get("missing_value", None)
                        if fv is not None:
                            fill_value = float(np.asarray(fv).reshape(-1)[0])
                        if mv is not None:
                            missing_value = float(np.asarray(mv).reshape(-1)[0])
            except Exception as exc:  # 发布就绪修复（P1-5）：不再静默吞错
                logger.warning(
                    "读取 HDF/MAT fill/missing 元数据失败 path=%s variable=%s: %s",
                    path,
                    variable_id,
                    exc,
                )

    return fill_value, missing_value


def auto_detect_invalid_values(path: Path, variable_id: str) -> dict[str, Any]:
    """自动检测栅格文件中指定变量的无效值（哨兵值）。

    加载变量的二维数组，读取元数据中的 ``_FillValue`` / ``missing_value``，
    并调用 :func:`detect_sentinel_values` 进行哨兵值检测。

    参数:
        path: 栅格文件路径（支持 ``.nc`` / ``.hdf`` / ``.h5`` / ``.he5`` / ``.mat``）。
        variable_id: 变量标识。

    返回:
        :func:`detect_sentinel_values` 的检测结果 dict，额外包含
        ``path`` 与 ``variable_id`` 字段。
    """
    array, _transform, _crs = _load_2d_array(
        path, variable_id=variable_id, time_index=0
    )

    fill_value, missing_value = _read_fill_metadata(path, variable_id)

    result = detect_sentinel_values(
        array, fill_value=fill_value, missing_value=missing_value
    )
    result["path"] = str(path)
    result["variable_id"] = variable_id
    return result
