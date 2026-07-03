"""raster_writer.py - COG 栅格写出和预览图生成。

提供 COGWriter 和 PreviewGenerator 两个类，
分别负责将 numpy 数组写出为 Cloud Optimized GeoTIFF 格式
和生成前端可用的 PNG 缩略图。
"""

from __future__ import annotations

import warnings
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

if TYPE_CHECKING:
    from rasterio import Affine

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

# 标准 EPSG CRS 前缀
_EPSG_PREFIXES = ("EPSG:", "epsg:", "http://epsg.io/", "https://epsg.io/")


def _is_standard_epsg(crs_str: str) -> bool:
    """检查 CRS 字符串是否为标准 EPSG 格式（如 EPSG:4326）。"""
    return any(crs_str.startswith(p) for p in _EPSG_PREFIXES)


def _normalize_crs(crs_str: str) -> str:
    """将 CRS 字符串标准化为 "EPSG:XXXX" 格式。"""
    if not _is_standard_epsg(crs_str):
        return crs_str
    upper = crs_str.upper()
    if upper.startswith("EPSG:"):
        return upper
    if "/" in upper:
        code = upper.rstrip("/").split("/")[-1]
        if code.isdigit():
            return f"EPSG:{code}"
    return crs_str


def _auto_nodata(dtype: np.dtype) -> float | None:
    """根据数据类型自动选择 NoData 值。"""
    if np.issubdtype(dtype, np.floating):
        return float(np.nan)
    if np.issubdtype(dtype, np.integer):
        return -9999.0
    return None


def _normalize_array(data: np.ndarray) -> tuple[np.ndarray, bool]:
    """规范化数组形状为 (bands, height, width)，返回 (数组, 是否为单波段)。"""
    data = np.asarray(data)
    if data.ndim == 2:
        return data[np.newaxis, :, :], True
    if data.ndim == 3:
        if data.shape[0] in (1, 3, 4) and data.shape[2] in (1, 3, 4):
            data = np.transpose(data, (2, 0, 1))
        return data, data.shape[0] == 1
    raise ValueError(f"不支持的数组维度: {data.ndim}D，仅支持 2D 或 3D 数组")


def _compute_bounds(transform: "Affine", width: int, height: int) -> tuple[float, float, float, float]:
    """根据仿射变换计算地理范围 (west, south, east, north)。"""
    west = transform.xoff
    east = transform.xoff + transform.a * width
    north = transform.yoff
    south = transform.yoff + transform.e * height
    return (west, south, east, north)


# ---------------------------------------------------------------------------
# 延迟依赖检查
# ---------------------------------------------------------------------------

def _check_rasterio() -> Any:
    """检查并导入 rasterio，失败时给出友好提示。"""
    try:
        import rasterio
        from rasterio import Affine
        return rasterio, Affine
    except ImportError as e:
        raise ImportError(
            "rasterio 未安装，无法使用 COGWriter。"
            " 请运行: pip install rasterio"
        ) from e


def _check_matplotlib() -> Any:
    """检查并导入 matplotlib 相关模块，失败时给出友好提示。"""
    try:
        import matplotlib
        import matplotlib.pyplot as plt
        from matplotlib import cm
        return matplotlib, plt, cm
    except ImportError as e:
        raise ImportError(
            "matplotlib 未安装，无法使用 PreviewGenerator。"
            " 请运行: pip install matplotlib"
        ) from e


def _contains_non_ascii(text: str) -> bool:
    return any(ord(ch) > 127 for ch in text)


@lru_cache(maxsize=1)
def _resolve_title_font():
    """优先选择可用的中文字体，避免 matplotlib 标题渲染时产生缺字告警。"""
    try:
        matplotlib, _, _ = _check_matplotlib()
        font_manager = matplotlib.font_manager
    except Exception:
        return None

    candidates = (
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "WenQuanYi Zen Hei",
        "Arial Unicode MS",
    )
    for family in candidates:
        try:
            font_path = font_manager.findfont(family, fallback_to_default=False)
        except Exception:
            continue
        if font_path and Path(font_path).exists():
            return font_manager.FontProperties(fname=font_path)
    return None


# ---------------------------------------------------------------------------
# COGWriter
# ---------------------------------------------------------------------------

