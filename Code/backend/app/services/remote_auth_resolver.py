"""Resolve RemoteAuth for a remote URI from credential profiles."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from shared.remote_sources.protocol import RemoteAuth
from shared.remote_sources.uri import parse_remote_uri

# 协议兼容组：profile 协议与 URI scheme 可互通
_COMPAT_SETS: list[frozenset[str]] = [
    frozenset({"ftp", "ftps"}),
    frozenset({"sftp", "ssh"}),
    frozenset({"http", "https"}),
]


@lru_cache(maxsize=1)
def _repo():
    from pathlib import Path

    from app.core.config import settings
    from app.services.remote_storage_credentials_repository import (
        RemoteStorageCredentialsRepository,
    )

    db_path = (
        Path(settings.gee_credentials_db_path).parent
        / "remote_storage_credentials.sqlite3"
    )
    return RemoteStorageCredentialsRepository(
        db_path=db_path,
        encryption_key=settings.gee_credentials_encryption_key,
    )


def _normalize_protocol(protocol: str) -> str:
    p = (protocol or "").lower().strip()
    if p == "gcs":
        return "gs"
    return p


def _protocols_compatible(profile_proto: str, uri_proto: str) -> bool:
    if profile_proto == uri_proto:
        return True
    return any({profile_proto, uri_proto} <= s for s in _COMPAT_SETS)


def resolve_remote_auth(uri: str) -> RemoteAuth:
    parsed = parse_remote_uri(uri)
    repo = _repo()
    bundle = None
    if parsed.cred_profile:
        bundle = repo.get_secret_bundle(parsed.cred_profile)
        if bundle is None:
            raise ValueError(
                f"Remote credential profile not found or disabled: {parsed.cred_profile}"
            )
    else:
        bundle = repo.find_by_host_protocol(parsed.scheme, parsed.host)
        if bundle is None:
            raise ValueError(
                f"No credential profile for {parsed.scheme}://{parsed.host}; "
                "pass ?cred=profile_id or create a matching profile"
            )

    profile_proto = _normalize_protocol(str(bundle.get("protocol") or ""))
    uri_proto = parsed.scheme
    if not _protocols_compatible(profile_proto, uri_proto):
        raise ValueError(
            f"Credential profile protocol '{profile_proto}' does not match URI scheme '{uri_proto}'"
        )

    extra = dict(bundle.get("extra") or {})
    secret = bundle.get("secret") or None
    # For GCS, secret field holds service account JSON (not a login password)
    if parsed.scheme == "gs" and secret:
        extra.setdefault("service_account_json", secret)
        secret = None

    # 双路径回退元数据以 JSON 字符串形式进入 extra（RemoteAuth.extra 为 dict[str, str]）
    auth_extra: dict[str, str] = {}
    for k, v in extra.items():
        if isinstance(v, bool):
            # transports 以字符串 "true"/"false" 语义消费布尔（如 allow_plain_ftp）
            auth_extra[str(k)] = "true" if v else "false"
        elif isinstance(v, str):
            auth_extra[str(k)] = v
        elif isinstance(v, (int, float)):
            auth_extra[str(k)] = str(v)
    alt = extra.get("alt")
    if isinstance(alt, dict) and any(alt.get(key) for key in ("host", "url", "share")):
        auth_extra.setdefault("alt_json", json.dumps(alt, ensure_ascii=False))
    fallback_mode = extra.get("fallback_mode")
    if fallback_mode in {"auto", "manual", "off"}:
        auth_extra.setdefault("fallback_mode", str(fallback_mode))
    failover_state = extra.get("failover_state")
    if isinstance(failover_state, dict):
        active = failover_state.get("active")
        if active in {"primary", "alt"}:
            auth_extra.setdefault("active_path", str(active))

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
        extra=auth_extra,
    )


def resolve_remote_auth_bundle(uri: str) -> tuple[RemoteAuth, dict[str, Any] | None]:
    """Resolve primary auth plus the alt path descriptor for dual-path failover."""
    auth = resolve_remote_auth(uri)
    alt: dict[str, Any] | None = None
    alt_json = auth.extra.get("alt_json")
    if alt_json:
        try:
            loaded = json.loads(alt_json)
            if isinstance(loaded, dict):
                alt = loaded
        except json.JSONDecodeError:
            alt = None
    return auth, alt


def clear_remote_auth_cache() -> None:
    _repo.cache_clear()
