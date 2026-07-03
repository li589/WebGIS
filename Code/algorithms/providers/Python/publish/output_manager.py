"""output_manager.py - 统一输出管理器。

整合 COG 写出、预览图生成、Parquet 写出和 manifest 组装，
为算法模块提供一站式产物输出接口。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

# ---------------------------------------------------------------------------
# 类型检查
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from rasterio import Affine
    from pandas import DataFrame

# ---------------------------------------------------------------------------
# OutputManager
# ---------------------------------------------------------------------------

class OutputManager:
    """统一输出管理器。

    整合 COG 写出、预览图生成、Parquet 写出和 manifest 组装，
    为算法模块提供一站式产物输出接口。

    参数：
        output_root: 输出根目录
        job_id: 作业 ID
        module_name: 模块名称
        workflow_name: 工作流名称
        time_range: 时间范围字典
        region: 空间区域字典
        storage_backend: 可选，存储后端（如 MinIO 客户端）用于写入远程存储
    """

    def __init__(
        self,
        output_root: Path | str,
        job_id: str,
        *,
        module_name: str = "",
        workflow_name: str = "",
        time_range: Optional[dict] = None,
        region: Optional[dict] = None,
        storage_backend: Optional[Any] = None,
    ):
        self.output_root = Path(output_root)
        self.job_id = job_id
        self.module_name = module_name
        self.workflow_name = workflow_name
        self.time_range = time_range
        self.region = region
        self.storage_backend = storage_backend
        # 创建 job 专用子目录
        self.job_dir: Path = self.output_root / job_id

        # 内部组件（延迟导入避免循环依赖）
        self._cog_writer: Optional[Any] = None
        self._preview_gen: Optional[Any] = None
        self._table_writer: Optional[Any] = None

        # manifest 构建器
        self._manifest_builder: Optional[Any] = None

    def _ensure_dirs(self) -> None:
        """确保所有子目录已创建。"""
        self.job_dir.mkdir(parents=True, exist_ok=True)

    def write_raster(
        self,
        name: str,
        data: np.ndarray,
        *,
        crs: str = "EPSG:4326",
        transform: Optional["Affine"] = None,
        nodata: Optional[float] = None,
        unit: str = "",
        description: str = "",
        generate_preview: bool = True,
        cmap: str = "viridis",
        preview_size: tuple[int, int] = (512, 512),
        **cog_kwargs: Any,
    ) -> dict:
        """写出栅格并自动生成预览图和 manifest 条目。

        参数：
            name: 产物名称
            data: 栅格数据（2D 或 3D numpy 数组）
            crs: 坐标系
            transform: 仿射变换对象
            nodata: NoData 值
            unit: 数据单位
            description: 描述信息
            generate_preview: 是否生成预览图
            cmap: 配色方案
            preview_size: 预览图尺寸
            **cog_kwargs: COG 写入额外参数

        返回：
            dict: {
                "raster": COG 写出结果,
                "preview": 预览图结果（如果 generate_preview=True）
            }
        """
        self._ensure_dirs()

        # 延迟导入内部组件
        if self._cog_writer is None:
            from .raster_writer import COGWriter
            self._cog_writer = COGWriter(self.job_dir, overwrite=True)

        # 写出 COG
        result = self._cog_writer.write(
            data,
            name,
            crs=crs,
            transform=transform,
            nodata=nodata,
            unit=unit,
            description=description,
            **cog_kwargs,
        )
        raster_result = result

        # 生成预览图
        preview_result: dict = {}
        if generate_preview:
            if self._preview_gen is None:
                from .raster_writer import PreviewGenerator
                self._preview_gen = PreviewGenerator(self.job_dir, preview_size)
            preview_result = self._preview_gen.generate(
                data,
                name,
                cmap=cmap,
                nodata=nodata,
                title=name,
            )

        # 添加 manifest 条目
        self._add_manifest_raster(name, raster_result, preview_result, unit, description)

        return {
            "raster": raster_result,
            "preview": preview_result,
        }

    def write_table(
        self,
        name: str,
        df: "DataFrame",
        *,
        description: str = "",
        index: bool = False,
    ) -> dict:
        """写出表格并添加 manifest 条目。

        参数：
            name: 产物名称
            df: pandas DataFrame
            description: 描述信息
            index: 是否写入索引

        返回：
            dict: TableWriter 返回的详细信息
        """
        self._ensure_dirs()

        # 延迟导入
        if self._table_writer is None:
            from .table_writer import TableWriter
            self._table_writer = TableWriter(self.job_dir, overwrite=True)

        result = self._table_writer.write(
            df,
            name,
            index=index,
        )

        # 添加 manifest 条目
        self._add_manifest_table(name, result, description)

        return result

    def _add_manifest_raster(
        self,
        name: str,
        raster_result: dict,
        preview_result: dict,
        unit: str,
        description: str,
    ) -> None:
        """添加栅格产物到 manifest。"""
        self._ensure_manifest_builder()
        self._manifest_builder.add_raster(
            name=name,
            path=raster_result["path"],
            var_name=name,
            unit=unit,
            description=description,
            preview_path=preview_result.get("path"),
            crs=raster_result["crs"],
            nodata=raster_result["nodata"],
            bounds=raster_result["bounds"],
            size_bytes=raster_result["size_bytes"],
            preview_size_bytes=preview_result.get("size_bytes", 0),
        )

    def _add_manifest_table(
        self,
        name: str,
        table_result: dict,
        description: str,
    ) -> None:
        """添加表格产物到 manifest。"""
        self._ensure_manifest_builder()
        self._manifest_builder.add_table(
            name=name,
            path=table_result["path"],
            description=description,
            rows=table_result["rows"],
            columns=table_result["columns"],
            size_bytes=table_result["size_bytes"],
        )

    def _ensure_manifest_builder(self) -> None:
        """确保 manifest 构建器已初始化。"""
        if self._manifest_builder is None:
            from .manifest_builder import ManifestBuilder

            self._manifest_builder = ManifestBuilder(
                job_id=self.job_id,
                module_name=self.module_name,
                workflow_name=self.workflow_name,
                time_range=self.time_range,
                region=self.region,
            )

    def add_diagnostic(self, key: str, value: Any) -> None:
        """添加诊断信息。

        参数：
            key: 诊断键名
            value: 诊断值
        """
        self._ensure_manifest_builder()
        self._manifest_builder.add_diagnostic(key, value)

    def write_manifest(self, extra: Optional[dict] = None) -> dict:
        """写出 manifest.json，返回 manifest 内容。

        参数：
            extra: 额外字段，会合并到 manifest 的 extra 字段

        返回：
            dict: manifest 内容
        """
        self._ensure_manifest_builder()

        if extra:
            self._manifest_builder.extra.update(extra)

        return self._manifest_builder.build(self.job_dir)

    def get_output_dir(self) -> Path:
        """获取当前 job 的输出目录。

        返回：
            Path: 输出目录路径
        """
        self._ensure_dirs()
        return self.job_dir
