"""Multi-profile Agent LLM config — global (admin) + per-user personal stores."""

from __future__ import annotations

import json
import logging
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Literal

from app.core.config import settings
from app.core.ssrf import SSRFBlockedError, validate_url_for_storage
from app.services.agent.presets import get_preset, list_presets
from app.services.effective_config import secrets_encryption_required
from app.services.secret_cipher import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

_VALID_PROTOCOLS = frozenset({"openai", "anthropic", "demo"})
Scope = Literal["global", "personal"]
_lock = threading.Lock()


class AgentPermissionError(PermissionError):
    """Raised when caller lacks scope write permission."""


def _runtime_root() -> Path:
    root = Path(settings.data_root or settings.workflow_state_dir or ".")
    path = root / "_runtime" / "agent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _global_profiles_path() -> Path:
    return _runtime_root() / "global_profiles.json"


def _personal_profiles_path(user_id: int) -> Path:
    path = _runtime_root() / "users" / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path / "profiles.json"


def _legacy_flat_profiles_path() -> Path:
    """Pre-isolation single file under _runtime/."""
    root = Path(settings.data_root or settings.workflow_state_dir or ".")
    return root / "_runtime" / "agent_profiles.json"


def _legacy_config_path() -> Path:
    root = Path(settings.data_root or settings.workflow_state_dir or ".")
    return root / "_runtime" / "agent_config.json"


def _encryption_key() -> str:
    return (settings.gee_credentials_encryption_key or "").strip()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _default_demo_profile() -> dict[str, Any]:
    preset = get_preset("demo") or {}
    return {
        "id": "demo",
        "name": str(preset.get("name") or "演示（无网）"),
        "provider_kind": "demo",
        "protocol": "demo",
        "base_url": "",
        "model": str(preset.get("model") or "demo-rules"),
        "context_window_input": int(preset.get("context_window_input") or 4000),
        "context_window_output": int(preset.get("context_window_output") or 2000),
        "preset_id": "demo",
        "api_key_ciphertext": None,
        "api_key_iv": None,
    }


def _empty_store() -> dict[str, Any]:
    demo = _default_demo_profile()
    return {"active_profile_id": demo["id"], "profiles": [demo]}


def _empty_personal_store() -> dict[str, Any]:
    """Personal store starts empty so global active remains effective."""
    return {"active_profile_id": "", "profiles": []}


def _archive_legacy_path(path: Path) -> None:
    """Rename one-shot legacy files so they cannot re-seed polluted stores."""
    if not path.exists():
        return
    bak = path.with_name(path.name + ".migrated.bak")
    try:
        if bak.exists():
            bak.unlink()
        path.replace(bak)
    except OSError as exc:
        logger.warning("Failed to archive legacy %s: %s", path, exc)


def _migrate_legacy_single_config() -> dict[str, Any] | None:
    """Convert old flat agent_config.json → profiles store.

    Mock/demo legacy configs are discarded (clean demo only). Real ollama /
    openai_compatible keys become a single optional profile beside demo.
    """
    legacy = _legacy_config_path()
    if not legacy.exists():
        return None
    try:
        raw = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None

    provider = str(raw.get("provider") or "mock").strip().lower()
    # Demo / mock / empty → stock demo only (do not keep "迁移自旧配置" clutter).
    if provider in {"", "mock", "demo"}:
        return _empty_store()

    protocol = "demo"
    provider_kind = "demo"
    preset_id = "demo"
    if provider == "ollama":
        protocol, provider_kind, preset_id = "openai", "ollama", "ollama"
    elif provider == "openai_compatible":
        protocol, provider_kind, preset_id = "openai", "custom", "custom_openai"
    else:
        # Unknown legacy provider → ignore and seed demo.
        return _empty_store()

    pid = _new_id()
    profile: dict[str, Any] = {
        "id": pid,
        "name": str(
            (get_preset(preset_id) or {}).get("name") or provider_kind or "LLM"
        ),
        "provider_kind": provider_kind,
        "protocol": protocol,
        "base_url": str(raw.get("base_url") or "").strip(),
        "model": str(raw.get("model") or "").strip() or "qwen2.5",
        "context_window_input": 8192,
        "context_window_output": 4096,
        "preset_id": preset_id,
        "api_key_ciphertext": raw.get("api_key_ciphertext"),
        "api_key_iv": raw.get("api_key_iv"),
    }
    return {
        "active_profile_id": "demo",
        "profiles": [_default_demo_profile(), profile],
    }


