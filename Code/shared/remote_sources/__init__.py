"""统一远程存储 URI / Transport 契约（算法包与 backend 共用）。"""

from __future__ import annotations

from shared.remote_sources.protocol import RemoteAuth, RemoteStat, RemoteTransport
from shared.remote_sources.registry import (
    TransportRegistry,
    get_default_transport_registry,
)
from shared.remote_sources.uri import ParsedRemoteUri, parse_remote_uri

__all__ = [
    "ParsedRemoteUri",
    "RemoteAuth",
    "RemoteStat",
    "RemoteTransport",
    "TransportRegistry",
    "get_default_transport_registry",
    "parse_remote_uri",
]