class COGWriter:
    """COG (Cloud Optimized GeoTIFF) 栅格写出器。

    将 numpy 数组写出为符合 COG 规范的 GeoTIFF，
    支持地理参考信息、元数据和多种压缩算法。
    """

    def __init__(self, output_dir: Path | str, overwrite: bool = False):
        self.output_dir = Path(output_dir)
        self.overwrite = overwrite

    def write(
        self,
        data: np.ndarray,
        output_name: str,
        *,
        crs: str = "EPSG:4326",
        transform: Optional["Affine"] = None,
        nodata: Optional[float] = None,
        dtype: Optional[str] = None,
        compress: str = "deflate",
        description: str = "",
        unit: str = "",
        **profile_overrides: Any,
    ) -> dict:
        """将 numpy 数组写出为 COG 格式 GeoTIFF。

        参数：
            data: 2D 或 3D numpy 数组，shape 为 (bands, height, width) 或 (height, width)
            output_name: 输出文件名（不含扩展名）
            crs: 坐标系，默认为 EPSG:4326
            transform: rasterio transform 对象，如果为 None 则生成全 1 的仿射变换
            nodata: NoData 值，默认为 np.nan（浮点型）或 -9999（整型）
            dtype: 输出数据类型，如 "float32", "int16"，默认为 data.dtype
            compress: 压缩算法，默认 "deflate"
            description: 栅格描述
            unit: 数据单位，如 "mm", "kg/m2", "K"

        返回：
            dict: {
                "path": str,           # 相对输出目录的路径
                "uri": str,             # 完整 URI
                "shape": tuple,         # (height, width) 或 (bands, height, width)
                "dtype": str,           # 数据类型
                "crs": str,             # 坐标系
                "nodata": float|None,  # NoData 值
                "unit": str,            # 数据单位
                "bounds": tuple,        # (west, south, east, north)
                "size_bytes": int,      # 文件大小
            }
        """
        rasterio, Affine = _check_rasterio()

        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 规范化数组
        bands_data, is_single_band = _normalize_array(data)
        count, height, width = bands_data.shape

        # 确定 dtype
        out_dtype = np.dtype(dtype) if dtype else bands_data.dtype
        out_dtype_str = str(out_dtype)

        # 自动设置 nodata
        nodata_val = nodata if nodata is not None else _auto_nodata(out_dtype)

        # 生成默认 transform（以 (0,0) 为左上角，1.0 像素分辨率）
        if transform is None:
            transform = Affine(1.0, 0.0, 0.0, 0.0, -1.0, 0.0)

        # CRS 格式检查与标准化
        if not _is_standard_epsg(crs):
            warnings.warn(
                f"CRS 格式可能不符合标准 EPSG 格式: {crs!r}。"
                f"建议使用 'EPSG:XXXX' 格式。",
                UserWarning,
                stacklevel=2,
            )
        crs_normalized = _normalize_crs(crs)

        # 构造输出路径
        output_file = self.output_dir / f"{output_name}.tif"
        if output_file.exists() and not self.overwrite:
            raise FileExistsError(f"文件已存在（overwrite=False）: {output_file}")

        # 构造 rasterio profile
        profile: dict[str, Any] = {
            "driver": "COG",
            "height": height,
            "width": width,
            "count": count,
            "dtype": out_dtype_str,
            "crs": crs_normalized,
            "transform": transform,
            "compress": compress,
            "BIGTIFF": "IF_SAFER",
            "nodata": nodata_val,
            "description": description,
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
        }

        # 如果有单位信息，写入到 Tags 中
        tags: dict[str, str] = {}
        if unit:
            tags["单位"] = unit
            tags["unit"] = unit

        # 合并用户提供的额外参数
        profile.update(profile_overrides)

        # 写入文件
        with rasterio.open(output_file, "w", **profile) as dst:
            dst.write(bands_data)
            if description:
                dst.update_tags(description=description)
            if unit:
                dst.update_tags(unit=unit)
            if tags:
                dst.update_tags(**tags)

        # 验证文件
        if not output_file.exists():
            raise IOError(f"写入失败，文件不存在: {output_file}")
        file_size = output_file.stat().st_size
        if file_size == 0:
            raise IOError(f"写入失败，文件大小为 0: {output_file}")

        bounds = _compute_bounds(transform, width, height)
        rel_path = str(output_file.relative_to(self.output_dir))

        return {
            "path": rel_path,
            "uri": str(output_file.resolve().as_uri()),
            "shape": (height, width) if is_single_band else (count, height, width),
            "dtype": out_dtype_str,
            "crs": crs_normalized,
            "nodata": nodata_val,
            "unit": unit,
            "bounds": bounds,
            "size_bytes": file_size,
        }


# ---------------------------------------------------------------------------
# PreviewGenerator
# ---------------------------------------------------------------------------

