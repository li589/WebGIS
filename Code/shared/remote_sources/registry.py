from __future__ import annotations

from typing import Iterable

from shared.remote_sources.protocol import RemoteTransport
from shared.remote_sources.uri import ParsedRemoteUri, parse_remote_uri


class TransportRegistry:
    def __init__(self) -> None:
        self._by_scheme: dict[str, RemoteTransport] = {}

    def register(self, transport: RemoteTransport) -> None:
        for scheme in transport.supported_schemes:
            self._by_scheme[scheme.lower()] = transport

    def register_many(self, transports: Iterable[RemoteTransport]) -> None:
        for t in transports:
            self.register(t)

    def get_for_uri(self, uri: str) -> tuple[ParsedRemoteUri, RemoteTransport]:
        parsed = parse_remote_uri(uri)
        transport = self._by_scheme.get(parsed.scheme)
        if transport is None:
            raise KeyError(f"No remote transport for scheme '{parsed.scheme}'")
        return parsed, transport

    def registered_schemes(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_scheme))


_default: TransportRegistry | None = None


def get_default_transport_registry() -> TransportRegistry:
    global _default
    if _default is None:
        from shared.remote_sources.transports.ftp import FtpTransport
        from shared.remote_sources.transports.gcs import GcsTransport
        from shared.remote_sources.transports.sftp import SftpTransport
        from shared.remote_sources.transports.smb import SmbTransport

        reg = TransportRegistry()
        reg.register_many(
            [
                SftpTransport(),
                SmbTransport(),
                FtpTransport(),
                GcsTransport(),
            ]
        )
        _default = reg
    return _default
