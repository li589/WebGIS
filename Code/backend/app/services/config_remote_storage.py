from __future__ import annotations

import logging
from datetime import UTC
from functools import lru_cache
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── 远程存储凭证 ──────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _get_remote_storage_repository():
    from pathlib import Path

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
        history_limit=settings.remote_storage_history_limit,
    )


def list_remote_storage_profiles(include_disabled: bool = True) -> list[dict[str, Any]]:
    return _get_remote_storage_repository().list_profiles(
        include_disabled=include_disabled
    )


def list_remote_storage_history(profile_id: str) -> list[dict[str, Any]]:
    return _get_remote_storage_repository().list_history(profile_id)


def restore_remote_storage_history(profile_id: str, history_id: int) -> dict[str, Any]:
    from app.services.remote_auth_resolver import clear_remote_auth_cache

    repo = _get_remote_storage_repository()
    info = repo.get_profile_info(profile_id)
    if info is None:
        raise ValueError(f"Profile not found: {profile_id}")
    bundle = repo.get_history_bundle(profile_id, history_id)
    if bundle is None:
        raise ValueError(f"历史记录 #{history_id} 不存在")
    result = repo.upsert(
        profile_id=profile_id,
        protocol=info["protocol"],
        host=info.get("host") or "",
        port=info.get("port"),
        username=info.get("username"),
        secret=bundle.get("secret") or "",
        private_key_pem=bundle.get("private_key_pem"),
        domain=info.get("domain"),
        extra=info.get("extra"),
        display_name=info.get("display_name"),
        enabled=info.get("enabled"),
    )
    clear_remote_auth_cache()
    return result


def delete_remote_storage_history_entry(profile_id: str, history_id: int) -> bool:
    return _get_remote_storage_repository().delete_history_entry(profile_id, history_id)


def clear_remote_storage_history(profile_id: str) -> int:
    return _get_remote_storage_repository().clear_history(profile_id)


def upsert_remote_storage_profile(
    profile_id: str,
    *,
    protocol: str,
    host: str = "",
    port: int | None = None,
    username: str | None = None,
    secret: str | None = None,
    private_key_pem: str | None = None,
    domain: str | None = None,
    extra: dict[str, Any] | None = None,
    display_name: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    from app.services.remote_auth_resolver import clear_remote_auth_cache

    result = _get_remote_storage_repository().upsert(
        profile_id=profile_id,
        protocol=protocol,
        host=host,
        port=port,
        username=username,
        secret=secret,
        private_key_pem=private_key_pem,
        domain=domain,
        extra=extra,
        display_name=display_name,
        enabled=enabled,
    )
    clear_remote_auth_cache()
    return result


def delete_remote_storage_profile(profile_id: str) -> bool:
    from app.services.remote_auth_resolver import clear_remote_auth_cache

    deleted = _get_remote_storage_repository().delete(profile_id)
    if deleted:
        clear_remote_auth_cache()
    return deleted


def toggle_remote_storage_profile(profile_id: str, enabled: bool) -> bool:
    from app.services.remote_auth_resolver import clear_remote_auth_cache

    ok = _get_remote_storage_repository().set_enabled(profile_id, enabled)
    if ok:
        clear_remote_auth_cache()
    return ok


def test_remote_storage_profile(
    profile_id: str, uri: str | None = None
) -> dict[str, Any]:
    """Probe connectivity for a credential profile (auth/host, not object existence)."""
    from datetime import datetime

    from app.services.remote_auth_resolver import resolve_remote_auth
    from shared.remote_sources.download import (
        probe_remote_connectivity,
        probe_remote_uri,
    )
    from shared.remote_sources.uri import redact_uri

    repo = _get_remote_storage_repository()
    info = repo.get_profile_info(profile_id)
    if info is None:
        return {
            "profile_id": profile_id,
            "success": False,
            "message": f"Profile not found: {profile_id}",
            "tested_at": datetime.now(UTC).isoformat(),
        }
    if not info.get("enabled"):
        return {
            "profile_id": profile_id,
            "success": False,
            "message": "Profile is disabled",
            "tested_at": datetime.now(UTC).isoformat(),
        }

    protocol = info["protocol"]
    host = info.get("host") or "localhost"
    port = info.get("port")
    host_part = f"{host}:{port}" if port is not None and protocol != "gs" else host

    if uri:
        probe_uri = uri
    elif protocol == "smb":
        share = (info.get("extra") or {}).get("default_share")
        if not share:
            return {
                "profile_id": profile_id,
                "success": False,
                "message": "SMB profile requires extra.default_share for connectivity probe",
                "tested_at": datetime.now(UTC).isoformat(),
            }
        probe_uri = f"smb://{host_part}/{share}/"
    elif protocol == "gs":
        probe_uri = f"gs://{host}/"
    else:
        probe_uri = f"{protocol}://{host_part}/"

    try:
        from urllib.parse import urlparse

        from app.core.ssrf import (
            SSRFBlockedError,
            default_allow_private,
            validate_outbound_url,
        )

        parsed_probe = urlparse(probe_uri)
        if parsed_probe.scheme in {"http", "https"}:
            try:
                validate_outbound_url(probe_uri, allow_private=default_allow_private())
            except SSRFBlockedError as exc:
                repo.update_test_status(profile_id, "failed")
                return {
                    "profile_id": profile_id,
                    "success": False,
                    "message": str(exc),
                    "tested_at": datetime.now(UTC).isoformat(),
                }
        if "cred=" not in probe_uri:
            sep = "&" if "?" in probe_uri else "?"
            probe_uri = f"{probe_uri}{sep}cred={profile_id}"
        auth = resolve_remote_auth(probe_uri)
        # Custom URI probes the given path; default probes connectivity only
        if uri:
            probe_remote_uri(probe_uri, auth)
        else:
            probe_remote_connectivity(probe_uri, auth)
        repo.update_test_status(profile_id, "ok")
        return {
            "profile_id": profile_id,
            "success": True,
            "message": f"Probe OK: {redact_uri(probe_uri)}",
            "tested_at": datetime.now(UTC).isoformat(),
        }
    except (OSError, ConnectionError, TimeoutError) as exc:
        # 探测失败（连接拒绝/超时/认证失败等）——预期结果，不记 ERROR
        repo.update_test_status(profile_id, "failed")
        return {
            "profile_id": profile_id,
            "success": False,
            "message": str(exc),
            "tested_at": datetime.now(UTC).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001 — unexpected error catch-all after specific exceptions, logged
        # 意外错误——记录完整堆栈，但仍返回失败元组（形状不变）
        logger.exception(
            "Unexpected error probing remote storage profile %s", profile_id
        )
        repo.update_test_status(profile_id, "failed")
        return {
            "profile_id": profile_id,
            "success": False,
            "message": str(exc),
            "tested_at": datetime.now(UTC).isoformat(),
        }
