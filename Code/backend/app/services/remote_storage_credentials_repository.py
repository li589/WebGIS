"""Encrypted SQLite repository for remote storage credential profiles."""
from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

ALLOWED_PROTOCOLS = frozenset({"sftp", "smb", "ftp", "ftps", "gs"})
DEFAULT_HISTORY_LIMIT = 20


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


class RemoteStorageCredentialsRepository:
    def __init__(
        self,
        db_path: str | Path,
        encryption_key: str = "",
        *,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._encryption_key = encryption_key
        self._history_limit = max(1, int(history_limit))
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS remote_storage_credentials (
                    profile_id TEXT PRIMARY KEY,
                    protocol TEXT NOT NULL,
                    host TEXT NOT NULL DEFAULT '',
                    port INTEGER,
                    username TEXT,
                    secret_encrypted TEXT NOT NULL,
                    secret_iv TEXT NOT NULL,
                    private_key_encrypted TEXT,
                    private_key_iv TEXT,
                    domain TEXT,
                    extra_json TEXT,
                    display_name TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_tested_at TEXT,
                    last_test_status TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS remote_storage_secret_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id TEXT NOT NULL,
                    secret_encrypted TEXT NOT NULL,
                    secret_iv TEXT NOT NULL,
                    private_key_encrypted TEXT,
                    private_key_iv TEXT,
                    label TEXT,
                    created_at TEXT NOT NULL,
                    superseded_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_remote_secret_history_profile "
                "ON remote_storage_secret_history(profile_id, superseded_at DESC)"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _encrypt(self, plaintext: str) -> tuple[str, str]:
        if not plaintext:
            return "", ""
        if not self._encryption_key:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError(
                    "Cannot store remote credentials without BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY "
                    "outside development."
                )
            logger.error("Remote credentials encryption key not set, storing plaintext (development only)")
            return plaintext, ""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore

            key_bytes = bytes.fromhex(self._encryption_key)
            iv = os.urandom(12)
            aesgcm = AESGCM(key_bytes)
            ct = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
            return base64.b64encode(ct).decode("ascii"), base64.b64encode(iv).decode("ascii")
        except ImportError as exc:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError("cryptography package required") from exc
            return plaintext, ""

    def _decrypt(self, ciphertext_b64: str, iv_b64: str) -> str:
        if not ciphertext_b64:
            return ""
        if not self._encryption_key or not iv_b64:
            return ciphertext_b64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore

        key_bytes = bytes.fromhex(self._encryption_key)
        iv = base64.b64decode(iv_b64)
        ct = base64.b64decode(ciphertext_b64)
        aesgcm = AESGCM(key_bytes)
        return aesgcm.decrypt(iv, ct, None).decode("utf-8")

    def upsert(
        self,
        *,
        profile_id: str,
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
        protocol = protocol.lower().strip()
        if protocol not in ALLOWED_PROTOCOLS:
            raise ValueError(f"Unsupported protocol: {protocol}")
        profile_id = profile_id.strip()
        if not profile_id:
            raise ValueError("profile_id is required")

        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_secret_bundle(profile_id, include_disabled=True)
        # None = preserve existing secret/key/extra/enabled; "" clears secrets
        secret_val = secret if secret is not None else (existing or {}).get("secret") or ""
        key_val = (
            private_key_pem
            if private_key_pem is not None
            else (existing or {}).get("private_key_pem") or ""
        )
        if extra is None:
            extra_val = dict((existing or {}).get("extra") or {})
        else:
            extra_val = dict(extra)
        if enabled is None:
            enabled_val = bool((existing or {}).get("enabled", True)) if existing else True
        else:
            enabled_val = bool(enabled)

        sec_ct, sec_iv = self._encrypt(secret_val)
        key_ct, key_iv = self._encrypt(key_val) if key_val else ("", "")
        with self._connect() as conn:
            # Archive previous secrets in the SAME transaction as the main upsert
            # to ensure atomicity (avoid orphaned archive rows if main upsert fails).
            if existing is not None:
                old_secret = existing.get("secret") or ""
                old_key = existing.get("private_key_pem") or ""
                if (secret is not None and secret != old_secret) or (
                    private_key_pem is not None and (private_key_pem or "") != old_key
                ):
                    self._archive_secrets(
                        conn,
                        profile_id=profile_id,
                        secret=old_secret,
                        private_key_pem=old_key or None,
                        superseded_at=now,
                        source="user",
                    )
            conn.execute(
                """
                INSERT INTO remote_storage_credentials (
                    profile_id, protocol, host, port, username,
                    secret_encrypted, secret_iv, private_key_encrypted, private_key_iv,
                    domain, extra_json, display_name, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    protocol=excluded.protocol,
                    host=excluded.host,
                    port=excluded.port,
                    username=excluded.username,
                    secret_encrypted=excluded.secret_encrypted,
                    secret_iv=excluded.secret_iv,
                    private_key_encrypted=excluded.private_key_encrypted,
                    private_key_iv=excluded.private_key_iv,
                    domain=excluded.domain,
                    extra_json=excluded.extra_json,
                    display_name=excluded.display_name,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    profile_id,
                    protocol,
                    host or "",
                    port,
                    username,
                    sec_ct,
                    sec_iv,
                    key_ct or None,
                    key_iv or None,
                    domain,
                    json.dumps(extra_val, ensure_ascii=False),
                    display_name or profile_id,
                    1 if enabled_val else 0,
                    now,
                    now,
                ),
            )
            conn.commit()
        info = self.get_profile_info(profile_id)
        assert info is not None
        return info

    def delete(self, profile_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM remote_storage_credentials WHERE profile_id=?",
                (profile_id,),
            )
            conn.commit()
            return cur.rowcount > 0

    def set_enabled(self, profile_id: str, enabled: bool) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE remote_storage_credentials SET enabled=?, updated_at=? WHERE profile_id=?",
                (1 if enabled else 0, datetime.now(timezone.utc).isoformat(), profile_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def update_test_status(self, profile_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE remote_storage_credentials
                SET last_tested_at=?, last_test_status=?, updated_at=?
                WHERE profile_id=?
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    status,
                    datetime.now(timezone.utc).isoformat(),
                    profile_id,
                ),
            )
            conn.commit()

    def list_profiles(self, include_disabled: bool = True) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if include_disabled:
                rows = conn.execute(
                    "SELECT * FROM remote_storage_credentials ORDER BY profile_id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM remote_storage_credentials WHERE enabled=1 ORDER BY profile_id"
                ).fetchall()
        return [self._row_to_info(r) for r in rows]

    def get_profile_info(self, profile_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM remote_storage_credentials WHERE profile_id=?",
                (profile_id,),
            ).fetchone()
        return self._row_to_info(row) if row else None

    def get_secret_bundle(
        self,
        profile_id: str,
        *,
        include_disabled: bool = False,
    ) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM remote_storage_credentials WHERE profile_id=?",
                (profile_id,),
            ).fetchone()
        if not row:
            return None
        if not include_disabled and not row["enabled"]:
            return None
        extra = {}
        if row["extra_json"]:
            try:
                extra = json.loads(row["extra_json"])
            except json.JSONDecodeError:
                extra = {}
        return {
            "profile_id": row["profile_id"],
            "protocol": row["protocol"],
            "host": row["host"] or "",
            "port": row["port"],
            "username": row["username"],
            "secret": self._decrypt(row["secret_encrypted"], row["secret_iv"] or ""),
            "private_key_pem": self._decrypt(
                row["private_key_encrypted"] or "",
                row["private_key_iv"] or "",
            )
            if row["private_key_encrypted"]
            else None,
            "domain": row["domain"],
            "extra": extra,
            "enabled": bool(row["enabled"]),
        }

    def find_by_host_protocol(self, protocol: str, host: str) -> Optional[dict[str, Any]]:
        protocol = protocol.lower().strip()
        protocols = [protocol]
        if protocol in {"ftp", "ftps"}:
            protocols = ["ftp", "ftps"]
        placeholders = ",".join("?" for _ in protocols)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT profile_id FROM remote_storage_credentials
                WHERE enabled=1 AND protocol IN ({placeholders}) AND LOWER(host)=LOWER(?)
                ORDER BY updated_at DESC LIMIT 1
                """,
                (*protocols, host),
            ).fetchone()
        if not row:
            return None
        return self.get_secret_bundle(row["profile_id"])

    def _row_to_info(self, row: sqlite3.Row) -> dict[str, Any]:
        extra = {}
        if row["extra_json"]:
            try:
                extra = json.loads(row["extra_json"])
            except json.JSONDecodeError:
                extra = {}
        return {
            "profile_id": row["profile_id"],
            "protocol": row["protocol"],
            "host": row["host"] or "",
            "port": row["port"],
            "username": row["username"],
            "has_secret": bool(row["secret_encrypted"]),
            "has_private_key": bool(row["private_key_encrypted"]),
            "domain": row["domain"],
            "extra": extra,
            "display_name": row["display_name"] or row["profile_id"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_tested_at": row["last_tested_at"],
            "last_test_status": row["last_test_status"],
        }

    def _archive_secrets(
        self,
        conn: sqlite3.Connection,
        *,
        profile_id: str,
        secret: str,
        private_key_pem: str | None,
        superseded_at: str,
        source: str,
        label: str | None = None,
    ) -> None:
        """将旧密钥归档到 history 表。必须在调用方的事务内调用，不自行 commit。

        Args:
            conn: 由调用方传入的 sqlite3.Connection，确保与主 upsert 在同一事务内。
            其余参数同旧签名。
        """
        sec_ct, sec_iv = self._encrypt(secret or "")
        key_ct, key_iv = self._encrypt(private_key_pem) if private_key_pem else ("", "")
        conn.execute(
            """
            INSERT INTO remote_storage_secret_history (
                profile_id, secret_encrypted, secret_iv,
                private_key_encrypted, private_key_iv,
                label, created_at, superseded_at, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                sec_ct,
                sec_iv,
                key_ct or None,
                key_iv or None,
                label,
                superseded_at,
                superseded_at,
                source,
            ),
        )
        conn.execute(
            """
            DELETE FROM remote_storage_secret_history
            WHERE profile_id=? AND id NOT IN (
                SELECT id FROM remote_storage_secret_history
                WHERE profile_id=?
                ORDER BY superseded_at DESC, id DESC
                LIMIT ?
            )
            """,
            (profile_id, profile_id, self._history_limit),
        )

    def list_history(self, profile_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM remote_storage_secret_history
                WHERE profile_id=?
                ORDER BY superseded_at DESC, id DESC
                """,
                (profile_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            secret = self._decrypt(row["secret_encrypted"], row["secret_iv"] or "")
            result.append(
                {
                    "id": int(row["id"]),
                    "profile_id": row["profile_id"],
                    "masked_secret": _mask_secret(secret),
                    "has_private_key": bool(row["private_key_encrypted"]),
                    "label": row["label"],
                    "created_at": row["created_at"],
                    "superseded_at": row["superseded_at"],
                    "source": row["source"],
                }
            )
        return result

    def get_history_bundle(self, profile_id: str, history_id: int) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM remote_storage_secret_history
                WHERE profile_id=? AND id=?
                """,
                (profile_id, history_id),
            ).fetchone()
        if not row:
            return None
        return {
            "secret": self._decrypt(row["secret_encrypted"], row["secret_iv"] or ""),
            "private_key_pem": self._decrypt(
                row["private_key_encrypted"] or "",
                row["private_key_iv"] or "",
            )
            if row["private_key_encrypted"]
            else None,
        }

    def delete_history_entry(self, profile_id: str, history_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM remote_storage_secret_history WHERE profile_id=? AND id=?",
                (profile_id, history_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def clear_history(self, profile_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM remote_storage_secret_history WHERE profile_id=?",
                (profile_id,),
            )
            conn.commit()
            return int(cur.rowcount)
