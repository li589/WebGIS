"""External adapter protocols and data types.

WebGIS 后端接入方只需实现这里列出的 Protocol（接口），即可通过 run_job() 驱动计算。
"""

from .datasource import DataAsset, DataSourceAdapter
from .logger import LoggerAdapter
from .product_sink import ProductSink, RasterProduct, TableProduct
from .scheduler import SchedulerAdapter

__all__ = [
    "DataAsset",
    "DataSourceAdapter",
    "LoggerAdapter",
    "ProductSink",
    "RasterProduct",
    "SchedulerAdapter",
    "TableProduct",
]
