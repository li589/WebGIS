"""output_manager.py - 统一输出管理器。

整合 COG 写出、预览图生成、Parquet 写出和 manifest 组装，
为算法模块提供一站式产物输出接口。

支持双后端写出：
- 始终写入本地文件（output_root/job_id/），保持调试兼容性
- 若传入 storage_backend，同时写入远程存储（local fs / MinIO）
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
        output_root: 输出根目录（本地文件存储）
        job_id: 作业 ID
        module_name: 模块名称
        workflow_name: 工作流名称
        time_range: 时间范围字典
        region: 空间区域字典
        storage_backend: 可选，StorageBackend 实例（如 LocalFileSystemStorage /
                         MinIOStorage）用于写入远程存储。传入后产物会同时
                         写入本地和远程后端。
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

    def _write_to_backend(self, rel_path: str, data: bytes) -> str:
        """将数据写入 storage_backend（如已配置），返回远程 URI。

        Args:
            rel_path: 相对于 job_dir 的路径
            data: 二进制数据

        Returns:
            远程 URI（若 storage_backend 未配置则返回空字符串）
        """
        if self.storage_backend is None:
            return ""
        backend_path = self.storage_backend.resolve_path(self.job_id, rel_path)
        return self.storage_backend.write_bytes(backend_path, data)

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

        产物同时写入本地和 storage_backend（如已配置）。

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
                "raster": COG 写出结果（含 local_uri 和可选 remote_uri）,
                "preview": 预览图结果（如果 generate_preview=True）
            }
        """
        self._ensure_dirs()

        # 延迟导入内部组件
        if self._cog_writer is None:
            from .raster_writer import COGWriter
            self._cog_writer = COGWriter(self.job_dir, overwrite=True)

        # 写出 COG bytes
        cog_bytes, cog_meta = self._cog_writer.write_bytes(
            data,
            name,
            crs=crs,
            transform=transform,
            nodata=nodata,
            unit=unit,
            description=description,
            **cog_kwargs,
        )

        # 本地文件写入
        cog_path = self.job_dir / cog_meta["path"]
        cog_path.write_bytes(cog_bytes)
        local_raster_uri = str(cog_path.resolve().as_uri())

        # 远程存储写入
        remote_raster_uri = self._write_to_backend(cog_meta["path"], cog_bytes)

        raster_result = {
            **cog_meta,
            "local_uri": local_raster_uri,
            "uri": local_raster_uri,
        }
        if remote_raster_uri:
            raster_result["remote_uri"] = remote_raster_uri

        # 生成预览图
        preview_result: dict = {}
        if generate_preview:
            if self._preview_gen is None:
                from .raster_writer import PreviewGenerator
                self._preview_gen = PreviewGenerator(self.job_dir, preview_size)

            png_bytes, png_meta = self._preview_gen.generate_bytes(
                data,
                name,
                cmap=cmap,
                nodata=nodata,
                title=name,
            )

            # 本地文件写入
            png_path = self.job_dir / png_meta["path"]
            png_path.write_bytes(png_bytes)
            local_png_uri = str(png_path.resolve().as_uri())

            # 远程存储写入
            remote_png_uri = self._write_to_backend(png_meta["path"], png_bytes)

            preview_result = {
                **png_meta,
                "local_uri": local_png_uri,
                "uri": local_png_uri,
            }
            if remote_png_uri:
                preview_result["remote_uri"] = remote_png_uri

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

        产物同时写入本地和 storage_backend（如已配置）。

        参数：
            name: 产物名称
            df: pandas DataFrame
            description: 描述信息
            index: 是否写入索引

        返回：
            dict: TableWriter 返回的详细信息（含 local_uri 和可选 remote_uri）
        """
        self._ensure_dirs()

        # 延迟导入
        if self._table_writer is None:
            from .table_writer import TableWriter
            self._table_writer = TableWriter(self.job_dir, overwrite=True)

        parquet_bytes, parquet_meta = self._table_writer.write_bytes(
            df,
            name,
            index=index,
        )

        # 本地文件写入
        parquet_path = self.job_dir / parquet_meta["path"]
        parquet_path.write_bytes(parquet_bytes)
        local_uri = str(parquet_path.resolve().as_uri())

        # 远程存储写入
        remote_uri = self._write_to_backend(parquet_meta["path"], parquet_bytes)

        result = {
            **parquet_meta,
            "uri": local_uri,
            "local_uri": local_uri,
        }
        if remote_uri:
            result["remote_uri"] = remote_uri

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

        manifest 同时写入本地和 storage_backend（如已配置）。

        参数：
            extra: 额外字段，会合并到 manifest 的 extra 字段

        返回：
            dict: manifest 内容
        """
        self._ensure_manifest_builder()

        if extra:
            self._manifest_builder.extra.update(extra)

        json_bytes, manifest = self._manifest_builder.build_bytes()

        # 本地文件写入
        manifest_path = self.job_dir / "manifest.json"
        manifest_path.write_bytes(json_bytes)
        local_uri = str(manifest_path.resolve().as_uri())

        result: dict[str, Any] = {"local_uri": local_uri}
        remote_uri = self._write_to_backend("manifest.json", json_bytes)
        if remote_uri:
            result["remote_uri"] = remote_uri

        return manifest

    def get_output_dir(self) -> Path:
        """获取当前 job 的输出目录。

        返回：
            Path: 输出目录路径
        """
        self._ensure_dirs()
        return self.job_dir
