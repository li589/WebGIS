"""manifest_builder.py - 产物清单组装器。

提供 ManifestBuilder 类，用于构建和组装算法产物的清单信息，
最终输出为格式化的 JSON manifest 文件。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# ManifestBuilder
# ---------------------------------------------------------------------------

class ManifestBuilder:
    """产物清单构建器。

    用于组装和管理算法模块输出的各类产物（栅格、表格、JSON）信息，
    并最终生成格式化的 manifest.json 文件。
    """

    def __init__(
        self,
        job_id: str,
        *,
        module_name: str = "",
        workflow_name: str = "",
        time_range: Optional[dict] = None,
        region: Optional[dict] = None,
        extra: Optional[dict] = None,
    ):
        """初始化产物清单构建器。

        参数：
            job_id: 作业 ID，唯一标识本次运行
            module_name: 模块名称
            workflow_name: 工作流名称
            time_range: 时间范围 {"start": str, "end": str}
            region: 空间区域 {"west": float, "south": float, "east": float, "north": float}
            extra: 额外字段字典
        """
        self.job_id = job_id
        self.module_name = module_name
        self.workflow_name = workflow_name
        self.time_range = time_range
        self.region = region
        self.extra = extra or {}
        self.products: list[dict] = []
        self.diagnostics: dict[str, Any] = {}
        self.created_at: str = ""

    def add_raster(
        self,
        name: str,
        path: str,
        *,
        layer_type: str = "raster",
        var_name: str = "",
        unit: str = "",
        description: str = "",
        preview_path: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """添加栅格产物。

        参数：
            name: 产物名称
            path: 产物相对路径
            layer_type: 图层类型，默认为 "raster"
            var_name: 变量名称
            unit: 数据单位
            description: 描述信息
            preview_path: 预览图路径
            **kwargs: 其他额外字段（如 size_bytes, bounds 等）
        """
        product: dict[str, Any] = {
            "name": name,
            "path": path,
            "layer_type": layer_type,
            "var_name": var_name,
            "unit": unit,
            "description": description,
            "preview_path": preview_path,
        }
        product.update(kwargs)
        self.products.append(product)

    def add_table(
        self,
        name: str,
        path: str,
        *,
        layer_type: str = "table",
        description: str = "",
        rows: int = 0,
        columns: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> None:
        """添加表格产物。

        参数：
            name: 产物名称
            path: 产物相对路径
            layer_type: 图层类型，默认为 "table"
            description: 描述信息
            rows: 行数
            columns: 列名列表
            **kwargs: 其他额外字段
        """
        product: dict[str, Any] = {
            "name": name,
            "path": path,
            "layer_type": layer_type,
            "description": description,
            "rows": rows,
            "columns": columns or [],
        }
        product.update(kwargs)
        self.products.append(product)

    def add_json(
        self,
        name: str,
        path: str,
        *,
        layer_type: str = "json",
        description: str = "",
        **kwargs: Any,
    ) -> None:
        """添加 JSON 产物。

        参数：
            name: 产物名称
            path: 产物相对路径
            layer_type: 图层类型，默认为 "json"
            description: 描述信息
            **kwargs: 其他额外字段
        """
        product: dict[str, Any] = {
            "name": name,
            "path": path,
            "layer_type": layer_type,
            "description": description,
        }
        product.update(kwargs)
        self.products.append(product)

    def add_diagnostic(self, key: str, value: Any) -> None:
        """添加诊断信息。

        参数：
            key: 诊断键名
            value: 诊断值（需为 JSON 可序列化类型）
        """
        self.diagnostics[str(key)] = value

    def build_bytes(self) -> tuple[bytes, dict]:
        """将 manifest 内容序列化为 JSON bytes（不写文件）。

        返回：
            (bytes, dict): JSON 字节数据和 manifest 内容字典。
        """
        self.created_at = datetime.now(timezone.utc).isoformat()

        manifest: dict[str, Any] = {
            "job_id": self.job_id,
            "created_at": self.created_at,
            "module_name": self.module_name,
            "workflow_name": self.workflow_name,
            "time_range": self.time_range,
            "region": self.region,
            "products": self.products,
            "diagnostics": self.diagnostics,
            "extra": self.extra,
        }
        json_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        return json_bytes, manifest

    def build(self, output_dir: Path | str) -> dict:
        """构建并写出 manifest.json（兼容旧接口）。

        参数：
            output_dir: 输出目录

        返回：
            dict: manifest 内容
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        json_bytes, manifest = self.build_bytes()

        manifest_file = output_dir / "manifest.json"
        manifest_file.write_bytes(json_bytes)

        if not manifest_file.exists():
            raise IOError(f"manifest.json 写入失败: {manifest_file}")
        file_size = manifest_file.stat().st_size
        if file_size == 0:
            raise IOError(f"manifest.json 写入失败，文件大小为 0: {manifest_file}")

        return manifest

    def to_dict(self) -> dict:
        """将当前清单内容返回为字典（不写入文件）。"""
        return {
            "job_id": self.job_id,
            "created_at": self.created_at,
            "module_name": self.module_name,
            "workflow_name": self.workflow_name,
            "time_range": self.time_range,
            "region": self.region,
            "products": self.products,
            "diagnostics": self.diagnostics,
            "extra": self.extra,
        }
