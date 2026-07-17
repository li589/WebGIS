"""Remote scheme adapter (sftp/smb/ftp/ftps/gs) backed by shared.remote_sources."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from data_access.contracts import DataRequestV2, ResourceRef, build_resource_ref
from shared.remote_sources.download import download_remote_uri
from shared.remote_sources.limits import get_max_remote_bytes
from shared.remote_sources.protocol import RemoteAuth
from shared.remote_sources.uri import parse_remote_uri

_REMOTE_SCHEMES = frozenset({"sftp", "smb", "ftp", "ftps", "gs", "gcs"})


def _resolve_auth(uri: str, metadata: dict[str, object] | None) -> RemoteAuth:
    meta = dict(metadata or {})
    if meta.get("username") or meta.get("password") or meta.get("private_key_pem"):
        extra = meta.get("extra") if isinstance(meta.get("extra"), dict) else {}
        port_raw = meta.get("port")
        try:
            port = int(port_raw) if port_raw is not None else None
        except (TypeError, ValueError):
            port = None
        return RemoteAuth(
            username=str(meta["username"]) if meta.get("username") else None,
            password=str(meta["password"]) if meta.get("password") else None,
            private_key_pem=str(meta["private_key_pem"]) if meta.get("private_key_pem") else None,
            domain=str(meta["domain"]) if meta.get("domain") else None,
            port=port,
            extra={str(k): str(v) for k, v in extra.items()},
        )
    try:
        from app.services.remote_auth_resolver import resolve_remote_auth

        return resolve_remote_auth(uri)
    except Exception as exc:
        raise ValueError(
            f"Unable to resolve remote credentials for {uri}: {exc}. "
            "Provide metadata auth fields or backend credential profile (?cred=)."
        ) from exc


class RemoteSource:
    name = "remote"
    supported_schemes = ("sftp", "smb", "ftp", "ftps", "gs", "gcs")

    def can_handle(self, uri: str) -> bool:
        scheme = urlparse(uri).scheme.lower()
        return scheme in _REMOTE_SCHEMES

    def locate(
        self,
        uri: str,
        *,
        request: DataRequestV2 | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ResourceRef:
        _ = request
        parsed = parse_remote_uri(uri)
        staged = dict(metadata or {})
        staged["remote_scheme"] = parsed.scheme
        staged["remote_host"] = parsed.host
        if parsed.cred_profile:
            staged["cred_profile"] = parsed.cred_profile
        return build_resource_ref(
            uri=uri,
            source_kind="remote",
            storage_backend=parsed.scheme,
            metadata=staged,
        )

    def materialize(
        self,
        resource: ResourceRef,
        *,
        target_dir: Path | None = None,
    ) -> ResourceRef:
        destination = Path(target_dir) if target_dir is not None else Path.cwd() / ".data" / "remote_cache"
        auth = _resolve_auth(resource.uri, resource.metadata)
        local_path, stat = download_remote_uri(
            resource.uri,
            auth,
            target_dir=destination,
            max_bytes=get_max_remote_bytes(),
        )
        staged = dict(resource.metadata)
        staged["materialization_status"] = "ready"
        staged["local_path"] = str(local_path)
        staged["remote_size"] = stat.size
        if target_dir is not None:
            staged["target_dir"] = str(target_dir)
        return build_resource_ref(
            uri=local_path.as_uri(),
            source_kind=resource.source_kind,
            format=resource.format,
            logical_type=resource.logical_type,
            storage_backend="local",
            metadata=staged,
        )
