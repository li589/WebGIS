"""API Key SQLite persistence with encrypted current value + version history."""
from __future__ import annotations

import base64
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.services._sqlite_pool import SQLiteConnectionPool

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_LIMIT = 20


def _mask_value(value: str) -> str:
    """脱敏处理：保留前4位和后4位，中间用 **** 替代。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


class ApiKeysRepository:
    """API Key 的 SQLite 持久化层（当前值 + api_key_history）。"""

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
        # Sprint 2.4b: 使用连接池替代每次新建连接（WAL + busy_timeout + 连接复用）
        self._pool = SQLiteConnectionPool(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_name TEXT PRIMARY KEY,
                    key_value_encrypted TEXT NOT NULL,
                    key_iv TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    description TEXT,
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
                CREATE TABLE IF NOT EXISTS api_key_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_name TEXT NOT NULL,
                    key_value_encrypted TEXT NOT NULL,
                    key_iv TEXT NOT NULL,
                    label TEXT,
                    created_at TEXT NOT NULL,
                    superseded_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_api_key_history_name "
                "ON api_key_history(key_name, superseded_at DESC)"
            )
            conn.commit()

    def _connect(self):
        """获取连接上下文管理器（从连接池获取，自动 commit/rollback + 归还）。"""
        return self._pool.connection()

    def _encrypt(self, plaintext: str) -> tuple[str, str]:
        """AES-GCM 加密，返回 (ciphertext_b64, iv_b64)。无 key 时仅 development 允许明文。"""
        if not self._encryption_key:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError(
                    "Cannot store API keys without BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY "
                    "outside development."
                )
            logger.error("API keys encryption key not set, storing plaintext (development only)")
            return plaintext, ""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore

            key_bytes = bytes.fromhex(self._encryption_key)
            iv = os.urandom(12)
            aesgcm = AESGCM(key_bytes)
            ct = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
            return base64.b64encode(ct).decode("ascii"), base64.b64encode(iv).decode("ascii")
        except ImportError:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError("cryptography package required to encrypt API keys") from None
            logger.warning("cryptography not installed, storing plaintext")
            return plaintext, ""
        except RuntimeError:
            raise
        except Exception as e:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError(f"Encryption failed for API key: {e}") from e
            logger.error("Encryption failed for key, storing plaintext: %s", e)
            return plaintext, ""

    def _decrypt(self, ciphertext_b64: str, iv_b64: str) -> str:
        if not self._encryption_key or not iv_b64:
            return ciphertext_b64
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore

            key_bytes = bytes.fromhex(self._encryption_key)
            iv = base64.b64decode(iv_b64)
            ct = base64.b64decode(ciphertext_b64)
            aesgcm = AESGCM(key_bytes)
            return aesgcm.decrypt(iv, ct, None).decode("utf-8")
        except Exception as e:
            logger.error("Decryption failed: %s", e)
            raise

    def _archive_current_locked(
        self,
        conn: sqlite3.Connection,
        *,
        key_name: str,
        label: str | None,
        source: str,
        superseded_at: str,
    ) -> None:
        row = conn.execute(
            "SELECT key_value_encrypted, key_iv FROM api_keys WHERE key_name=?",
            (key_name,),
        ).fetchone()
        if not row:
            return
        conn.execute(
            """
            INSERT INTO api_key_history (
                key_name, key_value_encrypted, key_iv, label, created_at, superseded_at, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key_name,
                row["key_value_encrypted"],
                row["key_iv"],
                label,
                superseded_at,
                superseded_at,
                source,
            ),
        )
        self._trim_history_locked(conn, key_name)

    def _trim_history_locked(self, conn: sqlite3.Connection, key_name: str) -> None:
        conn.execute(
            """
            DELETE FROM api_key_history
            WHERE key_name=? AND id NOT IN (
                SELECT id FROM api_key_history
                WHERE key_name=?
                ORDER BY superseded_at DESC, id DESC
                LIMIT ?
            )
            """,
            (key_name, key_name, self._history_limit),
        )

    def upsert_key(
        self,
        *,
        key_name: str,
        key_value: str,
        display_name: str,
        description: Optional[str] = None,
        enabled: bool = True,
        history_label: str | None = None,
        history_source: str = "user",
        archive_previous: bool = True,
    ) -> Optional[dict[str, Any]]:
        """新增或更新 API Key。值变化时归档旧值到 history。"""
        ct, iv = self._encrypt(key_value)
        now = datetime.now(timezone.utc).isoformat()
        enabled_flag = 1 if enabled else 0
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT key_value_encrypted, key_iv FROM api_keys WHERE key_name=?",
                (key_name,),
            ).fetchone()
            if archive_previous and existing is not None:
                try:
                    old_plain = self._decrypt(existing["key_value_encrypted"], existing["key_iv"])
                except Exception:
                    old_plain = None
                if old_plain is not None and old_plain != key_value:
                    self._archive_current_locked(
                        conn,
                        key_name=key_name,
                        label=history_label,
                        source=history_source,
                        superseded_at=now,
                    )
            conn.execute(
                """
                INSERT INTO api_keys (key_name, key_value_encrypted, key_iv, display_name,
                                      description, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key_name) DO UPDATE SET
                    key_value_encrypted=excluded.key_value_encrypted,
                    key_iv=excluded.key_iv,
                    display_name=excluded.display_name,
                    description=excluded.description,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (key_name, ct, iv, display_name, description, enabled_flag, now, now),
            )
            conn.commit()
        return self.get_key_info(key_name)

    def get_key_value(self, key_name: str) -> Optional[str]:
        """获取解密后的 key 值。供运行时服务调用。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT key_value_encrypted, key_iv, enabled FROM api_keys WHERE key_name=?",
                (key_name,),
            ).fetchone()
        if not row or not row["enabled"]:
            return None
        return self._decrypt(row["key_value_encrypted"], row["key_iv"])

    def get_key_value_raw(self, key_name: str) -> Optional[str]:
        """Decrypt current key regardless of enabled flag (for restore archive)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT key_value_encrypted, key_iv FROM api_keys WHERE key_name=?",
                (key_name,),
            ).fetchone()
        if not row:
            return None
        return self._decrypt(row["key_value_encrypted"], row["key_iv"])

    def get_key_info(self, key_name: str) -> Optional[dict[str, Any]]:
        """获取脱敏后的 key 信息（不包含明文）。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE key_name=?", (key_name,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def list_keys(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        """列出所有 key（脱敏）。"""
        with self._connect() as conn:
            if include_disabled:
                rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM api_keys WHERE enabled=1 ORDER BY created_at"
                ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete_key(self, key_name: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM api_keys WHERE key_name=?", (key_name,))
            conn.commit()
            return cur.rowcount > 0

    def set_enabled(self, key_name: str, enabled: bool) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE api_keys SET enabled=?, updated_at=? WHERE key_name=?",
                (1 if enabled else 0, datetime.now(timezone.utc).isoformat(), key_name),
            )
            conn.commit()
            return cur.rowcount > 0

    def update_test_status(self, key_name: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE api_keys SET last_tested_at=?, last_test_status=? WHERE key_name=?",
                (datetime.now(timezone.utc).isoformat(), status, key_name),
            )
            conn.commit()

    def list_history(self, key_name: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, key_name, key_value_encrypted, key_iv, label,
                       created_at, superseded_at, source
                FROM api_key_history
                WHERE key_name=?
                ORDER BY superseded_at DESC, id DESC
                """,
                (key_name,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                plaintext = self._decrypt(row["key_value_encrypted"], row["key_iv"])
                masked = _mask_value(plaintext)
            except Exception:
                masked = "****"
            result.append(
                {
                    "id": int(row["id"]),
                    "key_name": row["key_name"],
                    "masked_value": masked,
                    "label": row["label"],
                    "created_at": row["created_at"],
                    "superseded_at": row["superseded_at"],
                    "source": row["source"],
                }
            )
        return result

    def get_history_value(self, key_name: str, history_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT key_value_encrypted, key_iv FROM api_key_history
                WHERE key_name=? AND id=?
                """,
                (key_name, history_id),
            ).fetchone()
        if not row:
            return None
        return self._decrypt(row["key_value_encrypted"], row["key_iv"])

    def delete_history_entry(self, key_name: str, history_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM api_key_history WHERE key_name=? AND id=?",
                (key_name, history_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def clear_history(self, key_name: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM api_key_history WHERE key_name=?",
                (key_name,),
            )
            conn.commit()
            return int(cur.rowcount)

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            plaintext = self._decrypt(row["key_value_encrypted"], row["key_iv"])
            masked = _mask_value(plaintext)
        except Exception:
            masked = "****"
        return {
            "key_name": row["key_name"],
            "display_name": row["display_name"],
            "description": row["description"],
            "masked_value": masked,
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_tested_at": row["last_tested_at"],
            "last_test_status": row["last_test_status"],
        }
