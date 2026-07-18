from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.services._sqlite_pool import SQLiteConnectionPool

logger = logging.getLogger(__name__)


class GeeCredentialsRepository:
    """GEE 账号凭证的 SQLite 持久化层。

    表结构：
        CREATE TABLE IF NOT EXISTS gee_accounts (
            account_id TEXT PRIMARY KEY,
            account_type TEXT NOT NULL DEFAULT 'service_account',
            display_name TEXT,
            project_id TEXT,
            credentials_encrypted TEXT NOT NULL,  -- AES-GCM 加密的 service_account JSON
            credentials_iv TEXT NOT NULL,         -- 每次加密的随机 IV
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_tested_at TEXT,
            last_test_status TEXT  -- 'ok' / 'failed' / None
        );
    """

    def __init__(self, db_path: str | Path, encryption_key: str = "") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._encryption_key = encryption_key
        # Sprint 3.3: 使用连接池替代每次新建连接（WAL + busy_timeout + 连接复用）
        self._pool = SQLiteConnectionPool(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gee_accounts (
                    account_id TEXT PRIMARY KEY,
                    account_type TEXT NOT NULL DEFAULT 'service_account',
                    display_name TEXT,
                    project_id TEXT,
                    credentials_encrypted TEXT NOT NULL,
                    credentials_iv TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_tested_at TEXT,
                    last_test_status TEXT
                )
                """
            )
            conn.commit()

    def _connect(self):
        """获取连接上下文管理器（从连接池获取，自动 commit/rollback + 归还）。"""
        return self._pool.connection()

    def close(self) -> None:
        """关闭连接池中所有空闲连接。

        测试场景下必须在删除 db 文件前调用（Windows 不允许删除被占用文件）。
        生产场景下连接池生命周期与进程一致，通常无需显式调用。
        """
        self._pool.close_all()

    def __del__(self) -> None:
        try:
            self._pool.close_all(quiet=True)
        except Exception:
            pass

    def _encrypt(self, plaintext: str) -> tuple[str, str]:
        """AES-GCM 加密，返回 (ciphertext_b64, iv_b64)。无 key 时仅 development 允许明文。"""
        if not self._encryption_key:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError(
                    "Cannot store GEE credentials without BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY "
                    "outside development."
                )
            logger.error("GEE credentials encryption key not set, storing plaintext (development only)")
            return plaintext, ""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
            import base64
            import os

            key_bytes = bytes.fromhex(self._encryption_key)
            iv = os.urandom(12)
            aesgcm = AESGCM(key_bytes)
            ct = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
            return base64.b64encode(ct).decode("ascii"), base64.b64encode(iv).decode("ascii")
        except ImportError:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError("cryptography package required to encrypt GEE credentials") from None
            logger.warning("cryptography not installed, storing plaintext")
            return plaintext, ""
        except RuntimeError:
            raise
        except Exception as e:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError(f"Encryption failed for GEE credentials: {e}") from e
            logger.error("Encryption failed for account, storing plaintext: %s", e)
            return plaintext, ""

    def _decrypt(self, ciphertext_b64: str, iv_b64: str) -> str:
        if not self._encryption_key or not iv_b64:
            return ciphertext_b64
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
            import base64

            key_bytes = bytes.fromhex(self._encryption_key)
            iv = base64.b64decode(iv_b64)
            ct = base64.b64decode(ciphertext_b64)
            aesgcm = AESGCM(key_bytes)
            return aesgcm.decrypt(iv, ct, None).decode("utf-8")
        except Exception as e:
            logger.error("Decryption failed: %s", e)
            raise

    def upsert_account(
        self,
        *,
        account_id: str,
        service_account_json: dict[str, Any] | str,
        project_id: Optional[str] = None,
        display_name: Optional[str] = None,
        account_type: str = "service_account",
    ) -> Optional[dict[str, Any]]:
        """新增或更新账号。返回脱敏后的账号信息。"""
        if isinstance(service_account_json, str):
            sa_str = service_account_json
            try:
                sa_dict = json.loads(sa_str)
            except json.JSONDecodeError:
                sa_dict = {}
        else:
            sa_dict = dict(service_account_json)
            sa_str = json.dumps(service_account_json, ensure_ascii=False)

        if not project_id and isinstance(sa_dict, dict) and sa_dict.get("project_id"):
            project_id = sa_dict["project_id"]
        if not display_name and isinstance(sa_dict, dict) and sa_dict.get("client_email"):
            display_name = sa_dict["client_email"]

        ct, iv = self._encrypt(sa_str)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gee_accounts (account_id, account_type, display_name, project_id,
                                           credentials_encrypted, credentials_iv, enabled,
                                           created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    account_type=excluded.account_type,
                    display_name=excluded.display_name,
                    project_id=excluded.project_id,
                    credentials_encrypted=excluded.credentials_encrypted,
                    credentials_iv=excluded.credentials_iv,
                    enabled=1,
                    updated_at=excluded.updated_at
                """,
                (account_id, account_type, display_name, project_id, ct, iv, now, now),
            )
            conn.commit()
        return self.get_account(account_id)

    def get_account(self, account_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gee_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def get_account_credentials(self, account_id: str) -> Optional[dict[str, Any]]:
        """获取解密后的 service_account JSON。供账号池加载使用。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT credentials_encrypted, credentials_iv FROM gee_accounts "
                "WHERE account_id=? AND enabled=1",
                (account_id,),
            ).fetchone()
        if not row:
            return None
        sa_str = self._decrypt(row["credentials_encrypted"], row["credentials_iv"])
        try:
            return json.loads(sa_str)
        except json.JSONDecodeError:
            return None

    def list_accounts(self, include_disabled: bool = False, enabled_only: bool = False) -> list[dict[str, Any]]:
        """列出账号（脱敏）。

        参数优先级：``enabled_only`` > ``include_disabled``。两者都为 False 时仅返回启用账号。
        """
        with self._connect() as conn:
            if enabled_only or not include_disabled:
                rows = conn.execute(
                    "SELECT * FROM gee_accounts WHERE enabled=1 ORDER BY created_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM gee_accounts ORDER BY created_at"
                ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete_account(self, account_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM gee_accounts WHERE account_id=?", (account_id,))
            conn.commit()
            return cur.rowcount > 0

    def set_enabled(self, account_id: str, enabled: bool) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE gee_accounts SET enabled=?, updated_at=? WHERE account_id=?",
                (1 if enabled else 0, datetime.now(timezone.utc).isoformat(), account_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def update_test_status(self, account_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE gee_accounts SET last_tested_at=?, last_test_status=? WHERE account_id=?",
                (datetime.now(timezone.utc).isoformat(), status, account_id),
            )
            conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "account_id": row["account_id"],
            "account_type": row["account_type"],
            "display_name": row["display_name"],
            "project_id": row["project_id"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_tested_at": row["last_tested_at"],
            "last_test_status": row["last_test_status"],
            # 不返回 credentials_encrypted / iv
        }

    def list_enabled_accounts_with_credentials(self) -> list[tuple[str, dict[str, Any], Optional[str]]]:
        """供账号池加载：返回 [(account_id, sa_json, project_id), ...]"""
        result: list[tuple[str, dict[str, Any], Optional[str]]] = []
        for acc in self.list_accounts(enabled_only=True):
            sa = self.get_account_credentials(acc["account_id"])
            if sa:
                result.append((acc["account_id"], sa, acc.get("project_id")))
        return result
