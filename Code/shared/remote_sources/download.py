"""Convenience download helper used by data_access and source_fetcher wrappers."""
from __future__ import annotations

import hashlib
from pathlib import Path

from shared.remote_sources.limits import DEFAULT_MAX_REMOTE_BYTES
from shared.remote_sources.protocol import RemoteAuth, RemoteStat
from shared.remote_sources.registry import get_default_transport_registry
from shared.remote_sources.uri import build_connectivity_probe_uri


def download_remote_uri(
    uri: str,
    auth: RemoteAuth,
    *,
    target_dir: Path,
    max_bytes: int = DEFAULT_MAX_REMOTE_BYTES,
) -> tuple[Path, RemoteStat]:
    parsed, transport = get_default_transport_registry().get_for_uri(uri)
    digest = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:24]
    suffix = Path(parsed.path).suffix or ".bin"
    local_path = Path(target_dir) / f"{parsed.scheme}_{digest}{suffix}"
    if local_path.exists() and local_path.stat().st_size > 0:
        # Reuse only when remote size matches; otherwise re-download
        try:
            remote_stat = transport.stat(parsed, auth)
            if remote_stat.size is not None and remote_stat.size == local_path.stat().st_size:
                return local_path, remote_stat
        except Exception:
            pass
    stat = transport.download_to(parsed, auth, local_path, max_bytes=max_bytes)
    return local_path, stat


def probe_remote_uri(uri: str, auth: RemoteAuth) -> RemoteStat:
    parsed, transport = get_default_transport_registry().get_for_uri(uri)
    return transport.stat(parsed, auth)


def probe_remote_connectivity(uri: str, auth: RemoteAuth) -> RemoteStat:
    """Probe auth/host reachability without requiring a specific object to exist."""
    probe_uri = build_connectivity_probe_uri(uri, default_port=auth.port)
    return probe_remote_uri(probe_uri, auth)
