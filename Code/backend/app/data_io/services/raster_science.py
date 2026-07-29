"""科学栅格：列出 nc/hdf/mat 变量，并抽取 2D 场为 GeoTIFF。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from app.data_io.services.grid_presets import (
    list_grid_presets,
    resolve_geo_reference,
    suggest_grid_preset,
)


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
    for var in info.get("variables") or []:
        shape = var.get("shape")
        suggested = suggest_grid_preset(shape)
        if suggested:
            break
    info["grid_presets"] = list_grid_presets()
    info["suggested_grid_preset"] = suggested
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


def _list_mat(path: Path) -> dict[str, Any]:
    """仅列变量元数据，避免整表 loadmat（大文件易导致代理 502）。"""
    variables: list[dict[str, Any]] = []
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
            }
    except Exception:
        pass

    try:
        import h5py  # type: ignore

        with h5py.File(str(path), "r") as f:
            variables = _walk_h5(f)
        if not variables:
            raise RuntimeError("MAT 中未找到二维及以上变量")
        return {
            "format": "mat-v73",
            "variables": variables,
            "needs_variable_select": True,
        }
    except Exception as exc:
        raise RuntimeError(f"无法读取 MAT（v5/v7.3）: {exc}") from exc


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
) -> dict[str, Any]:
    ext = path.suffix.lower()
    if ext in {".tif", ".tiff"}:
        output_tif.write_bytes(path.read_bytes())
        return {"path": str(output_tif), "source": "copy"}

    array, _src_transform, _src_crs = _load_2d_array(
        path, variable_id=variable_id, time_index=time_index
    )
    array = apply_invalid_values(array, invalid_values=invalid_values, nodata=nodata)

    try:
        import rasterio
    except ImportError as exc:
        raise RuntimeError("缺少 rasterio，无法写出 GeoTIFF") from exc

    height, width = int(array.shape[0]), int(array.shape[1])
    transform, crs, resolved_bounds = resolve_geo_reference(
        height=height,
        width=width,
        grid_preset=grid_preset,
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
    write_nodata = (
        float(nodata)
        if nodata is not None
        else (
            float("nan") if np.issubdtype(np.dtype(dtype_name), np.floating) else None
        )
    )
    if write_nodata is not None and np.isfinite(write_nodata):
        profile["nodata"] = write_nodata

    data = array.astype(profile["dtype"], copy=False)
    with rasterio.open(output_tif, "w", **profile) as dst:
        dst.write(data, 1)

    return {
        "path": str(output_tif),
        "width": width,
        "height": height,
        "crs": crs,
        "bounds": resolved_bounds,
        "grid_preset": grid_preset,
        "variable_id": variable_id,
        "nodata": write_nodata,
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
    except Exception:
        pass

    try:
        from scipy.io import loadmat  # type: ignore

        data = loadmat(str(path), squeeze_me=True, variable_names=[variable_id])
        if variable_id not in data:
            raise KeyError(variable_id)
        arr = _as_2d(data[variable_id], time_index)
        return np.asarray(arr, dtype=np.float32), None, None
    except Exception as exc:
        raise RuntimeError(f"无法读取 MAT 变量 {variable_id}: {exc}") from exc


def describe_path_meta(path: Path) -> str:
    return json.dumps({"name": path.name, "size": path.stat().st_size})
