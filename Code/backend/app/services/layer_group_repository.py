"""Runtime-editable layer group (category) repository.

Catalog categories ship as seed JSON (``catalog_seeds/layer_categories.json``)
and stay the offline/codegen source of truth.  This repository layers
runtime-managed state on top of the seeds, persisted in SQLite
(``users.sqlite3``):

* ``layer_groups`` — seed groups are auto-registered (insert-only, so admin
  renames/reorders survive re-syncs); custom groups are fully CRUD-able.
* ``layer_group_assignments`` — per-layer group overrides applied when the
  catalog is served (``descriptor.category``), so moving a layer between
  groups never mutates seed JSON.

Group ids double as ACL resource ids for the ``layer_group`` resource type
(see ``permission_repository``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any

from app.services._sqlite_pool import SQLiteConnectionPool
from app.services.user_repository import _users_db_path

logger = logging.getLogger(__name__)

_GROUP_SOURCE_SEED = "seed"
_GROUP_SOURCE_CUSTOM = "custom"


@dataclass(frozen=True)
class LayerGroupRecord:
    """A runtime layer group row (seed-registered or admin-created)."""

    id: int
    group_id: str
    name: str
    icon: str | None
    accent_color: str | None
    chip_tone: str | None
    sub_categories: list[str]
    position: float
    source: str
    created_at: str
    updated_at: str

    def to_category_def_dict(self) -> dict[str, Any]:
        return {
            "id": self.group_id,
            "name": self.name,
            "icon": self.icon,
            "accent_color": self.accent_color,
            "chip_tone": self.chip_tone,
            "sub_categories": list(self.sub_categories),
            "position": self.position,
            "is_custom": self.source == _GROUP_SOURCE_CUSTOM,
        }


class LayerGroupError(ValueError):
    """Raised on invalid group operations (duplicate id, seed deletion…)."""


class LayerGroupRepository:
    """CRUD for runtime layer groups + per-layer group assignments."""

    def __init__(self, db_path: str | Any | None = None) -> None:
        self.db_path = _users_db_path() if db_path is None else db_path
        self._pool = SQLiteConnectionPool(self.db_path)
        self._seed_synced = False
        # layer_id -> group_id (assignment override only; None = fallback to
        # descriptor category).  Cache is cheap and invalidated on writes.
        self._assignment_cache: dict[str, str | None] | None = None

    # ------------------------------------------------------------------
    # Schema + seed sync
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS layer_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    icon TEXT,
                    accent_color TEXT,
                    chip_tone TEXT,
                    sub_categories TEXT NOT NULL DEFAULT '[]',
                    position REAL NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'custom',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS layer_group_assignments (
                    layer_id TEXT PRIMARY KEY,
                    group_id INTEGER NOT NULL REFERENCES layer_groups(id) ON DELETE CASCADE,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _ensure_seed_groups(self) -> None:
        """Insert missing seed groups (insert-only: admin edits are never clobbered)."""
        if self._seed_synced:
            return
        from app.services.layer_catalog import get_layer_categories

        now = datetime.now(UTC).isoformat()
        with self._pool.connection() as conn:
            for index, cat in enumerate(get_layer_categories()):
                gid = str(cat.get("id", "")).strip()
                if not gid:
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO layer_groups
                        (group_id, name, icon, accent_color, chip_tone,
                         sub_categories, position, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'seed', ?, ?)
                    """,
                    (
                        gid,
                        str(cat.get("name", gid)),
                        cat.get("icon"),
                        cat.get("accent_color"),
                        cat.get("chip_tone"),
                        json.dumps(cat.get("sub_categories") or [], ensure_ascii=False),
                        float(index) * 10.0,
                        now,
                        now,
                    ),
                )
            conn.commit()
        self._seed_synced = True

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_record(row: Any) -> LayerGroupRecord:
        try:
            sub_categories = json.loads(str(row["sub_categories"] or "[]"))
        except Exception:
            sub_categories = []
        return LayerGroupRecord(
            id=int(row["id"]),
            group_id=str(row["group_id"]),
            name=str(row["name"]),
            icon=row["icon"],
            accent_color=row["accent_color"],
            chip_tone=row["chip_tone"],
            sub_categories=[str(s) for s in sub_categories if str(s).strip()],
            position=float(row["position"]),
            source=str(row["source"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def list_groups(self) -> list[LayerGroupRecord]:
        self._ensure_schema()
        self._ensure_seed_groups()
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, group_id, name, icon, accent_color, chip_tone, "
                "sub_categories, position, source, created_at, updated_at "
                "FROM layer_groups ORDER BY position, id"
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_by_group_id(self, group_id: str) -> LayerGroupRecord | None:
        self._ensure_schema()
        self._ensure_seed_groups()
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT id, group_id, name, icon, accent_color, chip_tone, "
                "sub_categories, position, source, created_at, updated_at "
                "FROM layer_groups WHERE group_id=?",
                (group_id,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def list_assignments(self) -> dict[str, str]:
        """Return {layer_id: group_id} for all assignment overrides."""
        self._ensure_schema()
        if self._assignment_cache is not None:
            return {
                lid: gid for lid, gid in self._assignment_cache.items() if gid is not None
            }
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT a.layer_id, g.group_id FROM layer_group_assignments a "
                "JOIN layer_groups g ON g.id = a.group_id"
            ).fetchall()
        mapping = {str(r["layer_id"]): str(r["group_id"]) for r in rows}
        self._assignment_cache = mapping
        return dict(mapping)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_group_id(group_id: str) -> str:
        gid = group_id.strip()
        if not gid:
            raise LayerGroupError("分组 id 不能为空")
        if len(gid) > 64 or not all(c.isalnum() or c in "-_" for c in gid):
            raise LayerGroupError("分组 id 仅允许字母/数字/-/_，长度 ≤ 64")
        return gid.lower()

    def create_group(
        self,
        group_id: str,
        name: str,
        *,
        icon: str | None = None,
        accent_color: str | None = None,
        chip_tone: str | None = None,
        sub_categories: list[str] | None = None,
    ) -> LayerGroupRecord:
        self._ensure_schema()
        self._ensure_seed_groups()
        gid = self._validate_group_id(group_id)
        name = name.strip()
        if not name:
            raise LayerGroupError("分组名称不能为空")
        now = datetime.now(UTC).isoformat()
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM layer_groups WHERE group_id=?", (gid,)
            ).fetchone()
            if row is not None:
                raise LayerGroupError(f"分组 id 已存在: {gid}")
            max_pos = conn.execute(
                "SELECT COALESCE(MAX(position), 0) AS m FROM layer_groups"
            ).fetchone()
            position = float(max_pos["m"]) + 10.0
            conn.execute(
                """
                INSERT INTO layer_groups
                    (group_id, name, icon, accent_color, chip_tone,
                     sub_categories, position, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'custom', ?, ?)
                """,
                (
                    gid,
                    name,
                    icon,
                    accent_color,
                    chip_tone,
                    json.dumps(sub_categories or [], ensure_ascii=False),
                    position,
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_by_group_id(gid)  # type: ignore[return-value]

    def update_group(
        self,
        group_id: str,
        *,
        name: str | None = None,
        icon: str | None = None,
        accent_color: str | None = None,
        chip_tone: str | None = None,
        sub_categories: list[str] | None = None,
    ) -> LayerGroupRecord:
        record = self.get_by_group_id(group_id)
        if record is None:
            raise LayerGroupError(f"分组不存在: {group_id}")
        fields: list[str] = []
        values: list[Any] = []
        if name is not None:
            name = name.strip()
            if not name:
                raise LayerGroupError("分组名称不能为空")
            fields.append("name=?")
            values.append(name)
        for field, value in (
            ("icon", icon),
            ("accent_color", accent_color),
            ("chip_tone", chip_tone),
        ):
            if value is not None:
                fields.append(f"{field}=?")
                values.append(value)
        if sub_categories is not None:
            fields.append("sub_categories=?")
            values.append(json.dumps(sub_categories, ensure_ascii=False))
        if fields:
            fields.append("updated_at=?")
            values.append(datetime.now(UTC).isoformat())
            values.append(record.id)
            with self._pool.connection() as conn:
                conn.execute(
                    f"UPDATE layer_groups SET {', '.join(fields)} WHERE id=?",
                    values,
                )
                conn.commit()
        updated = self.get_by_group_id(record.group_id)
        assert updated is not None
        return updated

    def delete_group(self, group_id: str) -> None:
        record = self.get_by_group_id(group_id)
        if record is None:
            raise LayerGroupError(f"分组不存在: {group_id}")
        if record.source == _GROUP_SOURCE_SEED:
            raise LayerGroupError("种子分组不可删除（来自 layer_categories.json）")
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM layer_group_assignments WHERE group_id=?", (record.id,)
            )
            conn.execute("DELETE FROM layer_groups WHERE id=?", (record.id,))
            conn.commit()
        self.invalidate_cache()

    def reorder_groups(self, ordered_group_ids: list[str]) -> list[LayerGroupRecord]:
        """Rewrite positions to match the given id order (missing ids keep relative tail order)."""
        self._ensure_schema()
        self._ensure_seed_groups()
        known = {g.group_id: g for g in self.list_groups()}
        unknown = [gid for gid in ordered_group_ids if gid not in known]
        if unknown:
            raise LayerGroupError(f"未知分组 id: {', '.join(unknown)}")
        tail = [g.group_id for g in known.values() if g.group_id not in set(ordered_group_ids)]
        full_order = list(ordered_group_ids) + tail
        now = datetime.now(UTC).isoformat()
        with self._pool.connection() as conn:
            for index, gid in enumerate(full_order):
                conn.execute(
                    "UPDATE layer_groups SET position=?, updated_at=? WHERE group_id=?",
                    (float(index) * 10.0, now, gid),
                )
            conn.commit()
        return self.list_groups()

    def set_layer_assignments(self, group_id: str, layer_ids: list[str]) -> dict[str, str]:
        """Replace membership of *group_id* with *layer_ids* (other groups unaffected)."""
        record = self.get_by_group_id(group_id)
        if record is None:
            raise LayerGroupError(f"分组不存在: {group_id}")
        cleaned: list[str] = []
        for lid in layer_ids:
            lid = str(lid).strip()
            if lid and lid not in cleaned:
                cleaned.append(lid)
        now = datetime.now(UTC).isoformat()
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM layer_group_assignments WHERE group_id=?", (record.id,)
            )
            for lid in cleaned:
                conn.execute(
                    """
                    INSERT INTO layer_group_assignments (layer_id, group_id, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(layer_id) DO UPDATE SET
                        group_id=excluded.group_id, updated_at=excluded.updated_at
                    """,
                    (lid, record.id, now),
                )
            conn.commit()
        self.invalidate_cache()
        return self.list_assignments()

    # ------------------------------------------------------------------
    # Resolution (assignment override → descriptor category fallback)
    # ------------------------------------------------------------------

    def resolve_group_id_for_layer(self, layer_id: str, descriptor_category: str | None) -> str | None:
        """Group id for ACL purposes: assignment override wins, else descriptor category."""
        if self._assignment_cache is None:
            self.list_assignments()
        override = (self._assignment_cache or {}).get(layer_id)
        if override is not None:
            return override
        return descriptor_category

    def invalidate_cache(self) -> None:
        self._assignment_cache = None
        # Group membership feeds group-level ACL checks — drop those too.
        from app.services.permission_repository import invalidate_access_cache

        invalidate_access_cache(None)

    def close(self) -> None:
        self._pool.close_all()


_repo: LayerGroupRepository | None = None


def get_layer_group_repository() -> LayerGroupRepository:
    global _repo
    if _repo is None:
        _repo = LayerGroupRepository()
    return _repo


def reset_layer_group_repository_for_tests() -> None:
    global _repo
    if _repo is not None:
        _repo.close()
    _repo = None
