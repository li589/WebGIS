"""可视化模块 — 地图、时间序列、散点图"""

from __future__ import annotations

import os
import sys

# 支持独立运行: 将上级目录(Python providers 根目录)加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 使用 Agg 后端，避免 GUI 依赖
import matplotlib.pyplot as plt
import numpy as np

# 尝试导入 cartopy (可选，用于地理投影); 不可用时回退到普通 matplotlib
try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    _HAS_CARTOPY = True
except Exception:
    _HAS_CARTOPY = False


def _grid_vectors_from_2d(
    lat: np.ndarray,
    lon: np.ndarray,
    n_lat: int,
    n_lon: int,
) -> tuple[np.ndarray, np.ndarray]:
    """从 2D 坐标数组提取 1D 规则网格向量。

    用于 SMAP 等 2D 坐标含填充值的场景: 取每行/每列的有效中位数作为坐标。
    若整列/整行无效，则用线性插值外推。
    """
    # lat: 提取每行的有效中位数 → 1D (n_lat,)
    if lat.ndim == 2:
        lat_1d = np.empty(n_lat, dtype=np.float64)
        for i in range(n_lat):
            row = lat[i]
            valid = row[np.isfinite(row)]
            lat_1d[i] = float(np.median(valid)) if valid.size > 0 else np.nan
        lat_1d = _fix_1d_coords(lat_1d)
    else:
        lat_1d = _fix_1d_coords(lat)

    # lon: 提取每列的有效中位数 → 1D (n_lon,)
    if lon.ndim == 2:
        lon_1d = np.empty(n_lon, dtype=np.float64)
        for j in range(n_lon):
            col = lon[:, j]
            valid = col[np.isfinite(col)]
            lon_1d[j] = float(np.median(valid)) if valid.size > 0 else np.nan
        lon_1d = _fix_1d_coords(lon_1d)
    else:
        lon_1d = _fix_1d_coords(lon)

    return lat_1d, lon_1d


def _fix_1d_coords(coords: np.ndarray) -> np.ndarray:
    """修复 1D 坐标数组中的 NaN: 用线性插值 + 边界外推填充。"""
    coords = np.asarray(coords, dtype=np.float64)
    if np.all(np.isfinite(coords)):
        return coords
    if not np.any(np.isfinite(coords)):
        # 全部无效: 用等间距填充
        return np.linspace(0.0, 1.0, coords.size)

    valid_mask = np.isfinite(coords)
    valid_idx = np.where(valid_mask)[0]
    invalid_idx = np.where(~valid_mask)[0]
    # 用有效点线性插值
    coords[invalid_idx] = np.interp(invalid_idx, valid_idx, coords[valid_idx])
    return coords


