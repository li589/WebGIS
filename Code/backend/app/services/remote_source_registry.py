"""远程数据源注册表（「可访问远程数据源」别名条目）。

语义：别名条目供下载节点一键填充——
- ``kind=storage_profile`` → ``remote_fetch`` 生成 ``{protocol}://host/{remote_path}?cred={ref_id}``
- ``kind=portal`` → ``http_open_data`` 填 ``preset=ref_id`` + ``relative_path``

本期不做独立 URI scheme，不入侵 remote_sources URI 解析。
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services._sqlite_pool import SQLiteConnectionPool

logger = logging.getLogger(__name__)

VALID_KINDS = frozenset({"storage_profile", "portal"})
VALID_CACHE_POLICIES = frozenset({"standard", "aggressive", "unlimited"})


class RemoteSourceRegistryError(ValueError):
    """注册表操作校验失败。"""


def _db_path() -> Path:
    return (
        Path(settings.gee_credentials_db_path).parent / "research_data_settings.sqlite3"
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class RemoteSourceRegistryRepository:
    """remote_sources 表（与 research_data_settings KV 同库，additive）。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool = SQLiteConnectionPool(self.db_path)
        self._init_schema()

    def _connect(self):
        return self._pool.connection()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS remote_sources (
                    remote_source_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    ref_id TEXT NOT NULL,
                    remote_path TEXT DEFAULT '',
                    display_name TEXT DEFAULT '',
                    cache_policy TEXT NOT NULL DEFAULT 'standard',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # 数据集化改造（阶段 3/6）：additive 扩列（幂等）
            self._ensure_column(conn, "access_mode", "TEXT NOT NULL DEFAULT 'legacy'")
            self._ensure_column(conn, "archived", "INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    @staticmethod
    def _ensure_column(conn, column: str, ddl_type: str) -> None:
        """SQLite ALTER ADD COLUMN 幂等保护（缺列才加）。"""
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(remote_sources)").fetchall()
        }
        if column in cols:
            return
        try:
            conn.execute(f"ALTER TABLE remote_sources ADD COLUMN {column} {ddl_type}")
        except sqlite3.OperationalError:
            # 并发初始化（多 worker）时另一进程已加列
            pass

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def list_entries(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM remote_sources ORDER BY remote_source_id"
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get(self, remote_source_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM remote_sources WHERE remote_source_id = ?",
                (str(remote_source_id),),
            ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def upsert(
        self,
        *,
        remote_source_id: str,
        kind: str,
        ref_id: str,
        remote_path: str = "",
        display_name: str = "",
        cache_policy: str = "standard",
        access_mode: str = "legacy",
    ) -> dict[str, Any]:
        rid = str(remote_source_id or "").strip()
        if not rid:
            raise RemoteSourceRegistryError("remote_source_id must not be empty")
        if kind not in VALID_KINDS:
            raise RemoteSourceRegistryError(
                f"Invalid kind: {kind}; expected one of {sorted(VALID_KINDS)}"
            )
        if not str(ref_id or "").strip():
            raise RemoteSourceRegistryError("ref_id must not be empty")
        if cache_policy not in VALID_CACHE_POLICIES:
            raise RemoteSourceRegistryError(
                "Invalid cache_policy: "
                f"{cache_policy}; expected one of {sorted(VALID_CACHE_POLICIES)}"
            )
        if access_mode not in ("legacy", "site_compatible"):
            raise RemoteSourceRegistryError(
                f"Invalid access_mode: {access_mode}; expected legacy|site_compatible"
            )

        existing = self.get(rid)
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO remote_sources (
                    remote_source_id, kind, ref_id, remote_path, display_name,
                    cache_policy, access_mode, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(remote_source_id) DO UPDATE SET
                    kind = excluded.kind,
                    ref_id = excluded.ref_id,
                    remote_path = excluded.remote_path,
                    display_name = excluded.display_name,
                    cache_policy = excluded.cache_policy,
                    access_mode = excluded.access_mode,
                    updated_at = excluded.updated_at
                """,
                (
                    rid,
                    kind,
                    str(ref_id).strip(),
                    str(remote_path or "").strip(),
                    str(display_name or "").strip(),
                    cache_policy,
                    access_mode,
                    (existing or {}).get("created_at") or now,
                    now,
                ),
            )
            conn.commit()
        return self.get(rid) or {}

    def delete(self, remote_source_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM remote_sources WHERE remote_source_id = ?",
                (str(remote_source_id),),
            )
            conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._pool.close_all()


_repo_instance: RemoteSourceRegistryRepository | None = None


def get_remote_source_registry() -> RemoteSourceRegistryRepository:
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = RemoteSourceRegistryRepository(_db_path())
    return _repo_instance


def list_remote_sources_with_capabilities() -> list[dict[str, Any]]:
    """注册表条目 + 引用源能力徽标数据（protocol/search_capability/enabled 等）。"""
    entries = get_remote_source_registry().list_entries()
    storage_profiles: dict[str, dict[str, Any]] = {}
    try:
        from app.services.config_remote_storage import list_remote_storage_profiles

        storage_profiles = {
            str(p.get("profile_id")): p
            for p in list_remote_storage_profiles(include_disabled=True)
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("remote source registry: list storage profiles failed: %s", exc)

    portals: dict[str, dict[str, Any]] = {}
    try:
        from app.services.portal_catalog import list_portal_defs

        portals = {pid: d.to_public() for pid, d in list_portal_defs().items()}
    except Exception as exc:  # noqa: BLE001
        logger.debug("remote source registry: list portals failed: %s", exc)

    out: list[dict[str, Any]] = []
    for entry in entries:
        item = dict(entry)
        if entry["kind"] == "storage_profile":
            profile = storage_profiles.get(str(entry["ref_id"]))
            item["ref"] = (
                {
                    "protocol": (profile or {}).get("protocol"),
                    "enabled": (profile or {}).get("enabled"),
                    "last_test_status": (profile or {}).get("last_test_status"),
                    "display_name": (profile or {}).get("display_name") or "",
                }
                if profile
                else None
            )
        else:
            portal = portals.get(str(entry["ref_id"]))
            item["ref"] = (
                {
                    "protocol": "http",
                    "search_capability": (portal or {}).get("search_capability"),
                    "requires_credentials": (portal or {}).get("requires_credentials"),
                    "name": (portal or {}).get("name") or "",
                }
                if portal
                else None
            )
        item["ref_exists"] = item["ref"] is not None
        out.append(item)
    return out
