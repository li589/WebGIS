"""天气源 Provider 配置持久化层（SQLite + AES-GCM）。

存储 Provider 的运行时配置覆盖（enabled、priority、自定义 config），
启动时由 ``config_service.apply_persisted_provider_overrides()`` 应用到 registry。

表结构：
    CREATE TABLE IF NOT EXISTS weather_providers (
        provider_id TEXT PRIMARY KEY,
        display_name TEXT,
        provider_type TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        priority INTEGER NOT NULL DEFAULT 100,
        config_encrypted TEXT,        -- AES-GCM 加密的配置 JSON（可能为空，表示无覆盖）
        config_iv TEXT,
        last_tested_at TEXT,
        last_test_status TEXT,        -- 'ok' / 'failed' / NULL
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

注意：
- Provider 实例本身由代码定义（如 ``OpenMeteoProvider`` 类），数据库仅存"覆盖配置"
- 内置 Provider（如 open-meteo）的 display_name/type 在代码中已声明，DB 字段仅作冗余展示
- 第三方 Provider 的元数据完全由 DB 提供（未来扩展）
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.services._sqlite_pool import SQLiteConnectionPool

logger = logging.getLogger(__name__)


class WeatherProvidersRepository:
    """Provider 配置持久化层。

    与 ``GeeCredentialsRepository`` 共享加密 key（``gee_credentials_encryption_key``）。
    """

    def __init__(self, db_path: str | Path, encryption_key: str = "") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._encryption_key = encryption_key
        # Sprint 3.4: 使用连接池替代每次新建连接（WAL + busy_timeout + 连接复用）
        # 原 _connect 中手动设置 PRAGMA journal_mode=WAL/synchronous=NORMAL 已由连接池统一管理
        self._pool = SQLiteConnectionPool(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS weather_providers (
                    provider_id TEXT PRIMARY KEY,
                    display_name TEXT,
                    provider_type TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 100,
                    config_encrypted TEXT,
                    config_iv TEXT,
                    last_tested_at TEXT,
                    last_test_status TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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

    # ── 加密 / 解密（与 GeeCredentialsRepository 一致） ──────────────────────

    def _encrypt(self, plaintext: str) -> tuple[str, str]:
        """AES-GCM 加密，返回 (ciphertext_b64, iv_b64)。无 key 时仅 development 允许明文。"""
        if not self._encryption_key:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError(
                    "Cannot store weather provider config without BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY "
                    "outside development."
                )
            logger.error("Weather provider encryption key not set, storing plaintext (development only)")
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
                raise RuntimeError("cryptography package required to encrypt weather provider config") from None
            logger.warning("cryptography not installed, storing plaintext")
            return plaintext, ""
        except RuntimeError:
            raise
        except Exception as e:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError(f"Encryption failed for weather provider config: {e}") from e
            logger.error("Encryption failed for weather provider config, storing plaintext: %s", e)
            return plaintext, ""

    def _decrypt(self, ciphertext_b64: str, iv_b64: str) -> str:
        # Sprint 3.3: 无 key 时记录 warning，避免静默返回密文。
        # dev 模式下 _encrypt 存储明文 + 空 IV（secrets_encryption_required()=False），
        # 此处返回 ciphertext_b64（即明文）以保持 round-trip；
        # 生产模式下 assert_encryption_policy() 会在启动时拒绝无 key 状态，故此分支不会在生产路径触发。
        # 与 api_keys_repository / gee_credentials_repository 保持一致的降级策略。
        if not self._encryption_key or not iv_b64:
            if ciphertext_b64:
                logger.warning(
                    "Decrypting weather provider config without encryption key (dev-mode plaintext round-trip)"
                )
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
            logger.error("Decryption failed for weather provider config: %s", e)
            raise

    # ── CRUD ────────────────────────────────────────────────────────────────

    def upsert_provider(
        self,
        *,
        provider_id: str,
        display_name: Optional[str] = None,
        provider_type: Optional[str] = None,
        enabled: bool = True,
        priority: int = 100,
        config: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any] | None:
        """新增或更新 Provider 配置覆盖。返回脱敏后的记录。"""
        now = datetime.now(timezone.utc).isoformat()

        # 加密配置（如有）
        if config is not None:
            config_str = json.dumps(config, ensure_ascii=False)
            config_enc, config_iv = self._encrypt(config_str)
        else:
            config_enc, config_iv = None, None

        with self._connect() as conn:
            # 检查是否已存在（保留 last_tested_at / last_test_status）
            existing = conn.execute(
                "SELECT last_tested_at, last_test_status FROM weather_providers WHERE provider_id=?",
                (provider_id,),
            ).fetchone()
            last_tested_at = existing["last_tested_at"] if existing else None
            last_test_status = existing["last_test_status"] if existing else None

            conn.execute(
                """
                INSERT INTO weather_providers (
                    provider_id, display_name, provider_type, enabled, priority,
                    config_encrypted, config_iv,
                    last_tested_at, last_test_status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    provider_type=excluded.provider_type,
                    enabled=excluded.enabled,
                    priority=excluded.priority,
                    config_encrypted=excluded.config_encrypted,
                    config_iv=excluded.config_iv,
                    updated_at=excluded.updated_at
                """,
                (
                    provider_id, display_name, provider_type,
                    1 if enabled else 0, priority,
                    config_enc, config_iv,
                    last_tested_at, last_test_status,
                    now, now,
                ),
            )
            conn.commit()
        return self.get_provider(provider_id)

    def get_provider(self, provider_id: str) -> dict[str, Any] | None:
        """获取单个 Provider 配置（含解密后的 config）。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM weather_providers WHERE provider_id=?",
                (provider_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def list_providers(self, include_disabled: bool = True) -> list[dict[str, Any]]:
        """列出所有 Provider 配置。"""
        with self._connect() as conn:
            if include_disabled:
                rows = conn.execute(
                    "SELECT * FROM weather_providers ORDER BY priority ASC, provider_id ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM weather_providers WHERE enabled=1 ORDER BY priority ASC, provider_id ASC"
                ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete_provider(self, provider_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM weather_providers WHERE provider_id=?",
                (provider_id,),
            )
            conn.commit()
            return cur.rowcount > 0

    def set_enabled(self, provider_id: str, enabled: bool) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE weather_providers SET enabled=?, updated_at=? WHERE provider_id=?",
                (1 if enabled else 0, datetime.now(timezone.utc).isoformat(), provider_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def set_priority(self, provider_id: str, priority: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE weather_providers SET priority=?, updated_at=? WHERE provider_id=?",
                (priority, datetime.now(timezone.utc).isoformat(), provider_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def update_test_status(self, provider_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE weather_providers SET last_tested_at=?, last_test_status=? WHERE provider_id=?",
                (datetime.now(timezone.utc).isoformat(), status, provider_id),
            )
            conn.commit()

    # ── 内部工具 ─────────────────────────────────────────────────────────────

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        # 解密 config
        config: dict[str, Any] | None = None
        config_enc = row["config_encrypted"]
        config_iv = row["config_iv"]
        if config_enc:
            try:
                config_str = self._decrypt(config_enc, config_iv or "")
                config = json.loads(config_str) if config_str else None
            except Exception as e:
                logger.warning("Failed to decrypt config for provider %s: %s", row["provider_id"], e)
                config = None

        return {
            "provider_id": row["provider_id"],
            "display_name": row["display_name"],
            "provider_type": row["provider_type"],
            "enabled": bool(row["enabled"]),
            "priority": row["priority"],
            "config": config,
            "last_tested_at": row["last_tested_at"],
            "last_test_status": row["last_test_status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
