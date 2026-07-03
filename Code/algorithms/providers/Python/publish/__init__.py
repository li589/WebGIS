"""publish - 格式写出层，将算法模块的输出转换为前端可消费的标准格式。

支持格式：
- COG (Cloud Optimized GeoTIFF) 栅格：MapLibre GL 直接加载
- PNG 预览图：前端缩略图
- Parquet 表格：前端图表消费
- JSON manifest：产物清单
"""

from __future__ import annotations

from .manifest_builder import ManifestBuilder
from .output_manager import OutputManager
from .raster_writer import COGWriter, PreviewGenerator
from .table_writer import TableWriter, write_timeseries

__all__ = [
    "COGWriter",
    "PreviewGenerator",
    "TableWriter",
    "write_timeseries",
    "ManifestBuilder",
    "OutputManager",
]
