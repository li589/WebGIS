"""
算法模块输出协调层。

为算法模块提供统一的产物输出接口，整合：
- MAT 文件写出（MATLAB 兼容性保留）
- COG 栅格写出（WebGIS 地图渲染）
- PNG 预览图生成（前端快速预览）
- Parquet 表格写出（前端图表消费）
- JSON manifest 组装（产物清单）

使用方式（在模块 execute() 方法中）：
    from output.coordinator import OutputCoordinator

    coordinator = OutputCoordinator(
        job_id=ctx.request.job_id,
        output_dir=output_dir,
        module_name=self.name,
        workflow_name="...",
        time_range={"start": str(ctx.request.time_range.start), "end": str(ctx.request.time_range.end)},
        region={"bbox": ctx.request.region.bbox.__dict__} if ctx.request.region else None,
    )

    # 写出栅格（COG + preview + manifest 条目）
    coordinator.write_raster(
        name="ndvi_20230101",
        data=ndvi_array,          # numpy array (lat, lon)
        crs="EPSG:4326",
        nodata=-9999.0,
        unit="NDVI",
        description="VIIRS NDVI 16天合成",
        date_label="2023-01-01",
    )

    # 或写出表格
    coordinator.write_table(
        name="station_sm_daily",
        df=pandas_df,
        description="站点日均土壤水分",
    )

    # 最后写出 manifest
    manifest = coordinator.build_manifest()
    # → output_dir/manifest.json
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

logger = logging.getLogger(__name__)


# ===========================================================================
# 辅助：检测可选依赖
# ===========================================================================

_PUBLISH_AVAILABLE = False
_COGBOOK_AVAILABLE = False

try:
    from publish import COGWriter, ManifestBuilder, OutputManager, PreviewGenerator, TableWriter
    _PUBLISH_AVAILABLE = True
except ImportError:
    COGWriter = None
    PreviewGenerator = None
    TableWriter = None
    ManifestBuilder = None
    OutputManager = None

try:
    from affine import Affine
    _COGBOOK_AVAILABLE = True
except ImportError:
    Affine = None


# ===========================================================================
# 工具函数
# ===========================================================================


def _is_float_array(arr: "np.ndarray") -> bool:
    """判断是否为浮点类型数组"""
    import numpy as np
    return np.issubdtype(arr.dtype, np.floating)


def _ensure_contiguous(arr: "np.ndarray") -> "np.ndarray":
    """确保数组是 C 连续"""
    if not arr.flags["C_CONTIGUOUS"]:
        return arr.copy(order="C")
    return arr


def _get_default_nodata(dtype: "np.dtype") -> float:
    """根据数据类型返回合理的默认 nodata 值"""
    import numpy as np
    if np.issubdtype(dtype, np.floating):
        return -9999.0
    return -9999


def _estimate_bounds_from_transform(
    transform: "Affine",
    width: int,
    height: int,
) -> tuple[float, float, float, float]:
    """
    根据仿射变换估算地理范围（度为单位，假设 EPSG:4326）。

    transform 格式：Affine(a, b, c, d, e, f) 其中：
        c, f = 左上角坐标 (lon, lat)
        a    = 像素分辨率（lon 方向，通常为正）
        e    = 像素分辨率（lat 方向，通常为负）
    """
    if Affine is None:
        # fallback: 返回全中国大致范围
        return (73.0, 18.0, 135.0, 53.0)

    a, b, c, d, e, f, _, _, _ = transform
    west = c
    east = c + a * width
    # 纬度方向（e 通常为负，f 是左上角纬度）
    north = f
    south = f + e * height
    return (west, south, east, north)


def _generate_preview_from_array(
    arr: "np.ndarray",
    output_path: Path,
    *,
    cmap: str = "viridis",
    nodata: float | None = None,
    title: str = "",
    size: tuple[int, int] = (512, 512),
) -> bool:
    """使用 matplotlib 生成伪彩色预览图（独立函数，不依赖 PreviewGenerator）"""
    try:
        import matplotlib
        import matplotlib.pyplot as plt
        import numpy as np

        arr_f = arr.astype(np.float32)
        if nodata is not None:
            mask = arr_f == nodata
            arr_f = arr_f.copy()
            arr_f[mask] = np.nan

        # 2%-98% 拉伸
        vmin, vmax = np.nanpercentile(arr_f, (2, 98))
        if vmin >= vmax:
            vmin, vmax = np.nanmin(arr_f), np.nanmax(arr_f)

        fig, ax = plt.subplots(figsize=(size[0] / 100, size[1] / 100), dpi=100)
        ax.axis("off")
        if title:
            title_font = _resolve_preview_title_font(matplotlib)
            if not (_contains_non_ascii(title) and title_font is None):
                title_kwargs: dict[str, Any] = {"fontsize": 10, "pad": 4}
                if title_font is not None:
                    title_kwargs["fontproperties"] = title_font
                ax.set_title(title, **title_kwargs)
        im = ax.imshow(
            arr_f,
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            origin="upper",
        )
        fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
        fig.tight_layout(pad=0.1)
        fig.savefig(output_path, format="png", bbox_inches="tight", dpi=100, facecolor="white")
        plt.close(fig)
        return True
    except Exception:
        return False


def _contains_non_ascii(text: str) -> bool:
    return any(ord(ch) > 127 for ch in text)


@lru_cache(maxsize=1)
def _resolve_preview_title_font(matplotlib_module=None):
    try:
        matplotlib_ref = matplotlib_module
        if matplotlib_ref is None:
            import matplotlib as matplotlib_ref
        font_manager = matplotlib_ref.font_manager
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


# ===========================================================================
# 栅格写出器（独立实现，不依赖 publish 层可选依赖）
# ===========================================================================


class RasterPublisher:
    """
    栅格数据写出器。

    输出：
    - COG GeoTIFF（WebGIS 可直接加载）
    - PNG 预览图（前端快速预览）
    """

    def __init__(
        self,
        output_dir: Path,
        *,
        crs: str = "EPSG:4326",
        compress: str = "deflate",
        preview_size: tuple[int, int] = (512, 512),
        preview_cmap: str = "viridis",
        overwrite: bool = False,
    ):
        self.output_dir = Path(output_dir)
        self.crs = crs
        self.compress = compress
        self.preview_size = preview_size
        self.preview_cmap = preview_cmap
        self.overwrite = overwrite

    def publish(
        self,
        data: "np.ndarray",
        name: str,
        *,
        transform: "Affine | None" = None,
        nodata: float | None = None,
        unit: str = "",
        description: str = "",
        generate_preview: bool = True,
        pixel_resolution: float = 1.0,
        **kwargs,
    ) -> dict[str, Any]:
        """
        将栅格数据写出为 COG + 可选 preview。

        参数：
            data: 2D numpy 数组，shape (height, width)
            name: 产物名称（不含扩展名）
            transform: 地理变换对象，如果为 None 则自动生成
            nodata: NoData 值，默认根据数据类型自动推断
            unit: 数据单位
            description: 数据描述
            generate_preview: 是否生成预览图
            pixel_resolution: 像素分辨率（度），默认 1.0

        返回：
            dict: 包含 path / uri / preview_path / uri_preview / shape / dtype / bounds 等字段
        """
        import numpy as np

        self.output_dir.mkdir(parents=True, exist_ok=True)
        data = _ensure_contiguous(np.asarray(data))

        # 形状规范化
        if data.ndim == 3 and data.shape[0] == 1:
            data = data[0]
        if data.ndim != 2:
            raise ValueError(f"栅格数据必须为 2D，当前 shape={data.shape}")

        height, width = data.shape

        # nodata
        if nodata is None:
            nodata = _get_default_nodata(data.dtype)

        # 生成 transform
        if transform is None:
            if Affine is not None:
                # EPSG:4326，假设左上角 (west, north)，像素分辨率 pixel_resolution
                transform = Affine(pixel_resolution, 0.0, 0.0, 0.0, -pixel_resolution, 0.0)

        # 估算 bounds
        if transform is not None:
            bounds = _estimate_bounds_from_transform(transform, width, height)
        else:
            bounds = (0.0, 0.0, float(width) * pixel_resolution, float(height) * pixel_resolution)

        # 写入 COG
        cog_path = self.output_dir / f"{name}.cog.tif"
        result: dict[str, Any] = {
            "name": name,
            "cog_path": str(cog_path),
            "cog_uri": f"file://{cog_path.resolve()}",
            "shape": (height, width),
            "dtype": str(data.dtype),
            "crs": self.crs,
            "nodata": nodata,
            "unit": unit,
            "description": description,
            "bounds": bounds,
            "format": "COG",
        }

        if _PUBLISH_AVAILABLE and COGWriter is not None:
            try:
                writer = COGWriter(output_dir=self.output_dir, overwrite=self.overwrite)
                cog_result = writer.write(
                    data=data,
                    output_name=f"{name}.cog",
                    crs=self.crs,
                    transform=transform,
                    nodata=nodata,
                    compress=self.compress,
                    description=description,
                    unit=unit,
                )
                result.update(cog_result)
                result["cog_path"] = str(cog_path)
                result["cog_uri"] = f"file://{cog_path.resolve()}"
                result["path"] = str(cog_path)
                result["uri"] = f"file://{cog_path.resolve()}"
            except Exception as e:
                logger.warning(f"COG 写出失败: {e}，跳过 COG 输出")
                # 回退：写入普通 GeoTIFF
                result = self._write_plain_geotiff(data, cog_path, transform, nodata, result)
        else:
            result = self._write_plain_geotiff(data, cog_path, transform, nodata, result)

        if result.get("size_bytes", 0) == 0:
            logger.warning(f"COG 写出文件为空: {cog_path}")

        # 生成预览图
        if generate_preview:
            preview_path = self.output_dir / f"{name}.preview.png"
            if _PUBLISH_AVAILABLE and PreviewGenerator is not None:
                try:
                    gen = PreviewGenerator(output_dir=self.output_dir, size=self.preview_size)
                    preview_result = gen.generate(
                        data=data,
                        output_name=f"{name}.preview",
                        cmap=self.preview_cmap,
                        nodata=nodata,
                        title=description or name,
                    )
                    result["preview_path"] = str(preview_path)
                    result["preview_uri"] = f"file://{preview_path.resolve()}"
                    result["preview_size"] = preview_result.get("size_bytes", 0)
                except Exception as e:
                    logger.warning(f"预览图生成失败: {e}，使用备用方法")
                    ok = _generate_preview_from_array(
                        data, preview_path,
                        cmap=self.preview_cmap, nodata=nodata, title=description or name,
                        size=self.preview_size,
                    )
                    if ok:
                        result["preview_path"] = str(preview_path)
                        result["preview_uri"] = f"file://{preview_path.resolve()}"
                        result["preview_size"] = preview_path.stat().st_size
            else:
                ok = _generate_preview_from_array(
                    data, preview_path,
                    cmap=self.preview_cmap, nodata=nodata, title=description or name,
                    size=self.preview_size,
                )
                if ok:
                    result["preview_path"] = str(preview_path)
                    result["preview_uri"] = f"file://{preview_path.resolve()}"
                    result["preview_size"] = preview_path.stat().st_size

        return result

    def _write_plain_geotiff(
        self,
        data: "np.ndarray",
        output_path: Path,
        transform,
        nodata: float | None,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """回退：使用 rasterio 写入普通 GeoTIFF（无 COG 优化）"""
        try:
            import rasterio
            from rasterio.transform import from_bounds

            if transform is not None and Affine is not None:
                arr_transform = rasterio.Affine(
                    transform.a, transform.b, transform.c,
                    transform.d, transform.e, transform.f,
                )
            else:
                height, width = data.shape
                west, south, east, north = result.get("bounds", (0, 0, width, height))
                arr_transform = from_bounds(west, south, east, north, width, height)

            profile = {
                "driver": "GTiff",
                "height": data.shape[0],
                "width": data.shape[1],
                "count": 1,
                "dtype": str(data.dtype),
                "crs": self.crs,
                "transform": arr_transform,
                "compress": self.compress,
                "nodata": nodata,
            }

            with rasterio.open(output_path, "w", **profile) as dst:
                dst.write(data, 1)
                if result.get("description"):
                    dst.update_tags( DESCRIPTION=result["description"] )
                if result.get("unit"):
                    dst.update_tags( UNIT=result["unit"] )

            result["path"] = str(output_path)
            result["uri"] = f"file://{output_path.resolve()}"
            result["size_bytes"] = output_path.stat().st_size
            return result
        except ImportError:
            # rasterio 不可用，输出为 numpy .npy 文件
            np_path = output_path.with_suffix(".npy")
            import numpy as np
            np.save(np_path, data)
            logger.warning(f"rasterio 不可用，栅格保存为 numpy 格式: {np_path}")
            result["path"] = str(np_path)
            result["uri"] = f"file://{np_path.resolve()}"
            result["size_bytes"] = np_path.stat().st_size
            result["warning"] = "rasterio 不可用，数据保存为 numpy 格式"
            return result
        except Exception as e:
            logger.error(f"GeoTIFF 写出失败: {e}")
            result["error"] = str(e)
            return result


# ===========================================================================
# 表格写出器
# ===========================================================================


class TablePublisher:
    """表格数据写出器，输出 Parquet 格式。"""

    def __init__(
        self,
        output_dir: Path,
        *,
        overwrite: bool = False,
        compression: str = "snappy",
    ):
        self.output_dir = Path(output_dir)
        self.overwrite = overwrite
        self.compression = compression

    def publish(
        self,
        df: "pd.DataFrame",
        name: str,
        *,
        description: str = "",
        index: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        将 DataFrame 写出为 Parquet。

        参数：
            df: pandas DataFrame
            name: 产物名称（不含扩展名）
            description: 数据描述
            index: 是否写出索引
            metadata: 额外的 Parquet 元数据

        返回：
            dict: 包含 path / uri / rows / columns / size_bytes 等字段
        """
        import numpy as np
        import pandas as pd

        self.output_dir.mkdir(parents=True, exist_ok=True)
        parquet_path = self.output_dir / f"{name}.parquet"

        meta = dict(metadata or {})
        meta["description"] = description

        if _PUBLISH_AVAILABLE and TableWriter is not None:
            try:
                writer = TableWriter(output_dir=self.output_dir, overwrite=self.overwrite)
                result = writer.write(
                    df=df,
                    output_name=name,
                    index=index,
                    compression=self.compression,
                    metadata=meta,
                )
                abs_path = self.output_dir / Path(result["path"]).name
                result["name"] = name
                result["path"] = str(abs_path)
                result["uri"] = f"file://{abs_path.resolve()}"
                result["format"] = "Parquet"
                result["description"] = description
                result["metadata"] = meta
                return result
            except Exception as e:
                logger.warning(f"TableWriter 写出失败: {e}，使用 pandas 原生写出")
                pass

        # pandas 原生写出
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            table = pa.Table.from_pandas(df)
            pq.write_table(
                table,
                str(parquet_path),
                compression=self.compression,
            )
        except ImportError:
            # pyarrow 不可用，直接用 pandas 原生 parquet 支持（内部用 pyarrow）
            try:
                df.to_parquet(parquet_path, compression=self.compression)
            except Exception as e:
                # pandas 内部也依赖 pyarrow，尝试 csv 降级
                csv_path = parquet_path.with_suffix(".csv")
                df.to_csv(csv_path, index=False)
                result = {
                    "name": name,
                    "path": str(csv_path),
                    "uri": f"file://{csv_path.resolve()}",
                    "rows": len(df),
                    "columns": list(df.columns),
                    "size_bytes": csv_path.stat().st_size,
                    "description": description,
                    "metadata": meta,
                    "format": "CSV (pyarrow unavailable, fallback)",
                }
                return result

        result = {
            "name": name,
            "path": str(parquet_path),
            "uri": f"file://{parquet_path.resolve()}",
            "rows": len(df),
            "columns": list(df.columns),
            "size_bytes": parquet_path.stat().st_size,
            "description": description,
            "metadata": meta,
            "format": "Parquet",
        }
        return result


