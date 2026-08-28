"""Resource-level access control repository (SQLite).

Stores per-user resource permissions (allow/deny) for layers, workflow
definitions, and data sources.  Supports two modes:

* ``open`` (black-list): no ``deny`` record means allowed.
* ``whitelist``: only resources with an ``allow`` record are accessible.

Admin role always bypasses permission checks (handled in ``deps.py``).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any, Literal

from app.services._sqlite_pool import SQLiteConnectionPool
from app.services.user_repository import _users_db_path

logger = logging.getLogger(__name__)

ResourceType = Literal["layer", "workflow", "data_source"]
PermissionValue = Literal["allow", "deny"]
PermissionMode = Literal["open", "whitelist"]

_VALID_RESOURCE_TYPES: frozenset[str] = frozenset({"layer", "workflow", "data_source"})
_VALID_PERMISSIONS: frozenset[str] = frozenset({"allow", "deny"})
_VALID_MODES: frozenset[str] = frozenset({"open", "whitelist"})


@dataclass(frozen=True)
class UserResourcePermission:
    """A single resource permission record."""

    id: int
    user_id: int
    resource_type: str
    resource_id: str
    permission: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PermissionInput:
    """Input payload for setting a permission (no auto-generated fields)."""

    resource_type: str
    resource_id: str
    permission: str


# ---------------------------------------------------------------------------
# Cache: check_resource_access results cached per (user_id, resource_type)
# with a short TTL to avoid repeated DB hits on hot paths (e.g. tile requests).
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS: float = 30.0
_access_cache: dict[tuple[int, str, str], tuple[bool, float]] = {}


def _cache_get(key: tuple[int, str, str]) -> bool | None:
    entry = _access_cache.get(key)
    if entry is None:
        return None
    result, expires_at = entry
    if time.monotonic() > expires_at:
        _access_cache.pop(key, None)
        return None
    return result


def _cache_set(key: tuple[int, str, str], value: bool) -> None:
    _access_cache[key] = (value, time.monotonic() + _CACHE_TTL_SECONDS)


def invalidate_access_cache(user_id: int | None = None) -> None:
    """Invalidate cached access-check results.

    Call after modifying permissions for *user_id* (or all users when
    *user_id* is ``None``).
    """
    if user_id is None:
        _access_cache.clear()
    else:
        keys_to_remove = [k for k in _access_cache if k[0] == user_id]
        for k in keys_to_remove:
            _access_cache.pop(k, None)


class PermissionRepository:
    """CRUD + access-check for ``user_resource_permissions`` table."""

    def __init__(self, db_path: str | Any | None = None) -> None:
        self.db_path = _users_db_path() if db_path is None else db_path
        self._pool = SQLiteConnectionPool(self.db_path)
        # Schema is created by UserRepository._init_schema(); we only need
        # the table to exist.  Calling _init_schema defensively is safe
        # because CREATE TABLE IF NOT EXISTS is idempotent.
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Idempotent table creation (delegates to the same DDL as UserRepository)."""
        with self._pool.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_resource_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, resource_type, resource_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_permissions_user "
                "ON user_resource_permissions(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_permissions_user_type "
                "ON user_resource_permissions(user_id, resource_type)"
            )
            conn.commit()

    def close(self) -> None:
        self._pool.close_all()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_user_permissions(self, user_id: int) -> list[UserResourcePermission]:
        """Return all permission records for *user_id*."""
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, user_id, resource_type, resource_id, permission, "
                "created_at, updated_at "
                "FROM user_resource_permissions WHERE user_id=? "
                "ORDER BY resource_type, resource_id",
                (user_id,),
            ).fetchall()
        return [
            UserResourcePermission(
                id=int(r["id"]),
                user_id=int(r["user_id"]),
                resource_type=str(r["resource_type"]),
                resource_id=str(r["resource_id"]),
                permission=str(r["permission"]),
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    def set_user_permissions(
        self, user_id: int, permissions: list[PermissionInput]
    ) -> list[UserResourcePermission]:
        """Replace all permissions for *user_id* in a single transaction.

        Existing records are deleted, then the new set is inserted.
        Callers should validate inputs before calling.
        """
        for p in permissions:
            if p.resource_type not in _VALID_RESOURCE_TYPES:
                raise ValueError(f"invalid resource_type: {p.resource_type}")
            if p.permission not in _VALID_PERMISSIONS:
                raise ValueError(f"invalid permission: {p.permission}")
            if not p.resource_id.strip():
                raise ValueError("resource_id is required")

        now = datetime.now(UTC).isoformat()
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM user_resource_permissions WHERE user_id=?", (user_id,)
            )
            for p in permissions:
                conn.execute(
                    """
                    INSERT INTO user_resource_permissions
                        (user_id, resource_type, resource_id, permission, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, resource_type, resource_id) DO UPDATE SET
                        permission=excluded.permission,
                        updated_at=excluded.updated_at
                    """,
                    (
                        user_id,
                        p.resource_type,
                        p.resource_id.strip(),
                        p.permission,
                        now,
                        now,
                    ),
                )
            conn.commit()
        invalidate_access_cache(user_id)
        return self.get_user_permissions(user_id)

    def delete_permission(self, permission_id: int) -> bool:
        """Delete a single permission record by ID. Returns True if deleted."""
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT user_id FROM user_resource_permissions WHERE id=?",
                (permission_id,),
            ).fetchone()
            if row is None:
                return False
            cur = conn.execute(
                "DELETE FROM user_resource_permissions WHERE id=?", (permission_id,)
            )
            conn.commit()
        if cur.rowcount > 0:
            invalidate_access_cache(int(row["user_id"]))
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Permission mode
    # ------------------------------------------------------------------

    def get_permission_mode(self, user_id: int) -> str:
        """Return effective permission mode (user override, else theme default)."""
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT permission_mode, theme_id FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
        if row is None:
            return "open"
        raw_mode = row["permission_mode"] if isinstance(row, dict) else row[0]
        mode = str(raw_mode) if raw_mode is not None else ""
        if mode in _VALID_MODES:
            return mode
        # Inherit theme default when user mode missing/invalid
        theme_id = row["theme_id"] if isinstance(row, dict) else None
        if theme_id is not None:
            try:
                from app.services.theme_repository import get_theme_repository

                theme = get_theme_repository().get_by_id(int(theme_id))
                if theme and theme.default_permission_mode in _VALID_MODES:
                    return theme.default_permission_mode
            except Exception:
                logger.debug("theme mode lookup failed for user %s", user_id, exc_info=True)
        return "open"

    def set_permission_mode(self, user_id: int, mode: str) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(f"invalid permission_mode: {mode}")
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE users SET permission_mode=?, updated_at=? WHERE id=?",
                (mode, datetime.now(UTC).isoformat(), user_id),
            )
            conn.commit()
        invalidate_access_cache(user_id)

    # ------------------------------------------------------------------
    # Access check (theme defaults ⊕ user overrides)
    # ------------------------------------------------------------------

    def _user_theme_id(self, user_id: int) -> int | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT theme_id FROM users WHERE id=?", (user_id,)
            ).fetchone()
        if row is None:
            return None
        tid = row["theme_id"] if isinstance(row, dict) else row[0]
        return int(tid) if tid is not None else None

    def _theme_perm_map(
        self, theme_id: int | None, resource_type: str
    ) -> dict[str, str]:
        if theme_id is None:
            return {}
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT resource_id, permission FROM theme_resource_permissions "
                "WHERE theme_id=? AND resource_type=?",
                (theme_id, resource_type),
            ).fetchall()
        return {str(r["resource_id"]): str(r["permission"]) for r in rows}

    def _merged_permission(
        self,
        user_perm: str | None,
        theme_perm: str | None,
        mode: str,
    ) -> bool:
        """User override wins; else theme; else mode default."""
        effective = user_perm if user_perm is not None else theme_perm
        if mode == "whitelist":
            return effective == "allow"
        # open: deny only on explicit deny
        return effective != "deny"

    def check_resource_access(
        self, user_id: int, resource_type: str, resource_id: str
    ) -> bool:
        """Check if *user_id* may access ``resource_type/resource_id``.

        Merge: user override > theme default > mode (open/whitelist).
        """
        cache_key = (user_id, resource_type, resource_id)
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        mode = self.get_permission_mode(user_id)
        theme_id = self._user_theme_id(user_id)
        with self._pool.connection() as conn:
            user_row = conn.execute(
                "SELECT permission FROM user_resource_permissions "
                "WHERE user_id=? AND resource_type=? AND resource_id=?",
                (user_id, resource_type, resource_id),
            ).fetchone()
            theme_row = None
            if theme_id is not None:
                theme_row = conn.execute(
                    "SELECT permission FROM theme_resource_permissions "
                    "WHERE theme_id=? AND resource_type=? AND resource_id=?",
                    (theme_id, resource_type, resource_id),
                ).fetchone()

        user_perm = str(user_row["permission"]) if user_row is not None else None
        theme_perm = str(theme_row["permission"]) if theme_row is not None else None
        result = self._merged_permission(user_perm, theme_perm, mode)

        _cache_set(cache_key, result)
        return result

    def batch_filter_accessible(
        self,
        user_id: int,
        resource_type: str,
        resource_ids: list[str],
    ) -> list[str]:
        """Return the subset of *resource_ids* the user may access.

        More efficient than calling ``check_resource_access`` per item:
        loads user + theme permission maps for the type in two queries.
        """
        if not resource_ids:
            return []
        mode = self.get_permission_mode(user_id)
        theme_id = self._user_theme_id(user_id)
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT resource_id, permission FROM user_resource_permissions "
                "WHERE user_id=? AND resource_type=?",
                (user_id, resource_type),
            ).fetchall()
        user_map: dict[str, str] = {
            str(r["resource_id"]): str(r["permission"]) for r in rows
        }
        theme_map = self._theme_perm_map(theme_id, resource_type)

        out: list[str] = []
        for rid in resource_ids:
            user_perm = user_map.get(rid)
            theme_perm = theme_map.get(rid)
            # .get returns None if missing — distinguish from missing vs present
            u = user_perm if rid in user_map else None
            t = theme_perm if rid in theme_map else None
            if self._merged_permission(u, t, mode):
                out.append(rid)
        return out


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_repo: PermissionRepository | None = None


def get_permission_repository() -> PermissionRepository:
    global _repo
    if _repo is None:
        _repo = PermissionRepository()
    return _repo


def reset_permission_repository_for_tests() -> None:
    """Drop singleton + access cache so pytest fixtures can patch a fresh DB."""
    global _repo
    if _repo is not None:
        _repo.close()
    _repo = None
    invalidate_access_cache(None)
