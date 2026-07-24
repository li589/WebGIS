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


def _compute_bounds(
    transform: "Affine", width: int, height: int
) -> tuple[float, float, float, float]:
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
            "rasterio 未安装，无法使用 COGWriter。" " 请运行: pip install rasterio"
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

    def write_bytes(
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
    ) -> tuple[bytes, dict]:
        """将 numpy 数组写出为 COG 格式 bytes 和元数据（不写文件）。

        参数：
            data: 2D 或 3D numpy 数组
            output_name: 输出文件名（不含扩展名）
            crs: 坐标系
            transform: rasterio transform 对象
            nodata: NoData 值
            dtype: 输出数据类型
            compress: 压缩算法，默认 "deflate"
            description: 栅格描述
            unit: 数据单位
            **profile_overrides: COG 写入额外参数

        返回：
            (bytes, dict): COG 文件字节数据和元数据字典。
                元数据: {"path": str, "shape": tuple, "dtype": str, "crs": str,
                         "nodata": float|None, "unit": str, "bounds": tuple, "size_bytes": int}
        """
        rasterio, Affine = _check_rasterio()

        # 规范化数组
        bands_data, is_single_band = _normalize_array(data)
        count, height, width = bands_data.shape

        # 确定 dtype
        out_dtype = np.dtype(dtype) if dtype else bands_data.dtype
        out_dtype_str = str(out_dtype)

        # 自动设置 nodata
        nodata_val = nodata if nodata is not None else _auto_nodata(out_dtype)

        # 生成默认 transform
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
        }

        # 如果有单位信息，写入到 Tags 中
        tags: dict[str, str] = {}
        if unit:
            tags["单位"] = unit
            tags["unit"] = unit

        # 合并用户提供的额外参数
        profile.update(profile_overrides)

        # 写入内存缓冲区
        from io import BytesIO

        buf = BytesIO()
        with rasterio.open(buf, "w", **profile) as dst:
            dst.write(bands_data)
            if description:
                dst.update_tags(description=description)
            if unit:
                dst.update_tags(unit=unit)
            if tags:
                dst.update_tags(**tags)

        cog_bytes = buf.getvalue()
        if len(cog_bytes) == 0:
            raise IOError("COG 写入失败，缓冲区为空")

        bounds = _compute_bounds(transform, width, height)
        rel_path = f"{output_name}.tif"

        metadata = {
            "path": rel_path,
            "shape": (height, width) if is_single_band else (count, height, width),
            "dtype": out_dtype_str,
            "crs": crs_normalized,
            "nodata": nodata_val,
            "unit": unit,
            "bounds": bounds,
            "size_bytes": len(cog_bytes),
        }
        return cog_bytes, metadata

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
        """将 numpy 数组写出为 COG 格式 GeoTIFF 文件（兼容旧接口）。"""
        cog_bytes, metadata = self.write_bytes(
            data,
            output_name,
            crs=crs,
            transform=transform,
            nodata=nodata,
            dtype=dtype,
            compress=compress,
            description=description,
            unit=unit,
            **profile_overrides,
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_file = self.output_dir / f"{output_name}.tif"
        if output_file.exists() and not self.overwrite:
            raise FileExistsError(f"文件已存在（overwrite=False）: {output_file}")
        output_file.write_bytes(cog_bytes)
        file_size = output_file.stat().st_size
        if file_size == 0:
            raise IOError(f"写入失败，文件大小为 0: {output_file}")
        return {**metadata, "uri": str(output_file.resolve().as_uri())}


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

    def generate_bytes(
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
    ) -> tuple[bytes, dict]:
        """从栅格数据生成 PNG bytes 和元数据（不写文件）。

        参数：
            data: 2D numpy 数组
            output_name: 输出文件名（不含扩展名）
            cmap: colormap 名称
            nodata: NoData 值
            vmin/vmax: 拉伸范围
            title: 图像标题
            overlay_extent: 经纬度范围 (west, south, east, north)

        返回：
            (bytes, dict): PNG 字节数据和元数据字典。
                元数据: {"path": str, "size": tuple, "size_bytes": int}
        """
        matplotlib, plt, cm = _check_matplotlib()

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

        plot_data = data.astype(np.float64, copy=True)
        if nodata is not None:
            plot_data[plot_data == nodata] = np.nan

        if vmin is None or vmax is None:
            valid_data = plot_data[~np.isnan(plot_data)]
            if valid_data.size == 0:
                vmin_calc, vmax_calc = 0.0, 1.0
            else:
                vmin_calc = (
                    vmin if vmin is not None else float(np.percentile(valid_data, 2))
                )
                vmax_calc = (
                    vmax if vmax is not None else float(np.percentile(valid_data, 98))
                )
            if vmin_calc == vmax_calc:
                vmin_calc = float(np.nanmin(valid_data)) if valid_data.size > 0 else 0.0
                vmax_calc = vmin_calc + 1.0
        else:
            vmin_calc, vmax_calc = vmin, vmax

        fig_w, fig_h = self.size[0] / 100, self.size[1] / 100
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=100)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        masked_data = np.ma.masked_invalid(plot_data)
        im = ax.imshow(
            masked_data,
            cmap=cmap,
            vmin=vmin_calc,
            vmax=vmax_calc,
            aspect="equal",
        )

        ax.set_xticks([])
        ax.set_yticks([])

        if title:
            title_font = _resolve_title_font()
            if not (_contains_non_ascii(title) and title_font is None):
                title_kwargs: dict[str, Any] = {"fontsize": 8, "pad": 2}
                if title_font is not None:
                    title_kwargs["fontproperties"] = title_font
                ax.set_title(title, **title_kwargs)

        if overlay_extent is not None:
            west, south, east, north = overlay_extent
            ax.set_xlim(west, east)
            ax.set_ylim(south, north)

        if fig_w > 1.5 and fig_h > 1.5:
            cbar = fig.colorbar(
                im, ax=ax, orientation="vertical", fraction=0.05, pad=0.02
            )
            cbar.ax.tick_params(labelsize=6)

        fig.tight_layout(pad=0.1)

        from io import BytesIO

        buf = BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=100,
            bbox_inches="tight",
            facecolor="white",
            edgecolor="none",
        )
        plt.close(fig)
        png_bytes = buf.getvalue()
        if len(png_bytes) == 0:
            raise IOError("预览图生成失败，缓冲区为空")
        rel_path = f"{output_name}.png"
        return png_bytes, {
            "path": rel_path,
            "size": self.size,
            "size_bytes": len(png_bytes),
        }

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
        """从栅格数据生成 PNG 缩略图文件（兼容旧接口）。"""
        png_bytes, metadata = self.generate_bytes(
            data,
            output_name,
            cmap=cmap,
            nodata=nodata,
            vmin=vmin,
            vmax=vmax,
            title=title,
            overlay_extent=overlay_extent,
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_file = self.output_dir / f"{output_name}.png"
        output_file.write_bytes(png_bytes)
        file_size = output_file.stat().st_size
        if file_size == 0:
            raise IOError("预览图写入失败，文件大小为 0")
        return {**metadata, "uri": str(output_file.resolve().as_uri())}