# ===========================================================================
# Manifest 清单组装器
# ===========================================================================


class ManifestPublisher:
    """产物清单组装与写出。"""

    def __init__(
        self,
        job_id: str,
        output_dir: Path,
        *,
        module_name: str = "",
        workflow_name: str = "",
        time_range: dict[str, str] | None = None,
        region: dict[str, Any] | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.job_id = job_id
        self.module_name = module_name
        self.workflow_name = workflow_name
        self.time_range = time_range
        self.region = region
        self._products: list[dict[str, Any]] = []
        self._diagnostics: dict[str, Any] = {}
        self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def add_raster(
        self,
        name: str,
        path: str,
        *,
        uri: str = "",
        layer_type: str = "raster",
        var_name: str = "",
        unit: str = "",
        description: str = "",
        preview_path: str = "",
        preview_uri: str = "",
        shape: tuple[int, int] | None = None,
        dtype: str = "",
        crs: str = "",
        bounds: tuple | None = None,
        size_bytes: int = 0,
        **kwargs,
    ):
        """添加栅格产物"""
        product = {
            "name": name,
            "type": layer_type,
            "path": path,
            "uri": uri or f"file://{Path(path).resolve()}" if path else "",
            "var_name": var_name,
            "unit": unit,
            "description": description,
            "preview": {
                "path": preview_path,
                "uri": preview_uri or f"file://{Path(preview_path).resolve()}" if preview_path else "",
            },
            "shape": shape,
            "dtype": dtype,
            "crs": crs,
            "bounds": bounds,
            "size_bytes": size_bytes,
        }
        product.update(kwargs)
        self._products.append(product)

    def add_table(
        self,
        name: str,
        path: str,
        *,
        uri: str = "",
        layer_type: str = "table",
        description: str = "",
        rows: int = 0,
        columns: list[str] | None = None,
        size_bytes: int = 0,
        **kwargs,
    ):
        """添加表格产物"""
        product = {
            "name": name,
            "type": layer_type,
            "path": path,
            "uri": uri or f"file://{Path(path).resolve()}" if path else "",
            "description": description,
            "rows": rows,
            "columns": columns or [],
            "size_bytes": size_bytes,
        }
        product.update(kwargs)
        self._products.append(product)

    def add_mat(
        self,
        name: str,
        path: str,
        *,
        uri: str = "",
        variable: str = "",
        description: str = "MATLAB 兼容格式",
        size_bytes: int = 0,
        **kwargs,
    ):
        """添加 MAT 格式产物"""
        product = {
            "name": name,
            "type": "mat",
            "path": path,
            "uri": uri or f"file://{Path(path).resolve()}" if path else "",
            "variable": variable,
            "description": description,
            "size_bytes": size_bytes,
            "format": "MAT",
        }
        product.update(kwargs)
        self._products.append(product)

    def add_json(
        self,
        name: str,
        path: str,
        *,
        uri: str = "",
        description: str = "",
        size_bytes: int = 0,
        **kwargs,
    ):
        """添加 JSON 格式产物"""
        product = {
            "name": name,
            "type": "json",
            "path": path,
            "uri": uri or f"file://{Path(path).resolve()}" if path else "",
            "description": description,
            "size_bytes": size_bytes,
        }
        product.update(kwargs)
        self._products.append(product)

    def add_diagnostic(self, key: str, value: Any):
        """添加诊断信息"""
        self._diagnostics[key] = value

    def add_product(self, product: dict[str, Any]):
        """直接添加产物字典"""
        self._products.append(product)

    def build(self) -> dict[str, Any]:
        """
        构建并写出 manifest.json。

        返回 manifest 字典内容。
        """
        manifest = {
            "job_id": self.job_id,
            "created_at": self.created_at,
            "module_name": self.module_name,
            "workflow_name": self.workflow_name,
            "time_range": self.time_range,
            "region": self.region,
            "products": self._products,
            "diagnostics": self._diagnostics,
            "product_count": len(self._products),
        }
        return manifest

    def write(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """构建并写出 manifest.json 到文件。"""
        manifest = self.build()
        if extra:
            manifest.update(extra)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self.output_dir / "manifest.json"

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        manifest["manifest_path"] = str(manifest_path)
        manifest["manifest_uri"] = f"file://{manifest_path.resolve()}"
        return manifest

    @property
    def product_count(self) -> int:
        return len(self._products)

    @property
    def diagnostics(self) -> dict[str, Any]:
        return dict(self._diagnostics)


# ===========================================================================
# 统一输出协调器（整合以上三者）
# ===========================================================================


class OutputCoordinator:
    """
    统一输出协调器。

    为算法模块提供一站式产物输出接口，整合：
    - MAT 文件（保留）
    - COG 栅格（WebGIS 地图渲染）
    - PNG 预览图（前端快速预览）
    - Parquet 表格（前端图表消费）
    - JSON manifest（产物清单）
    """

    def __init__(
        self,
        job_id: str,
        output_dir: Path | str,
        *,
        module_name: str = "",
        workflow_name: str = "",
        time_range: dict[str, str] | None = None,
        region: dict[str, Any] | None = None,
        crs: str = "EPSG:4326",
        pixel_resolution: float = 0.01,
        preview_cmap: str = "viridis",
        preview_size: tuple[int, int] = (512, 512),
        compress: str = "deflate",
        overwrite: bool = True,
    ):
        self.job_id = job_id
        self.output_dir = Path(output_dir)
        self.module_name = module_name
        self.workflow_name = workflow_name
        self.time_range = time_range
        self.region = region
        self.crs = crs
        self.pixel_resolution = pixel_resolution
        self.preview_cmap = preview_cmap
        self.preview_size = preview_size
        self.compress = compress
        self.overwrite = overwrite

        self._raster_pub = RasterPublisher(
            output_dir=self.output_dir,
            crs=self.crs,
            compress=self.compress,
            preview_size=self.preview_size,
            preview_cmap=self.preview_cmap,
            overwrite=self.overwrite,
        )
        self._table_pub = TablePublisher(
            output_dir=self.output_dir,
            overwrite=self.overwrite,
        )
        self._manifest_pub = ManifestPublisher(
            job_id=self.job_id,
            output_dir=self.output_dir,
            module_name=self.module_name,
            workflow_name=self.workflow_name,
            time_range=self.time_range,
            region=self.region,
        )

    def write_raster(
        self,
        name: str,
        data: "np.ndarray",
        *,
        transform: "Affine | None" = None,
        nodata: float | None = None,
        unit: str = "",
        description: str = "",
        var_name: str = "",
        generate_preview: bool = True,
        **kwargs,
    ) -> dict[str, Any]:
        """
        写出栅格数据（COG + preview）并添加 manifest 条目。

        返回栅格写出结果（包含 cog_path / preview_path 等）。
        """
        result = self._raster_pub.publish(
            data=data,
            name=name,
            transform=transform,
            nodata=nodata,
            unit=unit,
            description=description,
            generate_preview=generate_preview,
            pixel_resolution=self.pixel_resolution,
        )

        # 添加到 manifest
        # 推断 format: 如果文件扩展名是 .cog.tif 则为 COG，否则为 GeoTIFF
        cog_or_tif_path = result.get("path") or result.get("cog_path", "")
        fmt = "COG" if ".cog.tif" in cog_or_tif_path else "GeoTIFF"
        self._manifest_pub.add_raster(
            name=name,
            path=cog_or_tif_path,
            uri=result.get("uri", result.get("cog_uri", "")),
            layer_type="raster",
            var_name=var_name or unit,
            unit=unit,
            description=description,
            preview_path=result.get("preview_path", ""),
            preview_uri=result.get("preview_uri", ""),
            shape=result.get("shape"),
            dtype=result.get("dtype", ""),
            crs=self.crs,
            bounds=result.get("bounds"),
            size_bytes=result.get("size_bytes", 0),
            format=fmt,
        )

        return result

    def write_table(
        self,
        name: str,
        df: "pd.DataFrame",
        *,
        description: str = "",
        **kwargs,
    ) -> dict[str, Any]:
        """写出表格数据（Parquet）并添加 manifest 条目。"""
        result = self._table_pub.publish(
            df=df,
            name=name,
            description=description,
            **kwargs,
        )

        self._manifest_pub.add_table(
            name=name,
            path=result.get("path", ""),
            uri=result.get("uri", ""),
            layer_type="table",
            description=description,
            rows=result.get("rows", 0),
            columns=result.get("columns", []),
            size_bytes=result.get("size_bytes", 0),
            format=result.get("format", "Parquet"),
        )

        return result

    def add_mat(
        self,
        name: str,
        path: Path | str,
        *,
        variable: str = "",
        description: str = "MATLAB 兼容格式",
    ):
        """将已有的 MAT 文件添加到 manifest。"""
        p = Path(path)
        self._manifest_pub.add_mat(
            name=name,
            path=str(p),
            variable=variable,
            description=description,
            size_bytes=p.stat().st_size if p.exists() else 0,
        )

    def add_diagnostic(self, key: str, value: Any):
        """添加诊断信息"""
        self._manifest_pub.add_diagnostic(key, value)

    def build_manifest(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """构建并写出 manifest.json。"""
        return self._manifest_pub.write(extra=extra)

    def get_output_dir(self) -> Path:
        """获取输出目录"""
        return self.output_dir

    @property
    def product_count(self) -> int:
        return self._manifest_pub.product_count

    @property
    def manifest_products(self) -> list[dict[str, Any]]:
        """获取当前已收集的 manifest 产品列表"""
        return self._manifest_pub._products

    @property
    def diagnostics(self) -> dict[str, Any]:
        return self._manifest_pub.diagnostics
