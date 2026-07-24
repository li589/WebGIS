"""空间对齐工具 — 重投影/重采样到统一网格。

支持将不同分辨率/投影的数据重采样到统一目标网格:
  - EASE-Grid 2.0 9km (SMAP 兼容, EPSG:6933)
  - WGS84 0.25° (ERA5 兼容)
  - WGS84 1km 中国区域

使用示例:
    aligner = SpatialAligner()
    data, lat, lon = aligner.align_to_smap_grid(
        Path("I:/Geograph_DataSet/Weather/ERA5_2018_SMCI-T7.nc"),
        variable="SMCI",
        bbox=CHINA_BBOX,
    )
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

# 支持独立运行
_PROVIDERS_DIR = Path(__file__).resolve().parent.parent
if str(_PROVIDERS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROVIDERS_DIR))

# noqa 说明：需先完成 sys.path 引导（支持脚本独立运行）后再导入包内模块，故此处 E402 为有意为之。
from data_access.universal_reader import UniversalDataReader, CHINA_BBOX, DataArray  # noqa: E402


# 重采样方法映射
_RESAMPLING_MAP = {
    "nearest": "nearest",
    "bilinear": "bilinear",
    "cubic": "cubic",
    "average": "average",
}


def _get_resampling_enum(method: str):
    """获取 rasterio 重采样枚举值。"""
    from rasterio.enums import Resampling

    return {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
        "average": Resampling.average,
    }.get(method, Resampling.bilinear)


class SpatialAligner:
    """空间对齐工具 — 重投影/重采样到统一网格。"""

    def resample_to_grid(
        self,
        source_data: np.ndarray,
        source_crs: str,
        source_transform: Any,
        target_crs: str,
        target_width: int,
        target_height: int,
        target_transform: Any,
        resampling: str = "nearest",
    ) -> np.ndarray:
        """将源数据重采样到目标网格。

        Args:
            source_data: 源数据数组 (2D)
            source_crs: 源坐标系字符串
            source_transform: 源仿射变换 (rasterio.Affine)
            target_crs: 目标坐标系字符串
            target_width: 目标宽度 (像素)
            target_height: 目标高度 (像素)
            target_transform: 目标仿射变换
            resampling: 重采样方法 (nearest/bilinear/cubic/average)

        Returns:
            目标网格上的数据数组 (target_height, target_width)
        """
        from rasterio.warp import reproject

        # 准备输出数组
        dst_data = np.full((target_height, target_width), np.nan, dtype=np.float64)

        # 执行重投影
        reproject(
            source=source_data,
            destination=dst_data,
            src_transform=source_transform,
            src_crs=source_crs,
            dst_transform=target_transform,
            dst_crs=target_crs,
            resampling=_get_resampling_enum(resampling),
            src_nodata=np.nan,
            dst_nodata=np.nan,
        )

        return dst_data

    def create_target_grid(
        self,
        bbox: tuple[float, float, float, float],
        resolution_deg: float,
    ) -> tuple[str, int, int, Any]:
        """创建 WGS84 目标网格定义。

        Args:
            bbox: (west, south, east, north) 经纬度范围
            resolution_deg: 分辨率 (度)

        Returns:
            (crs, width, height, transform)
        """
        from rasterio.transform import from_bounds

        west, south, east, north = bbox
        width = int((east - west) / resolution_deg)
        height = int((north - south) / resolution_deg)
        transform = from_bounds(west, south, east, north, width, height)
        return "EPSG:4326", width, height, transform

    def align_to_grid(
        self,
        source_path: Path,
        variable: str | None = None,
        target_crs: str = "EPSG:4326",
        target_resolution: float = 0.25,
        bbox: tuple[float, float, float, float] = CHINA_BBOX,
        resampling: str = "bilinear",
        time_index: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """将任意数据对齐到指定 WGS84 网格。

        Args:
            source_path: 源文件路径
            variable: 变量名 (HDF5/NetCDF/MAT)
            target_crs: 目标坐标系 (默认 WGS84)
            target_resolution: 目标分辨率 (度, 默认 0.25°)
            bbox: 区域范围
            resampling: 重采样方法
            time_index: 时间层索引 (NetCDF 3D 数据)

        Returns:
            (aligned_data, lat_1d, lon_1d) — 对齐后的数据和一维坐标
        """
        from rasterio.transform import from_bounds

        # 读取源数据
        reader = UniversalDataReader(source_path)
        data = reader.read_variable(variable=variable, bbox=bbox, time_index=time_index)

        # 创建目标网格
        west, south, east, north = bbox
        target_width = int((east - west) / target_resolution)
        target_height = int((north - south) / target_resolution)
        target_transform = from_bounds(
            west, south, east, north, target_width, target_height
        )

        # 如果源数据是 GeoTIFF，直接使用 rasterio 重投影
        if data.file_format == "geotiff":
            # GeoTIFF 已经有 CRS 和 transform 信息
            src_transform = data.attrs.get("transform")
            src_crs = data.crs or "EPSG:4326"

            if src_transform is not None:
                aligned = self.resample_to_grid(
                    source_data=data.values,
                    source_crs=src_crs,
                    source_transform=src_transform,
                    target_crs=target_crs,
                    target_width=target_width,
                    target_height=target_height,
                    target_transform=target_transform,
                    resampling=resampling,
                )
            else:
                # 没有 transform 信息，使用简单重采样
                aligned = self._simple_resample(
                    data.values, target_height, target_width
                )
        else:
            # HDF5/NetCDF/MAT — 使用基于坐标的简单重采样
            aligned = self._coordinate_based_resample(
                data, target_height, target_width, bbox, resampling
            )

        # 生成目标坐标
        lat_1d = np.linspace(north, south, target_height)
        lon_1d = np.linspace(west, east, target_width)

        return aligned, lat_1d, lon_1d

    def align_to_smap_grid(
        self,
        source_path: Path,
        variable: str | None = None,
        bbox: tuple[float, float, float, float] = CHINA_BBOX,
        resampling: str = "bilinear",
        time_index: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """将任意数据对齐到 SMAP 兼容网格 (WGS84 0.25°)。

        SMAP EASE-Grid 2.0 全球网格为 1624×3856 (9km)，
        但在中国区域使用 WGS84 0.25° 更便于多源数据融合。

        Returns:
            (aligned_data, lat_1d, lon_1d)
        """
        return self.align_to_grid(
            source_path=source_path,
            variable=variable,
            target_crs="EPSG:4326",
            target_resolution=0.25,
            bbox=bbox,
            resampling=resampling,
            time_index=time_index,
        )

    def align_multiple_datasets(
        self,
        datasets: list[dict],
        target_resolution: float = 0.25,
        bbox: tuple[float, float, float, float] = CHINA_BBOX,
        resampling: str = "bilinear",
    ) -> dict[str, np.ndarray]:
        """将多个数据集对齐到同一网格。

        Args:
            datasets: 数据集列表 [{path, variable, name, time_index?}, ...]
            target_resolution: 目标分辨率 (度)
            bbox: 区域范围
            resampling: 重采样方法

        Returns:
            {name: aligned_data} 字典，所有数据具有相同形状和坐标
        """
        results: dict[str, np.ndarray] = {}
        for ds_spec in datasets:
            name = ds_spec["name"]
            path = Path(ds_spec["path"])
            variable = ds_spec.get("variable")
            time_index = ds_spec.get("time_index")

            try:
                aligned, lat, lon = self.align_to_grid(
                    source_path=path,
                    variable=variable,
                    target_resolution=target_resolution,
                    bbox=bbox,
                    resampling=resampling,
                    time_index=time_index,
                )
                results[name] = aligned
                print(
                    f"  ✓ {name}: shape={aligned.shape}, "
                    f"valid={np.isfinite(aligned).sum()}/{aligned.size}"
                )
            except Exception as e:
                print(f"  ✗ {name}: {type(e).__name__}: {e}")
                results[name] = None

        return results

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _simple_resample(
        self,
        data: np.ndarray,
        target_height: int,
        target_width: int,
    ) -> np.ndarray:
        """简单最近邻重采样 (不涉及投影变换)。"""
        from scipy.ndimage import zoom

        src_h, src_w = data.shape
        if src_h == target_height and src_w == target_width:
            return data

        v_factor = target_height / src_h
        h_factor = target_width / src_w
        # 使用最近邻避免插值产生伪值
        return zoom(data, (v_factor, h_factor), order=0, mode="nearest")

    def _coordinate_based_resample(
        self,
        data: DataArray,
        target_height: int,
        target_width: int,
        bbox: tuple[float, float, float, float],
        resampling: str,
    ) -> np.ndarray:
        """基于坐标的网格重采样 (用于 HDF5/NetCDF/MAT)。

        使用 scipy.interpolate.griddata 进行不规则网格到规则网格的转换。
        """
        from scipy.interpolate import griddata

        values = data.values
        lat = data.lat
        lon = data.lon

        if lat is None or lon is None:
            # 没有坐标信息，使用简单重采样
            return self._simple_resample(values, target_height, target_width)

        west, south, east, north = bbox

        # 构建目标网格
        target_lat = np.linspace(north, south, target_height)
        target_lon = np.linspace(west, east, target_width)
        target_lon_2d, target_lat_2d = np.meshgrid(target_lon, target_lat)

        if lat.ndim == 1 and lon.ndim == 1:
            # 一维坐标 — 使用规则网格索引
            lon_2d, lat_2d = np.meshgrid(lon, lat)
        else:
            # 二维坐标 (如 SMAP)
            lat_2d = lat
            lon_2d = lon

        # 展平数据用于 griddata
        mask = np.isfinite(values) & np.isfinite(lat_2d) & np.isfinite(lon_2d)
        if not mask.any():
            return np.full((target_height, target_width), np.nan)

        points = np.column_stack([lon_2d[mask], lat_2d[mask]])
        values_flat = values[mask]

        # 插值方法映射
        method = "nearest" if resampling == "nearest" else "linear"

        result = griddata(
            points,
            values_flat,
            (target_lon_2d, target_lat_2d),
            method=method,
            fill_value=np.nan,
        )

        return result
