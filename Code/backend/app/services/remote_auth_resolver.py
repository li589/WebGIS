"""Resolve RemoteAuth for a remote URI from credential profiles."""
from __future__ import annotations

from functools import lru_cache

from shared.remote_sources.protocol import RemoteAuth
from shared.remote_sources.uri import parse_remote_uri


@lru_cache(maxsize=1)
def _repo():
    from pathlib import Path

    from app.core.config import settings
    from app.services.remote_storage_credentials_repository import RemoteStorageCredentialsRepository

    db_path = Path(settings.gee_credentials_db_path).parent / "remote_storage_credentials.sqlite3"
    return RemoteStorageCredentialsRepository(
        db_path=db_path,
        encryption_key=settings.gee_credentials_encryption_key,
    )


def _normalize_protocol(protocol: str) -> str:
    p = (protocol or "").lower().strip()
    if p == "gcs":
        return "gs"
    return p


def resolve_remote_auth(uri: str) -> RemoteAuth:
    parsed = parse_remote_uri(uri)
    repo = _repo()
    bundle = None
    if parsed.cred_profile:
        bundle = repo.get_secret_bundle(parsed.cred_profile)
        if bundle is None:
            raise ValueError(f"Remote credential profile not found or disabled: {parsed.cred_profile}")
    else:
        bundle = repo.find_by_host_protocol(parsed.scheme, parsed.host)
        if bundle is None:
            raise ValueError(
                f"No credential profile for {parsed.scheme}://{parsed.host}; "
                "pass ?cred=profile_id or create a matching profile"
            )

    profile_proto = _normalize_protocol(str(bundle.get("protocol") or ""))
    uri_proto = parsed.scheme
    # Allow ftp profile to serve ftps and vice versa loosely? Keep strict with ftp/ftps match.
    compatible = (
        profile_proto == uri_proto
        or {profile_proto, uri_proto} <= {"ftp", "ftps"}
    )
    if not compatible:
        raise ValueError(
            f"Credential profile protocol '{profile_proto}' does not match URI scheme '{uri_proto}'"
        )

    extra = dict(bundle.get("extra") or {})
    secret = bundle.get("secret") or None
    # For GCS, secret field holds service account JSON (not a login password)
    if parsed.scheme == "gs" and secret:
        extra.setdefault("service_account_json", secret)
        secret = None

    profile_port = bundle.get("port")
    try:
        profile_port_int = int(profile_port) if profile_port is not None else None
    except (TypeError, ValueError):
        profile_port_int = None

    return RemoteAuth(
        username=bundle.get("username") or parsed.username,
        password=secret,
        private_key_pem=bundle.get("private_key_pem") or None,
        domain=bundle.get("domain") or None,
        port=profile_port_int,
        extra={str(k): str(v) if not isinstance(v, str) else v for k, v in extra.items()},
    )


def clear_remote_auth_cache() -> None:
    _repo.cache_clear()
