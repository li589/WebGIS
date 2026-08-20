"""远程数据集授权注册表（「具体数据集选取模式」白名单）。

语义（plan §1.1/§1.3）：
- 每条 grant = 门户(portal_id) + 数据集规范标识(dataset_key) 的授权；
  同一门户可配多个数据集（UNIQUE(portal_id, dataset_key) 幂等合并）。
- 有效权限(portal) = 站点兼容开关生效 OR dataset_key/路径前缀命中 grants（并集）。
- 未配置任何授权的门户视为「未管控」→ 放行（向后兼容）。

与 remote_source_registry 同库（research_data_settings.sqlite3），additive。
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

VALID_PROVIDER_KINDS = frozenset({"", "cmr", "cdse_odata", "cds", "builtin_node"})


class RemoteDatasetGrantsError(ValueError):
    """授权注册表操作校验失败。"""


def _db_path() -> Path:
    return (
        Path(settings.gee_credentials_db_path).parent / "research_data_settings.sqlite3"
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_path_prefix(raw: str) -> list[str]:
    """path_prefix 字段（多前缀换行分隔）→ 去空白前缀列表。"""
    return [p.strip().strip("/") for p in str(raw or "").splitlines() if p.strip()]


class RemoteDatasetGrantsRepository:
    """remote_dataset_grants 表（与 research_data_settings KV 同库，additive）。"""

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
                CREATE TABLE IF NOT EXISTS remote_dataset_grants (
                    grant_id TEXT PRIMARY KEY,
                    portal_id TEXT NOT NULL,
                    dataset_key TEXT NOT NULL,
                    dataset_title TEXT DEFAULT '',
                    dataset_description TEXT DEFAULT '',
                    provider_kind TEXT DEFAULT '',
                    time_start TEXT DEFAULT '',
                    time_end TEXT DEFAULT '',
                    path_prefix TEXT DEFAULT '',
                    search_meta TEXT DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    archived INTEGER NOT NULL DEFAULT 0,
                    migrated_from TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(portal_id, dataset_key)
                )
                """
            )
            conn.commit()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def list_entries(self, *, include_archived: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM remote_dataset_grants"
        if not include_archived:
            query += " WHERE archived = 0"
        query += " ORDER BY portal_id, dataset_key"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get(self, grant_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM remote_dataset_grants WHERE grant_id = ?",
                (str(grant_id),),
            ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def find(self, *, portal_id: str, dataset_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM remote_dataset_grants"
                " WHERE portal_id = ? AND dataset_key = ?",
                (str(portal_id), str(dataset_key)),
            ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def upsert(
        self,
        *,
        grant_id: str = "",
        portal_id: str,
        dataset_key: str,
        dataset_title: str = "",
        dataset_description: str = "",
        provider_kind: str = "",
        time_start: str = "",
        time_end: str = "",
        path_prefix: str = "",
        search_meta: str = "{}",
        enabled: bool = True,
        archived: bool = False,
        migrated_from: str = "",
    ) -> dict[str, Any]:
        pid = str(portal_id or "").strip()
        dkey = str(dataset_key or "").strip()
        if not pid:
            raise RemoteDatasetGrantsError("portal_id must not be empty")
        if not dkey:
            raise RemoteDatasetGrantsError("dataset_key must not be empty")
        if provider_kind not in VALID_PROVIDER_KINDS:
            raise RemoteDatasetGrantsError(
                f"Invalid provider_kind: {provider_kind};"
                f" expected one of {sorted(VALID_PROVIDER_KINDS)}"
            )
        if not str(search_meta or "").strip():
            search_meta = "{}"
        # search_meta 必须是合法 JSON（快照字段，前端可能携带检索结果）
        import json as _json

        try:
            _json.loads(search_meta)
        except (TypeError, ValueError) as exc:
            raise RemoteDatasetGrantsError(
                f"search_meta must be valid JSON: {exc}"
            ) from exc

        # grant_id 未指定 → 由 portal/dataset 派生（如 nasa_cmr/GLDAS_NOAH025_3H
        # → nasa_cmr__GLDAS_NOAH025_3H）；同时用于 UNIQUE(portal_id, dataset_key)
        # 冲突时定位既有条目做幂等合并。
        existing = self.find(portal_id=pid, dataset_key=dkey)
        gid = (
            str(grant_id or "").strip()
            or (existing or {}).get("grant_id")
            or f"{pid}__{dkey}"
        )
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO remote_dataset_grants (
                    grant_id, portal_id, dataset_key, dataset_title,
                    dataset_description, provider_kind, time_start, time_end,
                    path_prefix, search_meta, enabled, archived, migrated_from,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(grant_id) DO UPDATE SET
                    portal_id = excluded.portal_id,
                    dataset_key = excluded.dataset_key,
                    dataset_title = excluded.dataset_title,
                    dataset_description = excluded.dataset_description,
                    provider_kind = excluded.provider_kind,
                    time_start = excluded.time_start,
                    time_end = excluded.time_end,
                    path_prefix = excluded.path_prefix,
                    search_meta = excluded.search_meta,
                    enabled = excluded.enabled,
                    archived = excluded.archived,
                    migrated_from = excluded.migrated_from,
                    updated_at = excluded.updated_at
                """,
                (
                    gid,
                    pid,
                    dkey,
                    str(dataset_title or "").strip(),
                    str(dataset_description or "").strip(),
                    provider_kind,
                    str(time_start or ""),
                    str(time_end or ""),
                    str(path_prefix or "").strip(),
                    str(search_meta),
                    1 if enabled else 0,
                    1 if archived else 0,
                    str(migrated_from or ""),
                    (existing or {}).get("created_at") or now,
                    now,
                ),
            )
            conn.commit()
        return self.get(gid) or {}

    def set_enabled(self, grant_id: str, enabled: bool) -> dict[str, Any] | None:
        entry = self.get(grant_id)
        if entry is None:
            return None
        with self._connect() as conn:
            conn.execute(
                "UPDATE remote_dataset_grants SET enabled = ?, updated_at = ?"
                " WHERE grant_id = ?",
                (1 if enabled else 0, _now_iso(), str(grant_id)),
            )
            conn.commit()
        return self.get(grant_id)

    def delete(self, grant_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM remote_dataset_grants WHERE grant_id = ?",
                (str(grant_id),),
            )
            conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._pool.close_all()


_repo_instance: RemoteDatasetGrantsRepository | None = None


def get_remote_dataset_grants() -> RemoteDatasetGrantsRepository:
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = RemoteDatasetGrantsRepository(_db_path())
    return _repo_instance


def reset_remote_dataset_grants_singleton() -> None:
    """Test helper: drop singleton (each test uses its own tmp db)."""
    global _repo_instance
    if _repo_instance is not None:
        try:
            _repo_instance.close()
        except Exception:  # noqa: BLE001
            pass
    _repo_instance = None


def list_grants_with_badges() -> list[dict[str, Any]]:
    """授权条目 + 门户能力徽标（复用 RemoteSourceRefBadge 语义）。"""
    entries = get_remote_dataset_grants().list_entries()
    portals: dict[str, dict[str, Any]] = {}
    try:
        from app.services.portal_catalog import list_portal_defs

        portals = {pid: d.to_public() for pid, d in list_portal_defs().items()}
    except Exception as exc:  # noqa: BLE001
        logger.debug("remote dataset grants: list portals failed: %s", exc)

    out: list[dict[str, Any]] = []
    for entry in entries:
        item = dict(entry)
        portal = portals.get(str(entry["portal_id"]))
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


def build_remote_dataset_policy() -> list[dict[str, Any]]:
    """编辑器过滤/提交校验消费的策略投影（plan §3 RemoteDatasetPolicy）。

    每门户一条：``{portal_id, managed, compatible, datasets: [...]}``。
    - compatible：该门户存在「站点兼容」条目（remote_sources 中
      kind=portal、ref_id=portal、remote_path='' 的启用条目；
      阶段 3 起以 access_mode='site_compatible' 为准）。
    - managed：compatible OR 存在启用且未归档的 grant。
    - 未出现在返回列表中的门户 = 未管控 → 消费方放行。
    """
    grants = [
        g
        for g in get_remote_dataset_grants().list_entries(include_archived=False)
        if g.get("enabled")
    ]
    grants_by_portal: dict[str, list[dict[str, Any]]] = {}
    for g in grants:
        grants_by_portal.setdefault(str(g["portal_id"]), []).append(g)

    compatible_portals: set[str] = set()
    try:
        from app.services.remote_source_registry import get_remote_source_registry

        for entry in get_remote_source_registry().list_entries():
            if (
                entry.get("kind") == "portal"
                and not str(entry.get("remote_path") or "").strip()
            ):
                compatible_portals.add(str(entry.get("ref_id")))
    except Exception as exc:  # noqa: BLE001
        logger.debug("remote dataset policy: list remote sources failed: %s", exc)

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pid, items in sorted(grants_by_portal.items()):
        seen.add(pid)
        out.append(
            {
                "portal_id": pid,
                "managed": True,
                "compatible": pid in compatible_portals,
                "datasets": [
                    {
                        "grant_id": g.get("grant_id"),
                        "dataset_key": g.get("dataset_key"),
                        "title": g.get("dataset_title") or g.get("dataset_key"),
                        "path_prefix": parse_path_prefix(g.get("path_prefix") or ""),
                    }
                    for g in items
                ],
            }
        )
    # 仅有兼容开关、无数据集授权的门户也要进入策略（managed=True, datasets=[]）
    for pid in sorted(compatible_portals - seen):
        out.append(
            {
                "portal_id": pid,
                "managed": True,
                "compatible": True,
                "datasets": [],
            }
        )
    return out