class DataVisualization:
    """数据可视化"""

    def _save_or_show(
        self,
        fig: plt.Figure,
        output_path: Path | None,
    ) -> None:
        """统一处理图像保存或显示"""
        if output_path is None:
            plt.show()
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def plot_spatial_map(
        self,
        data: np.ndarray,
        lat: np.ndarray | None = None,
        lon: np.ndarray | None = None,
        title: str = "",
        cmap: str = "RdYlBu_r",
        vmin: float | None = None,
        vmax: float | None = None,
        output_path: Path | None = None,
        figsize: tuple = (12, 8),
    ) -> None:
        """绘制空间地图

        - 使用 matplotlib + cartopy 或 basemap
        - 支持等经纬度投影
        - 添加 colorbar
        - 如果 output_path 为 None 则显示，否则保存
        """
        data = np.asarray(data, dtype=np.float64)
        if data.ndim != 2:
            raise ValueError("空间地图数据必须是 2D 数组")

        n_lat, n_lon = data.shape
        if lat is None:
            lat = np.linspace(90.0, -90.0, n_lat)
        if lon is None:
            lon = np.linspace(-180.0, 180.0, n_lon)
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)

        # 处理含 NaN/非有限值的坐标 (如 SMAP 2D 坐标含 -9999 填充)
        # 策略: 2D 坐标 → 提取 1D 规则网格; 1D 坐标 → 用边界外推
        if lat.ndim == 2 or lon.ndim == 2:
            lat_1d, lon_1d = _grid_vectors_from_2d(lat, lon, n_lat, n_lon)
            lat = lat_1d
            lon = lon_1d
        else:
            # 1D 坐标含 NaN: 用有效值线性外推
            if not np.all(np.isfinite(lat)):
                lat = _fix_1d_coords(lat)
            if not np.all(np.isfinite(lon)):
                lon = _fix_1d_coords(lon)

        fig = plt.figure(figsize=figsize)

        if _HAS_CARTOPY:
            # 使用 cartopy 地理投影
            ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
            ax.coastlines(resolution="110m")
            ax.add_feature(cfeature.LAND, facecolor="lightgray", alpha=0.3)
            ax.add_feature(cfeature.OCEAN, facecolor="lightblue", alpha=0.3)
            mesh = ax.pcolormesh(
                lon,
                lat,
                data,
                cmap=cmap,
                vmin=vmin,
                vmax=vmax,
                transform=ccrs.PlateCarree(),
                shading="auto",
            )
            ax.set_extent(
                [float(np.min(lon)), float(np.max(lon)),
                 float(np.min(lat)), float(np.max(lat))],
                crs=ccrs.PlateCarree(),
            )
            gl = ax.gridlines(draw_labels=True, linewidth=0.5, alpha=0.5, linestyle="--")
            gl.top_labels = False
            gl.right_labels = False
        else:
            # 回退到普通 matplotlib (无地理投影)
            ax = fig.add_subplot(1, 1, 1)
            lon_mesh, lat_mesh = np.meshgrid(lon, lat)
            mesh = ax.pcolormesh(
                lon_mesh,
                lat_mesh,
                data,
                cmap=cmap,
                vmin=vmin,
                vmax=vmax,
                shading="auto",
            )
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")

        if title:
            ax.set_title(title)
        fig.colorbar(mesh, ax=ax, orientation="vertical", shrink=0.8)

        fig.tight_layout()
        self._save_or_show(fig, output_path)

    def plot_timeseries(
        self,
        data: np.ndarray,
        time: np.ndarray | None = None,
        title: str = "",
        ylabel: str = "",
        output_path: Path | None = None,
        figsize: tuple = (12, 6),
    ) -> None:
        """绘制时间序列

        - 支持单条或多条线 (data 为 2D 时)
        - 自动格式化时间轴
        """
        data = np.asarray(data, dtype=np.float64)
        if data.ndim == 1:
            data = data.reshape(1, -1)
        elif data.ndim != 2:
            raise ValueError("时间序列数据必须是 1D 或 2D 数组")

        n_series, n_time = data.shape
        if time is None:
            time = np.arange(n_time, dtype=np.float64)
        else:
            time = np.asarray(time, dtype=np.float64)

        fig, ax = plt.subplots(figsize=figsize)
        for i in range(n_series):
            ax.plot(
                time,
                data[i],
                marker="o",
                markersize=3,
                linewidth=1.2,
                label=f"Series {i + 1}",
            )

        # 自动格式化时间轴 (若为日期类型则旋转刻度标签)
        if np.issubdtype(time.dtype, np.datetime64):
            fig.autofmt_xdate()

        if n_series > 1:
            ax.legend(loc="best")
        if title:
            ax.set_title(title)
        if ylabel:
            ax.set_ylabel(ylabel)
        ax.set_xlabel("Time")
        ax.grid(True, linestyle="--", alpha=0.5)
        fig.tight_layout()

        self._save_or_show(fig, output_path)

    def plot_scatter(
        self,
        x: np.ndarray,
        y: np.ndarray,
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        regression: bool = True,
        output_path: Path | None = None,
        figsize: tuple = (8, 8),
    ) -> None:
        """绘制散点图 (含回归线)"""
        x = np.asarray(x, dtype=np.float64).ravel()
        y = np.asarray(y, dtype=np.float64).ravel()
        if x.size != y.size:
            raise ValueError("x 与 y 长度必须一致")

        # 仅保留有限值样本
        valid = np.isfinite(x) & np.isfinite(y)
        x_valid = x[valid]
        y_valid = y[valid]

        fig, ax = plt.subplots(figsize=figsize)
        ax.scatter(x_valid, y_valid, s=10, alpha=0.6, edgecolors="none")

        # 拟合并绘制回归线 (需要至少 2 个样本且 x 有变化)
        if regression and x_valid.size >= 2 and np.ptp(x_valid) > 0:
            slope, intercept = np.polyfit(x_valid, y_valid, 1)
            x_line = np.linspace(float(np.min(x_valid)), float(np.max(x_valid)), 100)
            y_line = slope * x_line + intercept
            ax.plot(
                x_line,
                y_line,
                color="red",
                linewidth=1.5,
                label=f"y={slope:.4f}x+{intercept:.4f}",
            )
            ax.legend(loc="best")

        if title:
            ax.set_title(title)
        if xlabel:
            ax.set_xlabel(xlabel)
        if ylabel:
            ax.set_ylabel(ylabel)
        ax.grid(True, linestyle="--", alpha=0.5)
        fig.tight_layout()

        self._save_or_show(fig, output_path)

    def plot_histogram(
        self,
        data: np.ndarray,
        title: str = "",
        bins: int = 50,
        output_path: Path | None = None,
    ) -> None:
        """绘制直方图"""
        data = np.asarray(data, dtype=np.float64).ravel()
        valid = data[np.isfinite(data)]

        fig, ax = plt.subplots(figsize=(10, 6))
        if valid.size > 0:
            ax.hist(valid, bins=bins, color="steelblue", edgecolor="black", alpha=0.8)
        if title:
            ax.set_title(title)
        ax.set_xlabel("Value")
        ax.set_ylabel("Frequency")
        ax.grid(True, linestyle="--", alpha=0.5, axis="y")
        fig.tight_layout()

        self._save_or_show(fig, output_path)
