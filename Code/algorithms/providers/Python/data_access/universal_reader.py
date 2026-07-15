"""通用数据读取器 — 跨格式统一数据读取。

支持格式:
  - HDF5 (.h5) — SMAP L3 SM P
  - NetCDF (.nc) — ERA5, BIOMASS, CMFD
  - GeoTIFF (.tif) — HFP, China 1km, MCD12Q1, CLCD
  - MAT (.mat) — omega 反演结果 (v5/v6 + v7.3)

统一功能:
  - 坐标归一化: latitude → lat, longitude → lon
  - 填充值处理: -9999/-32768/-inf → NaN
  - 比例缩放: 自动应用 scale_factor + add_offset
  - 区域裁剪: bbox=(west, south, east, north) 子集读取
  - 时间索引: time_index 指定特定时间层

使用示例:
    reader = UniversalDataReader("I:/Geograph_DataSet/SMAP/SMAP_L3_SM_P_20230110_R18290_001.h5")
    data = reader.read_variable("Soil_Moisture_Retrieval_Data_AM/soil_moisture",
                                 bbox=(73, 15, 137, 59))  # 中国区域
    print(data.values.shape, data.lat.shape, data.lon.shape)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


# 中国区域常用 bbox
CHINA_BBOX = (73.0, 15.0, 137.0, 59.0)


@dataclass
class DataArray:
    """统一的读取结果数据结构。"""
    values: np.ndarray           # 数据值 (填充值已替换为 NaN)
    lat: np.ndarray | None       # 纬度坐标 (一维或二维)
    lon: np.ndarray | None       # 经度坐标 (一维或二维)
    time: np.ndarray | None      # 时间坐标 (一维)
    crs: str | None              # 坐标系
    attrs: dict[str, Any]        # 属性 (units, fill_value, scale_factor, 等)
    var_name: str                # 变量名
    file_path: str               # 源文件路径
    file_format: str             # 文件格式

    @property
    def shape(self) -> tuple[int, ...]:
        return self.values.shape

    def __repr__(self) -> str:
        return (f"DataArray(var={self.var_name!r}, shape={self.values.shape}, "
                f"format={self.file_format}, crs={self.crs})")


class UniversalDataReader:
    """跨格式通用数据读取器。"""

    def __init__(self, file_path: str | Path):
        self.path = Path(file_path)
        if not self.path.exists():
            raise FileNotFoundError(f"文件不存在: {self.path}")
        self.format = self._detect_format()
        self._meta: dict[str, Any] | None = None

    def _detect_format(self) -> str:
        ext = self.path.suffix.lower()
        if ext in (".h5", ".hdf", ".he5"):
            return "hdf5"
        if ext == ".nc":
            return "netcdf"
        if ext in (".tif", ".tiff"):
            return "geotiff"
        if ext == ".mat":
            return "mat"
        raise ValueError(f"不支持的文件格式: {ext}")

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def list_variables(self) -> list[str]:
        """列出文件中所有变量名。"""
        if self.format == "hdf5":
            return self._list_hdf5_variables()
        if self.format == "netcdf":
            return self._list_netcdf_variables()
        if self.format == "geotiff":
            return ["band_1"]  # GeoTIFF 通常只有 1 个波段
        if self.format == "mat":
            return self._list_mat_variables()
        return []

    def read_variable(
        self,
        variable: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        time_index: int | None = None,
        band: int = 1,
    ) -> DataArray:
        """读取变量数据。

        Args:
            variable: 变量名 (HDF5/NetCDF/MAT)。GeoTIFF 忽略。
            bbox: 区域裁剪 (west, south, east, north)，经纬度。None 读取全部。
            time_index: 时间层索引 (NetCDF 3D+ 数据)。None 读取全部时间。
            band: 波段号 (GeoTIFF)，从 1 开始。

        Returns:
            DataArray: 统一数据结构
        """
        if self.format == "hdf5":
            return self._read_hdf5(variable, bbox)
        if self.format == "netcdf":
            return self._read_netcdf(variable, bbox, time_index)
        if self.format == "geotiff":
            return self._read_geotiff(bbox, band)
        if self.format == "mat":
            return self._read_mat(variable)
        raise ValueError(f"不支持的格式: {self.format}")

    # ------------------------------------------------------------------
    # HDF5 (SMAP)
    # ------------------------------------------------------------------

    def _list_hdf5_variables(self) -> list[str]:
        import h5py
        names: list[str] = []
        with h5py.File(self.path, "r") as f:
            f.visititems(lambda name, node: names.append(name) if isinstance(node, h5py.Dataset) else None)
        return names

    def _read_hdf5(self, variable: str | None, bbox: tuple[float, float, float, float] | None) -> DataArray:
        import h5py
        if variable is None:
            raise ValueError("HDF5 读取需要指定 variable 参数")

        with h5py.File(self.path, "r") as f:
            ds = f[variable]
            attrs = dict(ds.attrs)
            fill_value = attrs.get("_FillValue", attrs.get("missing_value", None))

            # SMAP HDF5 使用二维 lat/lon 网格 (与数据同形)
            # 尝试读取坐标变量
            lat_2d = None
            lon_2d = None
            group_prefix = variable.rsplit("/", 1)[0] if "/" in variable else ""
            for lat_name in ("latitude", "lat"):
                for prefix in [group_prefix, ""]:
                    path = f"{prefix}/{lat_name}" if prefix else lat_name
                    if path in f:
                        lat_2d = f[path][:]
                        break
                if lat_2d is not None:
                    break
            for lon_name in ("longitude", "lon"):
                for prefix in [group_prefix, ""]:
                    path = f"{prefix}/{lon_name}" if prefix else lon_name
                    if path in f:
                        lon_2d = f[path][:]
                        break
                if lon_2d is not None:
                    break

            # 读取数据
            if bbox is not None and lat_2d is not None and lon_2d is not None:
                # 区域裁剪 (SMAP 2D 坐标)
                # 先过滤坐标中的填充值 (-9999)
                lat_valid = np.where(lat_2d > -9000, lat_2d, np.nan)
                lon_valid = np.where(lon_2d > -9000, lon_2d, np.nan)
                west, south, east, north = bbox
                mask = (lat_valid >= south) & (lat_valid <= north) & (lon_valid >= west) & (lon_valid <= east)
                # 找到裁剪区域的行列范围
                rows = np.any(mask, axis=1)
                cols = np.any(mask, axis=0)
                if not rows.any() or not cols.any():
                    raise ValueError(f"bbox {bbox} 不在数据范围内")
                r0, r1 = np.where(rows)[0][[0, -1]]
                c0, c1 = np.where(cols)[0][[0, -1]]
                values = ds[r0:r1+1, c0:c1+1]
                lat_out = lat_valid[r0:r1+1, c0:c1+1]
                lon_out = lon_valid[r0:r1+1, c0:c1+1]
            else:
                values = ds[:]
                # 过滤坐标中的填充值
                lat_out = np.where(lat_2d > -9000, lat_2d, np.nan) if lat_2d is not None else None
                lon_out = np.where(lon_2d > -9000, lon_2d, np.nan) if lon_2d is not None else None

            # 填充值处理
            values = values.astype(np.float64)
            if fill_value is not None:
                values[values == fill_value] = np.nan
            # SMAP 特殊: -9999 也是填充值
            values[values == -9999] = np.nan

            return DataArray(
                values=values,
                lat=lat_out,
                lon=lon_out,
                time=None,
                crs="EPSG:4326",
                attrs=attrs,
                var_name=variable,
                file_path=str(self.path),
                file_format="hdf5",
            )

    # ------------------------------------------------------------------
    # NetCDF (ERA5, BIOMASS, CMFD)
    # ------------------------------------------------------------------

    def _list_netcdf_variables(self) -> list[str]:
        from netCDF4 import Dataset
        with Dataset(self.path) as ds:
            return list(ds.variables.keys())

    def _read_netcdf(
        self,
        variable: str | None,
        bbox: tuple[float, float, float, float] | None,
        time_index: int | None,
    ) -> DataArray:
        from netCDF4 import Dataset, num2date
        if variable is None:
            raise ValueError("NetCDF 读取需要指定 variable 参数")

        with Dataset(self.path) as ds:
            var = ds.variables[variable]
            attrs = {k: getattr(var, k) for k in var.ncattrs()}
            fill_value = attrs.get("_FillValue", attrs.get("missing_value", None))
            scale_factor = attrs.get("scale_factor", None)
            add_offset = attrs.get("add_offset", None)

            # 读取坐标变量 (支持 lat/latitude, lon/longitude)
            lat_var = self._find_coord_var(ds, ["lat", "latitude"])
            lon_var = self._find_coord_var(ds, ["lon", "longitude", "long"])
            time_var = self._find_coord_var(ds, ["time"])

            lat_1d = lat_var[:] if lat_var is not None else None
            lon_1d = lon_var[:] if lon_var is not None else None
            time_vals = None
            if time_var is not None:
                try:
                    time_vals = num2date(time_var[:], time_var.units, getattr(time_var, "calendar", "standard"))
                    time_vals = np.array([str(t) for t in time_vals])
                except (AttributeError, ValueError):
                    # ERA5 特殊: time 是字符串 "YYYYMMDD"
                    time_vals = np.array([str(t) for t in time_var[:]])

            # 确定维度顺序
            dims = var.dimensions

            # 构建 slice
            slices: list[slice] = []
            lat_slice = slice(None)
            lon_slice = slice(None)

            for dim in dims:
                if lat_var is not None and dim == lat_var.dimensions[0]:
                    if bbox is not None and lat_1d is not None:
                        south, north = bbox[1], bbox[3]
                        # 使用 boolean mask 统一处理升序和降序
                        mask = (lat_1d >= south) & (lat_1d <= north)
                        indices = np.where(mask)[0]
                        if len(indices) > 0:
                            lat_slice = slice(int(indices[0]), int(indices[-1]) + 1)
                        else:
                            lat_slice = slice(0, 0)
                    slices.append(lat_slice)
                elif lon_var is not None and dim == lon_var.dimensions[0]:
                    if bbox is not None and lon_1d is not None:
                        west, east = bbox[0], bbox[2]
                        # 处理 0-360 经度 (ERA5): 仅当 bbox 含负值时偏移
                        if lon_1d.max() > 180 and west < 0:
                            west_idx = int(np.searchsorted(lon_1d, west + 360))
                            east_idx = int(np.searchsorted(lon_1d, east + 360)) + 1
                        elif lon_1d.max() > 180 and east > 180:
                            # bbox 在 0-360 范围内，直接索引
                            west_idx = int(np.searchsorted(lon_1d, west))
                            east_idx = int(np.searchsorted(lon_1d, east)) + 1
                        else:
                            west_idx = int(np.searchsorted(lon_1d, west))
                            east_idx = int(np.searchsorted(lon_1d, east)) + 1
                        lon_slice = slice(west_idx, east_idx)
                    slices.append(lon_slice)
                elif time_var is not None and dim == time_var.dimensions[0]:
                    if time_index is not None:
                        slices.append(slice(time_index, time_index + 1))
                    else:
                        slices.append(slice(None))
                else:
                    slices.append(slice(None))

            values = var[tuple(slices)]

            # 处理时间维度
            if time_index is not None and time_vals is not None:
                time_out = np.array([time_vals[time_index]]) if time_index < len(time_vals) else None
                # 去掉时间维度 (如果只有1个时间步)
                if len(values.shape) == 3 and values.shape[0] == 1:
                    values = values[0]
            elif time_vals is not None:
                time_out = time_vals[slices[dims.index(time_var.dimensions[0])]] if time_var.dimensions[0] in dims else None
            else:
                time_out = None

            # 提取裁剪后的坐标
            lat_out = lat_1d[lat_slice] if lat_1d is not None else None
            lon_out = lon_1d[lon_slice] if lon_1d is not None else None

            # 填充值 + 比例缩放
            values = values.astype(np.float64)
            if fill_value is not None:
                values[values == fill_value] = np.nan
            # int16 特殊: -32768/-32767 也是填充值
            if values.dtype == np.int16 or (hasattr(var, 'dtype') and var.dtype == np.int16):
                values[values <= -32767] = np.nan
            if scale_factor is not None:
                values = values * float(scale_factor)
            if add_offset is not None:
                values = values + float(add_offset)

            # CRS
            crs = "EPSG:4326"
            if "crs" in ds.variables:
                crs_var = ds.variables["crs"]
                if hasattr(crs_var, "crs_wkt"):
                    crs = crs_var.crs_wkt
                elif hasattr(crs_var, "epsg_code"):
                    crs = f"EPSG:{crs_var.epsg_code}"
                elif hasattr(crs_var, "grid_mapping_name"):
                    crs = getattr(crs_var, "grid_mapping_name", "unknown")

            return DataArray(
                values=values,
                lat=lat_out,
                lon=lon_out,
                time=time_out,
                crs=crs,
                attrs=attrs,
                var_name=variable,
                file_path=str(self.path),
                file_format="netcdf",
            )

    # ------------------------------------------------------------------
    # GeoTIFF (HFP, China 1km, MCD12Q1, CLCD)
    # ------------------------------------------------------------------

    def _read_geotiff(self, bbox: tuple[float, float, float, float] | None, band: int) -> DataArray:
        import rasterio
        from rasterio.windows import Window, from_bounds

        with rasterio.open(self.path) as ds:
            attrs = {
                "width": ds.width,
                "height": ds.height,
                "count": ds.count,
                "dtypes": ds.dtypes,
                "nodata": ds.nodatavals[band - 1] if band <= len(ds.nodatavals) else None,
                "transform": ds.transform,
                "res": (ds.res[0], ds.res[1]),
            }
            crs = ds.crs.to_string() if ds.crs else None
            nodata = attrs["nodata"]

            # 区域裁剪
            if bbox is not None:
                # 对于非 WGS84 投影 (如 Mollweide, Sinusoidal)，需要先转换 bbox
                if crs and "EPSG:4326" not in crs and "WGS 84" not in crs.upper():
                    from rasterio.warp import transform_bounds
                    west, south, east, north = bbox
                    bbox_proj = transform_bounds("EPSG:4326", ds.crs, west, south, east, north)
                    window = from_bounds(*bbox_proj, ds.transform)
                else:
                    window = from_bounds(*bbox, ds.transform)
                window = window.round_offsets().round_lengths()
                # 确保窗口在数据范围内
                window = Window(
                    col_off=max(0, window.col_off),
                    row_off=max(0, window.row_off),
                    width=min(window.width, ds.width - max(0, window.col_off)),
                    height=min(window.height, ds.height - max(0, window.row_off)),
                )
                values = ds.read(band, window=window)
                # 关键修复: 存储窗口特定的 transform，而非全数据集 transform
                # 否则 SpatialAligner 重投影时会使用错误的地理变换参数
                attrs["transform"] = ds.window_transform(window)
                attrs["window"] = window
                # 计算裁剪后的坐标
                col_coords = np.arange(window.col_off, window.col_off + window.width) * ds.transform.a + ds.transform.c
                row_coords = np.arange(window.row_off, window.row_off + window.height) * ds.transform.e + ds.transform.f
                # 对于 WGS84 GeoTIFF, row_coords 是纬度, col_coords 是经度
                if crs and "EPSG:4326" in crs:
                    lat_out = row_coords
                    lon_out = col_coords
                else:
                    lat_out = row_coords  # 投影坐标 Y
                    lon_out = col_coords  # 投影坐标 X
            else:
                values = ds.read(band)
                lat_out = None
                lon_out = None

            # 填充值处理
            values = values.astype(np.float64)
            if nodata is not None:
                if np.isinf(nodata):
                    # HFP 特殊: NoData=-inf，需要用 isfinite 过滤
                    values[~np.isfinite(values)] = np.nan
                else:
                    values[values == nodata] = np.nan
            else:
                # 未声明 NoData 时的启发式检测
                dtype_str = str(ds.dtypes[band - 1])
                if "int16" in dtype_str and np.nanmin(values) <= -32767:
                    # China 1km 特殊: int16 NoData=-32768 未在元数据中声明
                    values[values <= -32767] = np.nan
            # 额外: 过滤 inf 和 NaN
            values[~np.isfinite(values)] = np.nan

            return DataArray(
                values=values,
                lat=lat_out,
                lon=lon_out,
                time=None,
                crs=crs,
                attrs=attrs,
                var_name=f"band_{band}",
                file_path=str(self.path),
                file_format="geotiff",
            )

    # ------------------------------------------------------------------
    # MAT (omega 反演结果)
    # ------------------------------------------------------------------

    def _list_mat_variables(self) -> list[str]:
        try:
            from scipy.io import whosmat
            return [name for name, _, _ in whosmat(self.path)]
        except NotImplementedError:
            import h5py
            names: list[str] = []
            with h5py.File(self.path, "r") as f:
                f.visititems(lambda name, node: names.append(name) if isinstance(node, h5py.Dataset) else None)
            return names

    def _read_mat(self, variable: str | None) -> DataArray:
        if variable is None:
            raise ValueError("MAT 读取需要指定 variable 参数")

        # 尝试 v5/v6 (scipy.io.loadmat)
        try:
            from scipy.io import loadmat
            data = loadmat(self.path)
            if variable not in data:
                raise KeyError(f"变量 {variable} 不存在于 {self.path}")
            values = np.array(data[variable])
            # 去掉 MATLAB 的冗余维度 (1, n) → (n,)
            if values.ndim >= 2 and 1 in values.shape:
                values = values.squeeze()
            # 尝试读取坐标变量 (lat/lon, 可能是 1D 或 2D)
            lat_out = self._extract_mat_coord(data, ("lat", "latitude"))
            lon_out = self._extract_mat_coord(data, ("lon", "longitude"))
            return DataArray(
                values=values.astype(np.float64),
                lat=lat_out,
                lon=lon_out,
                time=None,
                crs="EPSG:4326" if lat_out is not None else None,
                attrs={"mat_version": "v5/v6"},
                var_name=variable,
                file_path=str(self.path),
                file_format="mat",
            )
        except NotImplementedError:
            pass

        # v7.3 (h5py)
        import h5py
        with h5py.File(self.path, "r") as f:
            if variable not in f:
                raise KeyError(f"变量 {variable} 不存在于 {self.path}")
            ds = f[variable]
            attrs = dict(ds.attrs)
            values = ds[:]

            # MAT v7.3 存储为列优先 (Fortran order)，需要转置
            if values.ndim >= 2:
                values = values.T

            # 尝试读取坐标变量 (v7.3 也需转置)
            lat_out = None
            lon_out = None
            for lat_name in ("lat", "latitude"):
                if lat_name in f:
                    lat_out = np.array(f[lat_name])
                    if lat_out.ndim >= 2:
                        lat_out = lat_out.T
                    break
            for lon_name in ("lon", "longitude"):
                if lon_name in f:
                    lon_out = np.array(f[lon_name])
                    if lon_out.ndim >= 2:
                        lon_out = lon_out.T
                    break

            return DataArray(
                values=values.astype(np.float64),
                lat=lat_out,
                lon=lon_out,
                time=None,
                crs="EPSG:4326" if lat_out is not None else None,
                attrs={"mat_version": "v7.3", **attrs},
                var_name=variable,
                file_path=str(self.path),
                file_format="mat",
            )

    @staticmethod
    def _extract_mat_coord(data: dict, candidates: tuple[str, ...]) -> np.ndarray | None:
        """从 loadmat 字典中提取坐标变量。"""
        for name in candidates:
            if name in data:
                arr = np.array(data[name])
                # 去掉冗余维度
                if arr.ndim >= 2 and 1 in arr.shape:
                    arr = arr.squeeze()
                return arr
        return None

    # ------------------------------------------------------------------
    # 辅助函数
    # ------------------------------------------------------------------

    @staticmethod
    def _find_coord_var(ds, candidates: list[str]):
        """从 NetCDF Dataset 中查找坐标变量。"""
        for name in candidates:
            if name in ds.variables:
                return ds.variables[name]
        return None