class PreviewGenerator:
    """栅格缩略图生成器。

    使用 matplotlib 将栅格数据渲染为伪彩色 PNG 图像，
    支持多种 colormap、自动拉伸和 colorbar。
    """

    def __init__(self, output_dir: Path | str, size: tuple[int, int] = (256, 256)):
        """初始化预览图生成器。

        参数：
            output_dir: 输出目录
            size: 预览图尺寸 (width, height)，单位像素
        """
        self.output_dir = Path(output_dir)
        self.size = size  # (width, height)

    def generate(
        self,
        data: np.ndarray,
        output_name: str,
        *,
        cmap: str = "viridis",
        nodata: Optional[float] = None,
        vmin: Optional[float] = None,
        vmax: Optional[float] = None,
        title: str = "",
        overlay_extent: Optional[tuple] = None,
    ) -> dict:
        """从栅格数据生成 PNG 缩略图。

        参数：
            data: 2D numpy 数组，shape 为 (height, width)
            output_name: 输出文件名（不含扩展名）
            cmap: colormap 名称，默认 viridis
            nodata: NoData 值，会渲染为灰色或透明
            vmin: 最小拉伸值，默认为数据 2% 分位数
            vmax: 最大拉伸值，默认为数据 98% 分位数
            title: 图像标题
            overlay_extent: 经纬度范围 (west, south, east, north)

        返回：
            dict: {
                "path": str,
                "uri": str,
                "size": tuple,
                "size_bytes": int,
            }
        """
        matplotlib, plt, cm = _check_matplotlib()

        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 规范化数组（确保 2D）
        data = np.asarray(data)
        if data.ndim == 3:
            if data.shape[0] == 1:
                data = data[0, :, :]
            elif data.shape[2] == 1:
                data = data[:, :, 0]
            else:
                data = data.mean(axis=0)
        elif data.ndim != 2:
            raise ValueError(f"不支持的数据维度: {data.ndim}D，仅支持 2D 数组")

        # 复制数据避免修改原数组
        plot_data = data.astype(np.float64, copy=True)

        # 处理 nodata
        if nodata is not None:
            plot_data[plot_data == nodata] = np.nan

        # 计算拉伸范围
        if vmin is None or vmax is None:
            valid_data = plot_data[~np.isnan(plot_data)]
            if valid_data.size == 0:
                vmin_calc, vmax_calc = 0.0, 1.0
            else:
                vmin_calc = vmin if vmin is not None else float(np.percentile(valid_data, 2))
                vmax_calc = vmax if vmax is not None else float(np.percentile(valid_data, 98))
            if vmin_calc == vmax_calc:
                vmin_calc = float(np.nanmin(valid_data)) if valid_data.size > 0 else 0.0
                vmax_calc = vmin_calc + 1.0
        else:
            vmin_calc, vmax_calc = vmin, vmax

        # 创建图形
        fig_w, fig_h = self.size[0] / 100, self.size[1] / 100
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=100)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        # 使用 masked array 处理 nodata 显示为灰色
        masked_data = np.ma.masked_invalid(plot_data)

        # 渲染图像
        im = ax.imshow(
            masked_data,
            cmap=cmap,
            vmin=vmin_calc,
            vmax=vmax_calc,
            aspect="equal",
        )

        # 移除坐标轴刻度
        ax.set_xticks([])
        ax.set_yticks([])

        # 添加标题
        if title:
            title_font = _resolve_title_font()
            if not (_contains_non_ascii(title) and title_font is None):
                title_kwargs: dict[str, Any] = {"fontsize": 8, "pad": 2}
                if title_font is not None:
                    title_kwargs["fontproperties"] = title_font
                ax.set_title(title, **title_kwargs)

        # 添加经纬度边框
        if overlay_extent is not None:
            west, south, east, north = overlay_extent
            ax.set_xlim(west, east)
            ax.set_ylim(south, north)

        # 添加 colorbar（缩小尺寸以适应缩略图）
        if fig_w > 1.5 and fig_h > 1.5:
            cbar = fig.colorbar(im, ax=ax, orientation="vertical", fraction=0.05, pad=0.02)
            cbar.ax.tick_params(labelsize=6)

        # 紧凑布局
        fig.tight_layout(pad=0.1)

        # 保存图像
        output_file = self.output_dir / f"{output_name}.png"
        fig.savefig(
            output_file,
            format="png",
            dpi=100,
            bbox_inches="tight",
            facecolor="white",
            edgecolor="none",
        )
        plt.close(fig)

        # 验证文件
        if not output_file.exists():
            raise IOError(f"预览图写入失败: {output_file}")
        file_size = output_file.stat().st_size
        if file_size == 0:
            raise IOError(f"预览图写入失败，文件大小为 0: {output_file}")

        rel_path = str(output_file.relative_to(self.output_dir))

        return {
            "path": rel_path,
            "uri": str(output_file.resolve().as_uri()),
            "size": self.size,
            "size_bytes": file_size,
        }
