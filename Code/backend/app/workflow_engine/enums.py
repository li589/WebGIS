from __future__ import annotations

from enum import Enum


class PortKind(str, Enum):
    """端口类型枚举，描述节点输入/输出端口的数据形态。"""

    value = "value"
    data = "data"
    artifact = "artifact"
    geometry = "geometry"
    raster = "raster"
    timeseries = "timeseries"
    table = "table"
    geojson = "geojson"
    diagnostic = "diagnostic"


class RunStatus(str, Enum):
    """工作流/节点执行状态枚举。"""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
