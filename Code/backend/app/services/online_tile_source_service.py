"""用户注册在线 WMTS/XYZ 瓦片源的安全适配。"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.core.ssrf import SSRFBlockedError, resolve_outbound_target
from app.services.config_service import list_online_tile_sources
from app.services.tile_provider_protocol import TileResponse
from app.services.tile_proxy_service import DEFAULT_TILE_USER_AGENT


def _validate_public_host(host: str) -> None:
    lowered = host.lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".local"):
        raise ValueError("online tile source host is not allowed")
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        try:
            resolved = socket.gethostbyname(lowered)
        except OSError as exc:
            raise ValueError("online tile source host cannot be resolved") from exc
        ip = ipaddress.ip_address(resolved)
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        raise ValueError("online tile source host must not target private networks")


def _source(source_id: str) -> dict:
    source = next(
        (x for x in list_online_tile_sources() if x.get("source_id") == source_id), None
    )
    if not source or source.get("enabled") is False:
        raise ValueError(f"Online tile source not found or disabled: {source_id}")
    parsed = urlparse(str(source.get("url_template") or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("online tile source URL must be absolute http(s)")
    try:
        resolve_outbound_target(
            f"{parsed.scheme}://{parsed.netloc}", allow_private=False
        )
    except SSRFBlockedError as exc:
        raise ValueError("online tile source host is blocked by SSRF policy") from exc
    return source


class OnlineTileProvider:
    def matches(self, layer_id: str) -> bool:
        return any(
            x.get("source_id") == layer_id and x.get("enabled") is not False
            for x in list_online_tile_sources()
        )

    async def get_tile(
        self, layer_id: str, z: int, x: int, y: int, **params
    ) -> TileResponse:
        from app.services.tile_proxy_service import tile_proxy_service

        source = _source(layer_id)
        template = str(source["url_template"])
        url = template.format(z=z, x=x, y=y)
        parsed = urlparse(url)
        try:
            resolve_outbound_target(
                f"{parsed.scheme}://{parsed.netloc}", allow_private=False
            )
        except SSRFBlockedError as exc:
            raise ValueError(
                "online tile source host is blocked by SSRF policy"
            ) from exc
        if source.get("service_type") == "wmts":
            # 已注册模板必须显式包含 WMTS 的服务参数，避免把普通 URL
            # 误标成 WMTS 并静默请求错误图层。
            required = {"SERVICE=WMTS", "REQUEST=GetTile"}
            upper_template = template.upper()
            if not required.issubset(
                {part for part in required if part in upper_template}
            ):
                raise ValueError(
                    "WMTS url_template must contain SERVICE=WMTS and REQUEST=GetTile"
                )
        data = await tile_proxy_service.fetch_external_url(
            url,
            use_cache=params.get("use_cache", True),
            user_agent=DEFAULT_TILE_USER_AGENT,
        )
        content_type = str(source.get("image_format") or "image/png")
        return TileResponse(
            data=data,
            content_type=content_type,
            extra_headers={
                "Cache-Control": "public, max-age=86400",
                "X-Tile-Provider": layer_id,
            },
        )
