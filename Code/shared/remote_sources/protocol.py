from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from shared.remote_sources.uri import ParsedRemoteUri


@dataclass(frozen=True, slots=True)
class RemoteAuth:
    """Resolved credentials passed into a transport (never log secret fields)."""

    username: str | None = None
    password: str | None = None
    private_key_pem: str | None = None
    domain: str | None = None
    # Profile default port when URI omits :port
    port: int | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RemoteStat:
    path: str
    size: int | None
    is_dir: bool
    mtime: float | None = None


def effective_port(parsed: ParsedRemoteUri, auth: RemoteAuth, default: int) -> int:
    if parsed.port is not None:
        return int(parsed.port)
    if auth.port is not None:
        return int(auth.port)
    return default


class RemoteTransport(Protocol):
    name: str
    supported_schemes: tuple[str, ...]

    def supports(self, parsed: ParsedRemoteUri) -> bool: ...

    def stat(self, parsed: ParsedRemoteUri, auth: RemoteAuth) -> RemoteStat: ...

    def download_to(
        self,
        parsed: ParsedRemoteUri,
        auth: RemoteAuth,
        local_path: Path,
        *,
        max_bytes: int,
    ) -> RemoteStat: ...
