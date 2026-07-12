"""统一瓦片提供者协议。

定义 TileProvider Protocol 和 TileResponse 数据类，
为统一瓦片端点 (/unified-tiles/{layer_id}/{z}/{x}/{y}) 提供标准接口。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class TileResponse:
    """统一瓦片响应容器。"""

    data: bytes
    content_type: str
    cache_status: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)


class TileProvider(Protocol):
    """瓦片提供者协议。

    每个提供者通过 ``matches`` 判断是否能处理给定的 ``layer_id``，
    并通过 ``get_tile`` 返回 :class:`TileResponse`。
    """

    def matches(self, layer_id: str) -> bool: ...

    async def get_tile(
        self,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        **params: Any,
    ) -> TileResponse: ...
