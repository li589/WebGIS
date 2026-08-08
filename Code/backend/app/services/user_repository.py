"""Local user accounts (SQLite)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.core.config import settings
from app.services._sqlite_pool import SQLiteConnectionPool
from app.services.passwords import hash_password, verify_password

UserRole = Literal["admin", "operator", "viewer"]
VALID_ROLES: frozenset[str] = frozenset({"admin", "operator", "viewer"})

# Fixed hash for timing-equalization when username is missing.
_DUMMY_PASSWORD_HASH = hash_password("dummy-timing-equalization-secret")


def _users_db_path() -> Path:
    state_dir = Path(settings.workflow_state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "users.sqlite3"


class UserRepository:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or _users_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool = SQLiteConnectionPool(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'operator',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)"
            )
            conn.commit()

    def close(self) -> None:
        self._pool.close_all()

    def count_users(self) -> int:
        with self._pool.connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return int(row["c"]) if row else 0

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username=? COLLATE NOCASE",
                (username.strip(),),
            ).fetchone()
        return dict(row) if row else None

    def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, username, role, enabled, created_at, updated_at "
                "FROM users ORDER BY id ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def count_admins(self) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE role='admin' AND enabled=1"
            ).fetchone()
        return int(row["c"]) if row else 0

    def verify_credentials(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.get_by_username(username)
        stored = str(user["password_hash"]) if user else _DUMMY_PASSWORD_HASH
        if not verify_password(password, stored):
            return None
        if not user or not user.get("enabled"):
            return None
        return user

    def create_user(
        self,
        *,
        username: str,
        password: str,
        role: UserRole = "operator",
    ) -> dict[str, Any]:
        name = username.strip()
        if not name:
            raise ValueError("username is required")
        if role not in VALID_ROLES:
            raise ValueError(f"invalid role: {role}")
        now = datetime.now(timezone.utc).isoformat()
        pwd_hash = hash_password(password)
        with self._pool.connection() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO users (username, password_hash, role, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (name, pwd_hash, role, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("username already exists") from exc
            user_id = int(cur.lastrowid)
            conn.commit()
        user = self.get_by_id(user_id)
        assert user is not None
        return user

    def update_user(
        self,
        user_id: int,
        *,
        password: str | None = None,
        role: UserRole | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any] | None:
        user = self.get_by_id(user_id)
        if not user:
            return None
        if role is not None and role not in VALID_ROLES:
            raise ValueError(f"invalid role: {role}")
        now = datetime.now(timezone.utc).isoformat()
        fields: list[str] = ["updated_at=?"]
        params: list[Any] = [now]
        if password is not None:
            fields.append("password_hash=?")
            params.append(hash_password(password))
        if role is not None:
            fields.append("role=?")
            params.append(role)
        if enabled is not None:
            fields.append("enabled=?")
            params.append(1 if enabled else 0)
        params.append(user_id)
        with self._pool.connection() as conn:
            conn.execute(
                f"UPDATE users SET {', '.join(fields)} WHERE id=?",
                params,
            )
            conn.commit()
        return self.get_by_id(user_id)

    def delete_user(self, user_id: int) -> bool:
        with self._pool.connection() as conn:
            cur = conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            conn.commit()
            return cur.rowcount > 0

    def upsert_session(
        self,
        *,
        token: str,
        user_id: int,
        username: str,
        role: str,
        expires_at: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (token, user_id, username, role, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET
                    user_id=excluded.user_id,
                    username=excluded.username,
                    role=excluded.role,
                    expires_at=excluded.expires_at
                """,
                (token, user_id, username, role, expires_at, now),
            )
            conn.commit()

    def get_session(self, token: str) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT token, user_id, username, role, expires_at FROM sessions WHERE token=?",
                (token,),
            ).fetchone()
        if not row:
            return None
        expires = datetime.fromisoformat(str(row["expires_at"]))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            self.delete_session(token)
            return None
        return dict(row)

    def delete_session(self, token: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            conn.commit()

    def delete_sessions_for_user(self, user_id: int) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            conn.commit()


_repo: UserRepository | None = None


def get_user_repository() -> UserRepository:
    global _repo
    if _repo is None:
        _repo = UserRepository()
    return _repo
