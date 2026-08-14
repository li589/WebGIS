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


def get_remote_storage_repository():
    """公开仓库访问器（供 remote_access.browser 复用，含解密 bundle）。"""
    return _get_remote_storage_repository()


def list_remote_storage_profiles(include_disabled: bool = True) -> list[dict[str, Any]]:
    return [
        _decorate_profile(info)
        for info in _get_remote_storage_repository().list_profiles(
            include_disabled=include_disabled
        )
    ]


def get_remote_storage_profile(profile_id: str) -> dict[str, Any] | None:
    info = _get_remote_storage_repository().get_profile_info(profile_id)
    return _decorate_profile(info) if info is not None else None


def _decorate_profile(info: dict[str, Any]) -> dict[str, Any]:
    """把 extra.alt / fallback_mode / failover_state 展平为顶层便捷字段（只读回显）。"""
    extra = info.get("extra") or {}
    alt = extra.get("alt") if isinstance(extra.get("alt"), dict) else {}
    out = dict(info)
    out["alt_host"] = str(alt.get("host") or "")
    out["alt_port"] = alt.get("port") if isinstance(alt.get("port"), int) else None
    out["alt_url"] = str(alt.get("url") or "")
    out["fallback_mode"] = str(extra.get("fallback_mode") or "auto")
    out["failover_state"] = (
        extra.get("failover_state")
        if isinstance(extra.get("failover_state"), dict)
        else {}
    )
    return out


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
    return _decorate_profile(result)


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
    alt_host: str | None = None,
    alt_port: int | None = None,
    alt_url: str | None = None,
    fallback_mode: str | None = None,
) -> dict[str, Any]:
    from app.services.remote_auth_resolver import clear_remote_auth_cache

    repo = _get_remote_storage_repository()
    alt_given = any(v is not None for v in (alt_host, alt_port, alt_url))
    if alt_given or fallback_mode is not None:
        # 合并语义：extra=None 时以现值为基础，避免丢掉 default_share 等协议字段
        base = extra
        if base is None:
            existing = repo.get_profile_info(profile_id)
            base = dict((existing or {}).get("extra") or {})
        merged = dict(base)
        if alt_given:
            alt = dict(merged.get("alt") or {})
            if alt_host is not None:
                alt["host"] = alt_host
            if alt_port is not None:
                alt["port"] = alt_port
            if alt_url is not None:
                alt["url"] = alt_url
            merged["alt"] = alt
        if fallback_mode is not None:
            merged["fallback_mode"] = fallback_mode
        extra = merged

    result = repo.upsert(
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
    return _decorate_profile(result)


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


def _build_probe_uri(
    protocol: str, host: str, port: int | None, extra: dict[str, Any]
) -> str | None:
    """按协议构造默认探测 URI；返回 None 表示需要浏览器式探测（filebrowser/lan/nfs）。"""
    if protocol in {"filebrowser", "lan", "nfs"}:
        return None
    host_part = f"{host}:{port}" if port is not None and protocol != "gs" else host
    if protocol == "smb":
        share = extra.get("default_share")
        if not share:
            return "MISSING_SMB_SHARE"
        return f"smb://{host_part}/{share}/"
    if protocol == "gs":
        return f"gs://{host}/"
    if protocol in {"http", "https"} and host.startswith(("http://", "https://")):
        # http/https 约定 host 存 base URL
        return host
    return f"{protocol}://{host_part}/"


def test_remote_storage_profile(
    profile_id: str, uri: str | None = None
) -> dict[str, Any]:
    """Probe connectivity for a credential profile (auth/host, not object existence).

    双路径：主路径网络类失败且 fallback_mode=auto 时自动重试备用路径；
    filebrowser/lan/nfs 走 remote_access.browser 统一探测（内部处理回退）。
    """
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
    extra = info.get("extra") or {}
    alt = extra.get("alt") if isinstance(extra.get("alt"), dict) else None
    alt_valid = bool(alt and any(alt.get(k) for k in ("host", "url", "share")))
    fallback_mode = str(extra.get("fallback_mode") or "auto")

    default_uri = _build_probe_uri(
        protocol, info.get("host") or "", info.get("port"), extra
    )
    if uri is None and default_uri == "MISSING_SMB_SHARE":
        return {
            "profile_id": profile_id,
            "success": False,
            "message": "SMB profile requires extra.default_share for connectivity probe",
            "tested_at": datetime.now(UTC).isoformat(),
        }

    if uri is None and default_uri is None:
        return _test_via_browser(repo, profile_id)

    def _probe_once(which: str, host: str, port: int | None, url_override: str) -> str:
        """Returns probe URI on success; raises on failure."""
        if uri is not None:
            # 自定义 URI 仅首跳使用；备用路径跳过（用户明确指定了对象路径）
            probe_uri = uri
            if which != "primary":
                raise ConnectionError("alt path skipped for custom URI probe")
        elif protocol in {"http", "https", "filebrowser"} and url_override:
            probe_uri = url_override
        else:
            built = _build_probe_uri(protocol, host or "", port, extra)
            probe_uri = (
                built
                if isinstance(built, str) and built != "MISSING_SMB_SHARE"
                else (default_uri or "")
            )
        try:
            from urllib.parse import urlparse

            from app.core.ssrf import (
                SSRFBlockedError,
                default_allow_private,
                validate_outbound_url,
            )

            parsed_probe = urlparse(probe_uri)
            if parsed_probe.scheme in {"http", "https"}:
                validate_outbound_url(probe_uri, allow_private=default_allow_private())
            if "cred=" not in probe_uri:
                sep = "&" if "?" in probe_uri else "?"
                probe_uri = f"{probe_uri}{sep}cred={profile_id}"
            auth = resolve_remote_auth(probe_uri)
            if uri:
                probe_remote_uri(probe_uri, auth)
            else:
                probe_remote_connectivity(probe_uri, auth)
            return probe_uri
        except SSRFBlockedError:
            raise

    attempts: list[tuple[str, str, int | None, str]] = [
        ("primary", info.get("host") or "localhost", info.get("port"), "")
    ]
    if alt_valid and fallback_mode == "auto" and uri is None:
        attempts.append(
            (
                "alt",
                str(alt.get("host") or info.get("host") or "localhost"),
                alt.get("port")
                if isinstance(alt.get("port"), int)
                else info.get("port"),
                str(alt.get("url") or ""),
            )
        )

    last_error = ""
    for which, host, port, url_override in attempts:
        try:
            probe_uri = _probe_once(which, host, port, url_override)
            repo.update_test_status(profile_id, "ok")
            repo.set_failover_state(profile_id, {"active": which, "last_error": ""})
            label = "主路径" if which == "primary" else "备用路径"
            return {
                "profile_id": profile_id,
                "success": True,
                "message": f"Probe OK ({label}): {redact_uri(probe_uri)}",
                "tested_at": datetime.now(UTC).isoformat(),
            }
        except (OSError, ConnectionError, TimeoutError) as exc:
            # 网络类失败——auto 模式继续尝试备用路径
            logger.info(
                "Probe failed via %s for profile %s: %s", which, profile_id, exc
            )
            last_error = str(exc)
            continue
        except Exception as exc:  # noqa: BLE001 — unexpected error catch-all
            logger.exception(
                "Unexpected error probing remote storage profile %s", profile_id
            )
            repo.update_test_status(profile_id, "failed")
            repo.set_failover_state(
                profile_id, {"active": "primary", "last_error": str(exc)}
            )
            return {
                "profile_id": profile_id,
                "success": False,
                "message": str(exc),
                "tested_at": datetime.now(UTC).isoformat(),
            }

    repo.update_test_status(profile_id, "failed")
    repo.set_failover_state(profile_id, {"active": "primary", "last_error": last_error})
    label = "主路径与备用路径均不可达" if len(attempts) > 1 else "探测失败"
    return {
        "profile_id": profile_id,
        "success": False,
        "message": f"{label}: {last_error}",
        "tested_at": datetime.now(UTC).isoformat(),
    }


def _test_via_browser(repo: Any, profile_id: str) -> dict[str, Any]:
    """filebrowser/lan/nfs 协议经 remote_access.browser 探测（含双路径回退）。"""
    from datetime import datetime

    from app.services.remote_access import browser

    try:
        result = browser.browse_profile(profile_id, "/")
        repo.update_test_status(profile_id, "ok")
        label = "主路径" if result.get("via") == "primary" else "备用路径"
        return {
            "profile_id": profile_id,
            "success": True,
            "message": f"Probe OK ({label}): {len(result.get('items') or [])} entries",
            "tested_at": datetime.now(UTC).isoformat(),
        }
    except browser.RemoteAccessError as exc:
        repo.update_test_status(profile_id, "failed")
        return {
            "profile_id": profile_id,
            "success": False,
            "message": str(exc),
            "tested_at": datetime.now(UTC).isoformat(),
        }


def probe_failover(profile_id: str, target: str) -> dict[str, Any]:
    """手动切换主/备访问路径（写 failover_state.active；manual 模式下生效）。"""
    from datetime import UTC as _UTC
    from datetime import datetime

    repo = _get_remote_storage_repository()
    info = repo.get_profile_info(profile_id)
    if info is None:
        raise ValueError(f"Profile not found: {profile_id}")
    extra = info.get("extra") or {}
    alt = extra.get("alt") if isinstance(extra.get("alt"), dict) else None
    target = (target or "").lower().strip()
    if target not in {"primary", "alt"}:
        raise ValueError("target must be 'primary' or 'alt'")
    if target == "alt" and not any(alt.get(k) for k in ("host", "url", "share") if alt):
        raise ValueError("该 Profile 未配置备用访问路径（alt）")

    state: dict[str, Any] = {"active": target, "last_error": ""}
    if target == "alt":
        state["last_failover_at"] = datetime.now(_UTC).isoformat()
    updated = repo.set_failover_state(profile_id, state)
    return {
        "profile_id": profile_id,
        "active": target,
        "updated": updated,
        "message": f"已切换到{'备用' if target == 'alt' else '主'}访问路径"
        + (
            "（manual 模式下立即生效；auto 模式下主路径恢复后会自动回切）"
            if str(extra.get("fallback_mode") or "auto") == "auto"
            else ""
        ),
    }
