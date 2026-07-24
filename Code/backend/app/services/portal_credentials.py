"""开放门户凭证（Earthdata / NSIDC / Copernicus）读写与运行时解析。"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

PORTAL_IDS = ("earthdata", "nsidc", "copernicus")

_SECRET_KEYS = frozenset(
    {"token", "access_token", "password", "secret", "client_secret"}
)


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def _encrypt_blob(plaintext: str, encryption_key: str) -> dict[str, str]:
    if not plaintext:
        return {"ciphertext": "", "iv": ""}
    if not encryption_key:
        from app.services.effective_config import secrets_encryption_required

        if secrets_encryption_required():
            raise RuntimeError(
                "Cannot store portal credentials without BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY "
                "outside development."
            )
        # development: store as base64 marker (not secure; documented)
        return {
            "ciphertext": base64.b64encode(plaintext.encode("utf-8")).decode("ascii"),
            "iv": "plain",
        }
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key_bytes = bytes.fromhex(encryption_key)
    iv = os.urandom(12)
    aes = AESGCM(key_bytes)
    ct = aes.encrypt(iv, plaintext.encode("utf-8"), None)
    return {
        "ciphertext": base64.b64encode(ct).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
    }


def _decrypt_blob(ciphertext: str, iv: str, encryption_key: str) -> str:
    if not ciphertext:
        return ""
    if iv == "plain":
        return base64.b64decode(ciphertext.encode("ascii")).decode("utf-8")
    if not encryption_key:
        raise RuntimeError("Cannot decrypt portal credentials without encryption key")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key_bytes = bytes.fromhex(encryption_key)
    aes = AESGCM(key_bytes)
    pt = aes.decrypt(base64.b64decode(iv), base64.b64decode(ciphertext), None)
    return pt.decode("utf-8")


def default_portal_credentials_public() -> dict[str, Any]:
    return {
        "earthdata": {
            "enabled": False,
            "auth_type": "bearer",
            "username": "",
            "has_token": False,
            "has_password": False,
            "use_for_nsidc": True,
            "source": "none",
        },
        "nsidc": {
            "enabled": False,
            "auth_type": "bearer",
            "username": "",
            "has_token": False,
            "has_password": False,
            "use_earthdata": True,
            "source": "none",
        },
        "copernicus": {
            "enabled": False,
            "auth_type": "bearer",
            "username": "",
            "has_token": False,
            "has_password": False,
            "client_id": "",
            "source": "none",
        },
    }


def _env_runtime_overlays() -> dict[str, dict[str, Any]]:
    """Cold-start env tokens (used when DB profile missing token)."""
    out: dict[str, dict[str, Any]] = {}
    ed = os.getenv("BACKEND_EARTHDATA_TOKEN", "").strip()
    if ed:
        out["earthdata"] = {
            "enabled": True,
            "auth_type": "bearer",
            "token": ed,
            "use_for_nsidc": True,
            "source": "env",
        }
    ns = os.getenv("BACKEND_NSIDC_TOKEN", "").strip()
    if ns:
        out["nsidc"] = {
            "enabled": True,
            "auth_type": "bearer",
            "token": ns,
            "source": "env",
        }
    cp = os.getenv("BACKEND_COPERNICUS_TOKEN", "").strip()
    if cp:
        out["copernicus"] = {
            "enabled": True,
            "auth_type": "bearer",
            "token": cp,
            "source": "env",
        }
    return out


def load_portal_credentials_secret(
    *,
    repo: Any,
    encryption_key: str,
) -> dict[str, dict[str, Any]]:
    """Return decrypted portal credential map (runtime use). DB overrides env."""
    merged: dict[str, dict[str, Any]] = {k: {} for k in PORTAL_IDS}
    for pid, entry in _env_runtime_overlays().items():
        merged[pid] = dict(entry)

    raw = repo.get_json("portal_credentials", None)
    if not isinstance(raw, dict):
        return {k: v for k, v in merged.items() if v}

    for pid in PORTAL_IDS:
        blob = raw.get(pid)
        if not isinstance(blob, dict):
            continue
        try:
            secret_json = _decrypt_blob(
                str(blob.get("ciphertext") or ""),
                str(blob.get("iv") or ""),
                encryption_key,
            )
            secrets = json.loads(secret_json) if secret_json else {}
            if not isinstance(secrets, dict):
                secrets = {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to decrypt portal credential %s: %s", pid, exc)
            continue
        public = {k: v for k, v in blob.items() if k not in {"ciphertext", "iv"}}
        entry = {**public, **secrets, "source": "db"}
        if entry.get("enabled") is None:
            entry["enabled"] = True
        merged[pid] = entry
    return {k: v for k, v in merged.items() if v}


def public_portal_credentials(
    *,
    repo: Any,
    encryption_key: str,
) -> dict[str, Any]:
    """Masked view for settings API."""
    base = default_portal_credentials_public()
    runtime = load_portal_credentials_secret(repo=repo, encryption_key=encryption_key)
    for pid, entry in runtime.items():
        pub = base.get(pid, {})
        pub = dict(pub)
        pub["enabled"] = bool(entry.get("enabled", True))
        pub["auth_type"] = str(
            entry.get("auth_type") or pub.get("auth_type") or "bearer"
        )
        pub["username"] = str(entry.get("username") or "")
        pub["has_token"] = bool(
            str(entry.get("token") or entry.get("access_token") or "").strip()
        )
        pub["has_password"] = bool(
            str(entry.get("password") or entry.get("secret") or "").strip()
        )
        pub["source"] = str(entry.get("source") or "none")
        if pid == "earthdata":
            pub["use_for_nsidc"] = bool(entry.get("use_for_nsidc", True))
        if pid == "nsidc":
            pub["use_earthdata"] = bool(entry.get("use_earthdata", True))
        if pid == "copernicus":
            pub["client_id"] = str(entry.get("client_id") or "")
        base[pid] = pub
    return base


def upsert_portal_credential(
    *,
    repo: Any,
    encryption_key: str,
    portal_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    portal_id = str(portal_id).strip().lower()
    if portal_id not in PORTAL_IDS:
        raise ValueError(
            f"Unknown portal_id: {portal_id}; expected one of {PORTAL_IDS}"
        )

    existing_raw = repo.get_json("portal_credentials", {})
    if not isinstance(existing_raw, dict):
        existing_raw = {}

    prev_secrets: dict[str, Any] = {}
    prev_blob = existing_raw.get(portal_id)
    if isinstance(prev_blob, dict) and prev_blob.get("ciphertext"):
        try:
            prev_secrets = json.loads(
                _decrypt_blob(
                    str(prev_blob.get("ciphertext") or ""),
                    str(prev_blob.get("iv") or ""),
                    encryption_key,
                )
                or "{}"
            )
        except Exception:  # noqa: BLE001
            prev_secrets = {}

    secrets: dict[str, Any] = dict(prev_secrets)
    for key in _SECRET_KEYS:
        if key in payload and payload[key] is not None:
            val = str(payload[key]).strip()
            if val:
                secrets[key] = val
            elif payload.get("clear_secrets"):
                secrets.pop(key, None)

    for key in ("username", "client_id", "auth_type", "token_header"):
        if key in payload and payload[key] is not None:
            secrets[key] = str(payload[key]).strip()

    if "use_for_nsidc" in payload:
        secrets["use_for_nsidc"] = bool(payload["use_for_nsidc"])
    if "use_earthdata" in payload:
        secrets["use_earthdata"] = bool(payload["use_earthdata"])

    enabled = bool(payload.get("enabled", True))
    public_meta = {
        "enabled": enabled,
        "auth_type": str(
            secrets.get("auth_type") or payload.get("auth_type") or "bearer"
        ),
        "username": str(secrets.get("username") or ""),
        "updated": True,
    }
    if portal_id == "earthdata":
        public_meta["use_for_nsidc"] = bool(secrets.get("use_for_nsidc", True))
    if portal_id == "nsidc":
        public_meta["use_earthdata"] = bool(secrets.get("use_earthdata", True))
    if portal_id == "copernicus":
        public_meta["client_id"] = str(secrets.get("client_id") or "")

    enc = _encrypt_blob(json.dumps(secrets, ensure_ascii=False), encryption_key)
    existing_raw[portal_id] = {**public_meta, **enc}
    repo.set_json("portal_credentials", existing_raw)
    return public_portal_credentials(repo=repo, encryption_key=encryption_key)


def delete_portal_credential(
    *, repo: Any, encryption_key: str, portal_id: str
) -> dict[str, Any]:
    portal_id = str(portal_id).strip().lower()
    raw = repo.get_json("portal_credentials", {})
    if isinstance(raw, dict) and portal_id in raw:
        del raw[portal_id]
        repo.set_json("portal_credentials", raw)
    return public_portal_credentials(repo=repo, encryption_key=encryption_key)
