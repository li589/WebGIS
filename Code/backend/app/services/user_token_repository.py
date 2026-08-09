"""Per-user API tokens (X-API-Key) inheriting user role."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services._sqlite_pool import SQLiteConnectionPool


def _users_db_path() -> Path:
    state_dir = Path(settings.workflow_state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "users.sqlite3"


def _token_lookup(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class UserTokenRepository:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or _users_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool = SQLiteConnectionPool(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_api_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token_lookup TEXT NOT NULL UNIQUE,
                    label TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    revoked_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_api_tokens_user "
                "ON user_api_tokens(user_id)"
            )
            conn.commit()

    def create_token(
        self,
        *,
        user_id: int,
        label: str | None = None,
        expires_at: str | None = None,
    ) -> tuple[int, str, str]:
        """创建用户 API Token，返回 ``(id, 明文, created_at)``。

        ``created_at`` 由仓库生成并直接返回，调用方无需二次查询
        （避免 auth_router 里创建后再 list 一遍取时间的小 N+1）。
        """
        plain = f"cgda_{secrets.token_urlsafe(32)}"
        lookup = _token_lookup(plain)
        now = datetime.now(timezone.utc).isoformat()
        with self._pool.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO user_api_tokens
                    (user_id, token_lookup, label, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (user_id, lookup, label, now, expires_at),
            )
            conn.commit()
            return int(cur.lastrowid), plain, now

    def resolve_token(self, token: str) -> dict[str, Any] | None:
        lookup = _token_lookup(token)
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, label, created_at, expires_at, revoked_at
                FROM user_api_tokens WHERE token_lookup=?
                """,
                (lookup,),
            ).fetchone()
        if not row:
            return None
        if row["revoked_at"]:
            return None
        if row["expires_at"]:
            expires = datetime.fromisoformat(str(row["expires_at"]))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                return None
        return dict(row)

    def list_tokens_for_user(self, user_id: int) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, label, created_at, expires_at, revoked_at
                FROM user_api_tokens
                WHERE user_id=? AND revoked_at IS NULL
                ORDER BY id DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_all_active_tokens(self) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT t.id, t.user_id, u.username, t.label, t.created_at,
                       t.expires_at, t.revoked_at
                FROM user_api_tokens t
                JOIN users u ON u.id = t.user_id
                WHERE t.revoked_at IS NULL
                ORDER BY t.id DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def revoke_token(self, token_id: int) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._pool.connection() as conn:
            cur = conn.execute(
                """
                UPDATE user_api_tokens SET revoked_at=?
                WHERE id=? AND revoked_at IS NULL
                """,
                (now, token_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def revoke_tokens_for_user(self, user_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE user_api_tokens SET revoked_at=?
                WHERE user_id=? AND revoked_at IS NULL
                """,
                (now, user_id),
            )
            conn.commit()


_repo: UserTokenRepository | None = None


def get_user_token_repository() -> UserTokenRepository:
    global _repo
    if _repo is None:
        _repo = UserTokenRepository()
    return _repo