def _normalize_global_store(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Drop migration leftovers; keep a clean demo slot; dedupe by id.

    Returns (store, changed).
    """
    profiles_in = [p for p in (data.get("profiles") or []) if isinstance(p, dict)]
    changed = False
    kept: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for p in profiles_in:
        name = str(p.get("name") or "")
        pid = str(p.get("id") or "")
        if name.startswith("迁移自旧配置"):
            changed = True
            continue
        if not pid or pid in seen_ids:
            changed = True
            continue
        seen_ids.add(pid)
        if pid == "demo":
            # Always re-materialize demo from preset (fixes corrupted migrations).
            demo = _default_demo_profile()
            if p != demo:
                changed = True
            kept.append(demo)
        else:
            kept.append(p)

    if not any(str(p.get("id")) == "demo" for p in kept):
        kept.insert(0, _default_demo_profile())
        changed = True

    active = str(data.get("active_profile_id") or "")
    ids = {str(p.get("id")) for p in kept}
    if active not in ids:
        active = "demo"
        changed = True

    out = {"active_profile_id": active, "profiles": kept}
    return out, changed


def _ensure_global_migrated() -> None:
    """Move agent_profiles.json → agent/global_profiles.json once."""
    dest = _global_profiles_path()
    if dest.exists():
        return
    flat = _legacy_flat_profiles_path()
    if flat.exists():
        try:
            shutil.copy2(flat, dest)
            _archive_legacy_path(flat)
            return
        except OSError as exc:
            logger.warning("Failed to migrate agent_profiles.json: %s", exc)
    migrated = _migrate_legacy_single_config()
    if migrated is not None:
        _save_store_unlocked(dest, migrated)
        _archive_legacy_path(_legacy_config_path())
        return
    _save_store_unlocked(dest, _empty_store())


def _load_store_unlocked(path: Path, *, personal: bool = False) -> dict[str, Any]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("profiles"), list):
                # Global store must always keep ≥1 profile (demo fallback).
                if not personal and len(data["profiles"]) == 0:
                    store = _empty_store()
                    _save_store_unlocked(path, store)
                    return store
                if not personal:
                    store, changed = _normalize_global_store(data)
                    if changed:
                        _save_store_unlocked(path, store)
                    return store
                return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load %s: %s", path, exc)
    store = _empty_personal_store() if personal else _empty_store()
    _save_store_unlocked(path, store)
    return store


def _save_store_unlocked(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _public_profile(
    raw: dict[str, Any],
    *,
    active_id: str,
    scope: Scope,
    effective_active: bool,
) -> dict[str, Any]:
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or ""),
        "provider_kind": str(raw.get("provider_kind") or "custom"),
        "protocol": str(raw.get("protocol") or "openai"),
        "base_url": str(raw.get("base_url") or ""),
        "model": str(raw.get("model") or ""),
        "context_window_input": int(raw.get("context_window_input") or 8192),
        "context_window_output": int(raw.get("context_window_output") or 4096),
        "preset_id": raw.get("preset_id"),
        "scope": scope,
        "enabled": effective_active and str(raw.get("id") or "") == active_id,
        "has_api_key": bool(raw.get("api_key_ciphertext")),
    }


def validate_agent_base_url(url: str, *, protocol: str) -> str:
    cleaned = (url or "").strip()
    if protocol == "demo":
        return cleaned
    if not cleaned:
        raise ValueError("base_url 不能为空（演示档除外）")
    try:
        return validate_url_for_storage(cleaned)
    except (SSRFBlockedError, ValueError) as exc:
        raise ValueError(f"无效的 base_url: {exc}") from exc


def _assert_can_write_scope(
    *,
    scope: Scope,
    role: str | None,
    user_id: int | None,
) -> None:
    if scope == "global":
        if role != "admin":
            raise AgentPermissionError("仅管理员可修改全局 Agent 配置档")
        return
    if user_id is None:
        raise AgentPermissionError("个人配置档需要登录用户会话或个人 Token")
    if role == "demo":
        raise AgentPermissionError("演示账户不能修改 Agent 配置档")
    if role not in {"admin", "standard"}:
        raise AgentPermissionError("当前角色无权修改个人 Agent 配置档")


def get_config_bundle(
    *,
    user_id: int | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """Merged public view: global + personal profiles, effective active."""
    with _lock:
        _ensure_global_migrated()
        g_store = _load_store_unlocked(_global_profiles_path())
        p_store: dict[str, Any] | None = None
        if user_id is not None:
            p_store = _load_store_unlocked(
                _personal_profiles_path(user_id), personal=True
            )

    g_active = str(g_store.get("active_profile_id") or "")
    use_personal = False
    p_active = ""
    if p_store is not None:
        p_active = str(p_store.get("active_profile_id") or "")
        p_ids = {
            str(p.get("id"))
            for p in (p_store.get("profiles") or [])
            if isinstance(p, dict)
        }
        if p_active and p_active in p_ids:
            use_personal = True

    effective_scope: Scope = "personal" if use_personal else "global"
    effective_id = p_active if use_personal else g_active

    profiles: list[dict[str, Any]] = []
    for p in g_store.get("profiles") or []:
        if isinstance(p, dict):
            profiles.append(
                _public_profile(
                    p,
                    active_id=g_active,
                    scope="global",
                    effective_active=not use_personal,
                )
            )
    if p_store is not None:
        for p in p_store.get("profiles") or []:
            if isinstance(p, dict):
                profiles.append(
                    _public_profile(
                        p,
                        active_id=p_active,
                        scope="personal",
                        effective_active=use_personal,
                    )
                )

    if not any(p["scope"] == "global" for p in profiles):
        demo = _default_demo_profile()
        profiles.insert(
            0,
            _public_profile(
                demo, active_id="demo", scope="global", effective_active=True
            ),
        )
        effective_scope, effective_id = "global", "demo"

    return {
        "active_profile_id": effective_id,
        "active_scope": effective_scope,
        "can_manage_global": role == "admin",
        "can_manage_personal": bool(
            user_id is not None and role in {"admin", "standard"}
        ),
        "profiles": profiles,
        "presets": list_presets(),
    }


def get_effective_profile_raw(
    *,
    user_id: int | None = None,
) -> dict[str, Any] | None:
    """Raw profile used for chat (personal active preferred)."""
    with _lock:
        _ensure_global_migrated()
        g_store = _load_store_unlocked(_global_profiles_path())
        if user_id is not None:
            p_path = _personal_profiles_path(user_id)
            if p_path.exists():
                p_store = _load_store_unlocked(p_path, personal=True)
                p_active = str(p_store.get("active_profile_id") or "")
                for p in p_store.get("profiles") or []:
                    if (
                        isinstance(p, dict)
                        and str(p.get("id")) == p_active
                        and p_active
                    ):
                        out = dict(p)
                        out["_scope"] = "personal"
                        return out
        g_store = _load_store_unlocked(_global_profiles_path())
        g_active = str(g_store.get("active_profile_id") or "")
        for p in g_store.get("profiles") or []:
            if isinstance(p, dict) and str(p.get("id")) == g_active:
                out = dict(p)
                out["_scope"] = "global"
                return out
        profiles = [p for p in (g_store.get("profiles") or []) if isinstance(p, dict)]
        if profiles:
            out = dict(profiles[0])
            out["_scope"] = "global"
            return out
    return _default_demo_profile()


def get_profile_raw(
    profile_id: str,
    *,
    scope: Scope,
    user_id: int | None = None,
) -> dict[str, Any] | None:
    with _lock:
        _ensure_global_migrated()
        if scope == "global":
            store = _load_store_unlocked(_global_profiles_path())
        else:
            if user_id is None:
                return None
            store = _load_store_unlocked(
                _personal_profiles_path(user_id), personal=True
            )
        for p in store.get("profiles") or []:
            if isinstance(p, dict) and str(p.get("id")) == profile_id:
                return dict(p)
    return None


def get_profile_api_key(profile: dict[str, Any]) -> str | None:
    ct = profile.get("api_key_ciphertext")
    iv = profile.get("api_key_iv") or ""
    if not isinstance(ct, str) or not ct:
        return None
    try:
        return decrypt_secret(
            ct,
            str(iv),
            key=_encryption_key(),
            require_encryption=secrets_encryption_required(),
            label="agent api key",
        )
    except Exception:
        logger.exception(
            "Failed to decrypt agent API key for profile %s", profile.get("id")
        )
        return None


def create_profile_from_preset(
    preset_id: str,
    *,
    name: str | None = None,
    scope: Scope = "personal",
    user_id: int | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    _assert_can_write_scope(scope=scope, role=role, user_id=user_id)
    preset = get_preset(preset_id)
    if preset is None:
        raise ValueError(f"未知预设: {preset_id}")
    pid = "demo" if preset_id == "demo" and scope == "global" else _new_id()
    if preset_id == "demo" and scope == "personal":
        pid = _new_id()

    with _lock:
        _ensure_global_migrated()
        path = (
            _global_profiles_path()
            if scope == "global"
            else _personal_profiles_path(int(user_id))  # type: ignore[arg-type]
        )
        store = _load_store_unlocked(path, personal=(scope == "personal"))
        profiles: list[dict[str, Any]] = [
            p for p in (store.get("profiles") or []) if isinstance(p, dict)
        ]
        if (
            scope == "global"
            and preset_id == "demo"
            and any(str(p.get("id")) == "demo" for p in profiles)
        ):
            demo = _default_demo_profile()
            repaired: list[dict[str, Any]] = []
            for p in profiles:
                if str(p.get("id")) == "demo":
                    repaired.append(demo)
                else:
                    repaired.append(p)
            store["profiles"] = repaired
            if store.get("active_profile_id") not in {
                str(x.get("id")) for x in repaired
            }:
                store["active_profile_id"] = "demo"
            _save_store_unlocked(path, store)
            return _public_profile(
                demo,
                active_id=str(store.get("active_profile_id") or "demo"),
                scope=scope,
                effective_active=str(store.get("active_profile_id") or "") == "demo",
            )
        profile = {
            "id": pid,
            "name": (name or "").strip() or str(preset.get("name") or preset_id),
            "provider_kind": preset.get("provider_kind") or "custom",
            "protocol": preset.get("protocol") or "openai",
            "base_url": str(preset.get("base_url") or ""),
            "model": str(preset.get("model") or ""),
            "context_window_input": int(preset.get("context_window_input") or 8192),
            "context_window_output": int(preset.get("context_window_output") or 4096),
            "preset_id": preset_id,
            "api_key_ciphertext": None,
            "api_key_iv": None,
        }
        profiles.append(profile)
        store["profiles"] = profiles
        _save_store_unlocked(path, store)
        active = str(store.get("active_profile_id") or "")
    return _public_profile(
        profile, active_id=active, scope=scope, effective_active=False
    )


def update_profile(
    profile_id: str,
    *,
    scope: Scope,
    user_id: int | None = None,
    role: str | None = None,
    name: str | None = None,
    protocol: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    context_window_input: int | None = None,
    context_window_output: int | None = None,
    api_key: str | None = None,
    clear_api_key: bool = False,
) -> dict[str, Any]:
    _assert_can_write_scope(scope=scope, role=role, user_id=user_id)
    with _lock:
        _ensure_global_migrated()
        path = (
            _global_profiles_path()
            if scope == "global"
            else _personal_profiles_path(int(user_id))  # type: ignore[arg-type]
        )
        store = _load_store_unlocked(path, personal=(scope == "personal"))
        profiles: list[dict[str, Any]] = [
            p for p in (store.get("profiles") or []) if isinstance(p, dict)
        ]
        target: dict[str, Any] | None = None
        for p in profiles:
            if str(p.get("id")) == profile_id:
                target = p
                break
        if target is None:
            raise ValueError(f"配置档不存在: {profile_id}")

        if name is not None:
            target["name"] = name.strip() or target.get("name") or profile_id
        if protocol is not None:
            proto = protocol.strip()
            if proto not in _VALID_PROTOCOLS:
                raise ValueError(f"无效协议: {protocol}")
            target["protocol"] = proto
            # Leaving demo → non-demo must re-validate existing base_url (W-2).
            if proto != "demo" and base_url is None:
                target["base_url"] = validate_agent_base_url(
                    str(target.get("base_url") or ""),
                    protocol=proto,
                )
        if base_url is not None:
            proto = str(target.get("protocol") or "openai")
            target["base_url"] = validate_agent_base_url(base_url, protocol=proto)
        if model is not None:
            target["model"] = model.strip()
        if context_window_input is not None:
            if context_window_input < 256 or context_window_input > 2_000_000:
                raise ValueError("context_window_input 超出范围")
            target["context_window_input"] = int(context_window_input)
        if context_window_output is not None:
            if context_window_output < 64 or context_window_output > 512_000:
                raise ValueError("context_window_output 超出范围")
            target["context_window_output"] = int(context_window_output)
        if clear_api_key:
            target.pop("api_key_ciphertext", None)
            target.pop("api_key_iv", None)
        elif api_key is not None and api_key.strip():
            ct, iv = encrypt_secret(
                api_key.strip(),
                key=_encryption_key(),
                require_encryption=secrets_encryption_required(),
                label="agent api key",
            )
            target["api_key_ciphertext"] = ct
            target["api_key_iv"] = iv

        store["profiles"] = profiles
        _save_store_unlocked(path, store)
        active = str(store.get("active_profile_id") or "")
    return _public_profile(
        target, active_id=active, scope=scope, effective_active=False
    )


def set_active_profile(
    profile_id: str,
    *,
    scope: Scope,
    user_id: int | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    _assert_can_write_scope(scope=scope, role=role, user_id=user_id)
    with _lock:
        _ensure_global_migrated()
        path = (
            _global_profiles_path()
            if scope == "global"
            else _personal_profiles_path(int(user_id))  # type: ignore[arg-type]
        )
        store = _load_store_unlocked(path, personal=(scope == "personal"))
        ids = {
            str(p.get("id"))
            for p in (store.get("profiles") or [])
            if isinstance(p, dict)
        }
        if profile_id not in ids:
            raise ValueError(f"配置档不存在: {profile_id}")
        store["active_profile_id"] = profile_id
        _save_store_unlocked(path, store)
        # Admin activating a global profile: clear own personal active so it takes effect for them
        if scope == "global" and user_id is not None:
            p_path = _personal_profiles_path(user_id)
            if p_path.exists():
                p_store = _load_store_unlocked(p_path, personal=True)
                if p_store.get("active_profile_id"):
                    p_store["active_profile_id"] = ""
                    _save_store_unlocked(p_path, p_store)
    return get_config_bundle(user_id=user_id, role=role)


def clear_personal_active(*, user_id: int, role: str | None) -> dict[str, Any]:
    """Stop preferring personal profile (fall back to global)."""
    _assert_can_write_scope(scope="personal", role=role, user_id=user_id)
    with _lock:
        path = _personal_profiles_path(user_id)
        store = _load_store_unlocked(path, personal=True)
        store["active_profile_id"] = ""
        _save_store_unlocked(path, store)
    return get_config_bundle(user_id=user_id, role=role)


def delete_profile(
    profile_id: str,
    *,
    scope: Scope,
    user_id: int | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    _assert_can_write_scope(scope=scope, role=role, user_id=user_id)
    with _lock:
        _ensure_global_migrated()
        path = (
            _global_profiles_path()
            if scope == "global"
            else _personal_profiles_path(int(user_id))  # type: ignore[arg-type]
        )
        store = _load_store_unlocked(path, personal=(scope == "personal"))
        profiles: list[dict[str, Any]] = [
            p for p in (store.get("profiles") or []) if isinstance(p, dict)
        ]
        if scope == "global" and len(profiles) <= 1:
            raise ValueError("不能删除最后一个全局配置档")
        remaining = [p for p in profiles if str(p.get("id")) != profile_id]
        if len(remaining) == len(profiles):
            raise ValueError(f"配置档不存在: {profile_id}")
        store["profiles"] = remaining
        if str(store.get("active_profile_id")) == profile_id:
            store["active_profile_id"] = (
                str(remaining[0].get("id")) if remaining else ""
            )
        _save_store_unlocked(path, store)
    return get_config_bundle(user_id=user_id, role=role)


# --- Legacy compatibility ---


def get_active_profile_raw() -> dict[str, Any] | None:
    return get_effective_profile_raw(user_id=None)


def get_agent_config_public() -> dict[str, Any]:
    raw = get_effective_profile_raw(user_id=None) or _default_demo_profile()
    protocol = str(raw.get("protocol") or "demo")
    if protocol == "demo":
        provider = "mock"
    elif str(raw.get("provider_kind")) == "ollama":
        provider = "ollama"
    else:
        provider = "openai_compatible"
    return {
        "provider": provider,
        "base_url": str(raw.get("base_url") or ""),
        "model": str(raw.get("model") or ""),
        "has_api_key": bool(raw.get("api_key_ciphertext")),
    }


def get_agent_api_key() -> str | None:
    raw = get_effective_profile_raw(user_id=None)
    if not raw:
        return None
    return get_profile_api_key(raw)


def update_agent_config(
    *,
    provider: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    clear_api_key: bool = False,
    user_id: int | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """Legacy PUT — updates effective active profile in the writable scope."""
    if role == "admin":
        scope: Scope = "global"
        uid = user_id
    elif user_id is not None and role in {"admin", "standard"}:
        scope = "personal"
        uid = user_id
    else:
        raise AgentPermissionError("无权修改 Agent 配置")

    raw = get_effective_profile_raw(user_id=user_id)
    # Ensure we update within the intended scope store
    with _lock:
        _ensure_global_migrated()
        path = (
            _global_profiles_path()
            if scope == "global"
            else _personal_profiles_path(int(uid))  # type: ignore[arg-type]
        )
        store = _load_store_unlocked(path, personal=(scope == "personal"))
        if not store.get("profiles"):
            store = _empty_store() if scope == "global" else _empty_personal_store()
            if scope == "global":
                _save_store_unlocked(path, store)
            else:
                # Seed personal with a demo clone then activate
                demo = _default_demo_profile()
                demo["id"] = _new_id()
                store = {"active_profile_id": demo["id"], "profiles": [demo]}
                _save_store_unlocked(path, store)
        pid = str(store.get("active_profile_id") or "")
        if not any(str(p.get("id")) == pid for p in store.get("profiles") or []):
            pid = str((store.get("profiles") or [{}])[0].get("id") or "demo")
            store["active_profile_id"] = pid
            _save_store_unlocked(path, store)

    protocol = None
    if provider is not None:
        p = provider.strip()
        if p == "mock":
            protocol = "demo"
        elif p in {"ollama", "openai_compatible"}:
            protocol = "openai"
        else:
            raise ValueError(f"Invalid provider: {provider}")
    update_profile(
        pid,
        scope=scope,
        user_id=uid,
        role=role,
        protocol=protocol,
        base_url=base_url,
        model=model,
        api_key=api_key,
        clear_api_key=clear_api_key,
    )
    if provider == "ollama":
        with _lock:
            path = (
                _global_profiles_path()
                if scope == "global"
                else _personal_profiles_path(int(uid))  # type: ignore[arg-type]
            )
            store = _load_store_unlocked(path, personal=(scope == "personal"))
            for p in store.get("profiles") or []:
                if isinstance(p, dict) and str(p.get("id")) == pid:
                    p["provider_kind"] = "ollama"
                    p["preset_id"] = "ollama"
            _save_store_unlocked(path, store)
    return get_agent_config_public()
