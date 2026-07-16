from __future__ import annotations

import base64
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _mask_value(value: str) -> str:
    """脱敏处理：保留前4位和后4位，中间用 **** 替代。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


class ApiKeysRepository:
    """API Key 的 SQLite 持久化层。

    表结构：
        CREATE TABLE IF NOT EXISTS api_keys (
            key_name TEXT PRIMARY KEY,         -- 'tianditu' / 'baidu' / 'backend_auth'
            key_value_encrypted TEXT NOT NULL, -- AES-GCM 加密的 key
            key_iv TEXT NOT NULL,              -- 每次加密的随机 IV
            display_name TEXT NOT NULL,        -- 显示名称
            description TEXT,                  -- 描述
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_tested_at TEXT,
            last_test_status TEXT              -- 'ok' / 'failed' / None
        );
    """

    def __init__(self, db_path: str | Path, encryption_key: str = "") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._encryption_key = encryption_key
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
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

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

    def upsert_key(
        self,
        *,
        key_name: str,
        key_value: str,
        display_name: str,
        description: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """新增或更新 API Key。返回脱敏后的 key 信息。"""
        ct, iv = self._encrypt(key_value)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_keys (key_name, key_value_encrypted, key_iv, display_name,
                                      description, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(key_name) DO UPDATE SET
                    key_value_encrypted=excluded.key_value_encrypted,
                    key_iv=excluded.key_iv,
                    display_name=excluded.display_name,
                    description=excluded.description,
                    enabled=1,
                    updated_at=excluded.updated_at
                """,
                (key_name, ct, iv, display_name, description, now, now),
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

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        # 解密获取明文用于脱敏显示
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
