"""Runtime-editable layer group (category) repository.

Catalog categories ship as seed JSON (``catalog_seeds/layer_categories.json``)
and stay the offline/codegen source of truth.  This repository layers
runtime-managed state on top of the seeds, persisted in SQLite
(``users.sqlite3``):

* ``layer_groups`` — seed groups are auto-registered under ``owner_user_id=0``
  (insert-only); each admin's custom groups and seed overrides live under
  their own ``owner_user_id``.
* ``layer_group_assignments`` — per-(owner, layer) group overrides applied
  when the catalog is served.
* ``theme_layer_group_presets`` — optional JSON snapshot of an admin's
  workspace, applied for non-admin users bound to that theme.

Group ids double as ACL resource ids for the ``layer_group`` resource type
(see ``permission_repository``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any, Literal

from app.services._sqlite_pool import SQLiteConnectionPool
from app.services.user_repository import _users_db_path

logger = logging.getLogger(__name__)

OWNER_SHARED = 0
_GROUP_SOURCE_SEED = "seed"
_GROUP_SOURCE_CUSTOM = "custom"
_GROUP_SOURCE_OVERRIDE = "override"

ScopeKind = Literal["shared", "personal", "theme"]


@dataclass(frozen=True)
class CatalogGroupScope:
    """How to resolve layer groups / assignments for a request."""

    kind: ScopeKind
    owner_user_id: int = OWNER_SHARED
    theme_id: int | None = None

    @classmethod
    def shared(cls) -> CatalogGroupScope:
        return cls(kind="shared", owner_user_id=OWNER_SHARED)

    @classmethod
    def personal(cls, owner_user_id: int) -> CatalogGroupScope:
        return cls(kind="personal", owner_user_id=int(owner_user_id))

    @classmethod
    def theme(cls, theme_id: int) -> CatalogGroupScope:
        return cls(kind="theme", theme_id=int(theme_id))


@dataclass(frozen=True)
class LayerGroupRecord:
    """A runtime layer group row (seed-registered, override, or admin-created)."""

    id: int
    group_id: str
    name: str
    icon: str | None
    accent_color: str | None
    chip_tone: str | None
    sub_categories: list[str]
    position: float
    source: str
    owner_user_id: int
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
        # Cache key = owner_user_id (theme scopes bypass this cache).
        self._assignment_cache: dict[int, dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Schema + seed sync
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS layer_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    icon TEXT,
                    accent_color TEXT,
                    chip_tone TEXT,
                    sub_categories TEXT NOT NULL DEFAULT '[]',
                    position REAL NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'custom',
                    owner_user_id INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(owner_user_id, group_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS layer_group_assignments (
                    owner_user_id INTEGER NOT NULL DEFAULT 0,
                    layer_id TEXT NOT NULL,
                    group_row_id INTEGER NOT NULL REFERENCES layer_groups(id) ON DELETE CASCADE,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (owner_user_id, layer_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS theme_layer_group_presets (
                    theme_id INTEGER PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by_user_id INTEGER
                )
                """
            )
            self._migrate_legacy_schema(conn)
            conn.commit()

    def _migrate_legacy_schema(self, conn: Any) -> None:
        """Upgrade pre-owner-scoped tables in place when needed."""
        group_cols = {
            str(r["name"]) for r in conn.execute("PRAGMA table_info(layer_groups)").fetchall()
        }
        assign_cols = {
            str(r["name"])
            for r in conn.execute("PRAGMA table_info(layer_group_assignments)").fetchall()
        }

        # Fresh installs already have the new schema via CREATE IF NOT EXISTS.
        # Legacy installs may lack owner_user_id or still use group_id FK column.
        if "owner_user_id" not in group_cols:
            conn.execute(
                "ALTER TABLE layer_groups ADD COLUMN owner_user_id INTEGER NOT NULL DEFAULT 0"
            )
            # Rebuild to replace UNIQUE(group_id) with UNIQUE(owner_user_id, group_id).
            conn.execute(
                """
                CREATE TABLE layer_groups__new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    icon TEXT,
                    accent_color TEXT,
                    chip_tone TEXT,
                    sub_categories TEXT NOT NULL DEFAULT '[]',
                    position REAL NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'custom',
                    owner_user_id INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(owner_user_id, group_id)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO layer_groups__new
                    (id, group_id, name, icon, accent_color, chip_tone,
                     sub_categories, position, source, owner_user_id,
                     created_at, updated_at)
                SELECT id, group_id, name, icon, accent_color, chip_tone,
                       sub_categories, position, source, 0, created_at, updated_at
                FROM layer_groups
                """
            )
            conn.execute("DROP TABLE layer_groups")
            conn.execute("ALTER TABLE layer_groups__new RENAME TO layer_groups")

        if "owner_user_id" not in assign_cols or "group_row_id" not in assign_cols:
            # Rebuild assignments: legacy used group_id INTEGER FK → layer_groups.id
            conn.execute(
                """
                CREATE TABLE layer_group_assignments__new (
                    owner_user_id INTEGER NOT NULL DEFAULT 0,
                    layer_id TEXT NOT NULL,
                    group_row_id INTEGER NOT NULL REFERENCES layer_groups(id) ON DELETE CASCADE,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (owner_user_id, layer_id)
                )
                """
            )
            if "group_id" in assign_cols:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO layer_group_assignments__new
                        (owner_user_id, layer_id, group_row_id, updated_at)
                    SELECT 0, layer_id, group_id, updated_at
                    FROM layer_group_assignments
                    """
                )
            elif "group_row_id" in assign_cols:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO layer_group_assignments__new
                        (owner_user_id, layer_id, group_row_id, updated_at)
                    SELECT COALESCE(owner_user_id, 0), layer_id, group_row_id, updated_at
                    FROM layer_group_assignments
                    """
                )
            conn.execute("DROP TABLE layer_group_assignments")
            conn.execute(
                "ALTER TABLE layer_group_assignments__new RENAME TO layer_group_assignments"
            )

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
                         sub_categories, position, source, owner_user_id,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'seed', 0, ?, ?)
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
        owner = row["owner_user_id"] if "owner_user_id" in row.keys() else OWNER_SHARED
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
            owner_user_id=int(owner or OWNER_SHARED),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _select_sql(self) -> str:
        return (
            "SELECT id, group_id, name, icon, accent_color, chip_tone, "
            "sub_categories, position, source, owner_user_id, created_at, updated_at "
            "FROM layer_groups"
        )

    def list_groups(
        self, owner_user_id: int = OWNER_SHARED
    ) -> list[LayerGroupRecord]:
        """Seed ⊕ personal overrides/customs for *owner_user_id*.

        ``owner_user_id=0`` returns shared seeds + legacy shared customs only.
        """
        self._ensure_schema()
        self._ensure_seed_groups()
        with self._pool.connection() as conn:
            seed_rows = conn.execute(
                self._select_sql()
                + " WHERE owner_user_id=0 AND source=? ORDER BY position, id",
                (_GROUP_SOURCE_SEED,),
            ).fetchall()
            personal_rows = []
            legacy_custom = []
            if owner_user_id and owner_user_id != OWNER_SHARED:
                personal_rows = conn.execute(
                    self._select_sql()
                    + " WHERE owner_user_id=? ORDER BY position, id",
                    (int(owner_user_id),),
                ).fetchall()
            else:
                legacy_custom = conn.execute(
                    self._select_sql()
                    + " WHERE owner_user_id=0 AND source=? ORDER BY position, id",
                    (_GROUP_SOURCE_CUSTOM,),
                ).fetchall()

        seeds = [self._row_to_record(r) for r in seed_rows]
        personal = [self._row_to_record(r) for r in personal_rows]
        overrides = {
            r.group_id: r
            for r in personal
            if r.source in (_GROUP_SOURCE_OVERRIDE, _GROUP_SOURCE_SEED)
        }
        customs = [r for r in personal if r.source == _GROUP_SOURCE_CUSTOM]
        legacy = [self._row_to_record(r) for r in legacy_custom]

        merged: list[LayerGroupRecord] = []
        for seed in seeds:
            merged.append(overrides.get(seed.group_id, seed))
        merged.extend(customs)
        merged.extend(legacy)
        merged.sort(key=lambda g: (g.position, g.id))
        return merged

    def get_by_group_id(
        self, group_id: str, *, owner_user_id: int = OWNER_SHARED
    ) -> LayerGroupRecord | None:
        self._ensure_schema()
        self._ensure_seed_groups()
        gid = group_id.strip()
        with self._pool.connection() as conn:
            if owner_user_id and owner_user_id != OWNER_SHARED:
                row = conn.execute(
                    self._select_sql()
                    + " WHERE owner_user_id=? AND group_id=?",
                    (int(owner_user_id), gid),
                ).fetchone()
                if row is not None:
                    return self._row_to_record(row)
            row = conn.execute(
                self._select_sql() + " WHERE owner_user_id=0 AND group_id=?",
                (gid,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def list_assignments(self, owner_user_id: int = OWNER_SHARED) -> dict[str, str]:
        """Return {layer_id: group_id} for the given owner workspace.

        Shared (``owner=0``) is the baseline. Once an admin has any personal
        group/assignment rows, their assignment map is **personal-only** (no
        silent merge with shared leftovers), so member edits fully replace
        membership for that workspace.
        """
        self._ensure_schema()
        owner = int(owner_user_id or OWNER_SHARED)
        cached = self._assignment_cache.get(owner)
        if cached is not None:
            return dict(cached)

        with self._pool.connection() as conn:
            if owner == OWNER_SHARED or not self._has_personal_rows(conn, owner):
                rows = conn.execute(
                    "SELECT a.layer_id, g.group_id FROM layer_group_assignments a "
                    "JOIN layer_groups g ON g.id = a.group_row_id "
                    "WHERE a.owner_user_id=0"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT a.layer_id, g.group_id FROM layer_group_assignments a "
                    "JOIN layer_groups g ON g.id = a.group_row_id "
                    "WHERE a.owner_user_id=?",
                    (owner,),
                ).fetchall()
        mapping = {str(r["layer_id"]): str(r["group_id"]) for r in rows}
        self._assignment_cache[owner] = mapping
        return dict(mapping)

    @staticmethod
    def _has_personal_rows(conn: Any, owner_user_id: int) -> bool:
        row = conn.execute(
            "SELECT 1 FROM layer_groups WHERE owner_user_id=? LIMIT 1",
            (int(owner_user_id),),
        ).fetchone()
        if row is not None:
            return True
        row = conn.execute(
            "SELECT 1 FROM layer_group_assignments WHERE owner_user_id=? LIMIT 1",
            (int(owner_user_id),),
        ).fetchone()
        return row is not None

    def _ensure_personal_workspace(self, owner_user_id: int) -> None:
        """Clone shared assignments into a personal workspace on first touch.

        Ensures subsequent member edits replace membership instead of merging
        with leftover shared (owner=0) assignment rows.
        """
        owner = int(owner_user_id or OWNER_SHARED)
        if owner == OWNER_SHARED:
            return
        self._ensure_schema()
        self._ensure_seed_groups()
        now = datetime.now(UTC).isoformat()
        with self._pool.connection() as conn:
            if self._has_personal_rows(conn, owner):
                return
            shared = conn.execute(
                "SELECT layer_id, group_row_id FROM layer_group_assignments "
                "WHERE owner_user_id=0"
            ).fetchall()
            for row in shared:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO layer_group_assignments
                        (owner_user_id, layer_id, group_row_id, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (owner, str(row["layer_id"]), int(row["group_row_id"]), now),
                )
            conn.commit()
        self.invalidate_cache()

    def list_groups_for_scope(self, scope: CatalogGroupScope) -> list[LayerGroupRecord]:
        if scope.kind == "theme" and scope.theme_id is not None:
            preset = self.get_theme_preset(scope.theme_id)
            if preset is not None:
                return self._records_from_preset(preset)
        owner = scope.owner_user_id if scope.kind == "personal" else OWNER_SHARED
        return self.list_groups(owner_user_id=owner)

    def list_assignments_for_scope(self, scope: CatalogGroupScope) -> dict[str, str]:
        if scope.kind == "theme" and scope.theme_id is not None:
            preset = self.get_theme_preset(scope.theme_id)
            if preset is not None:
                raw = preset.get("assignments") or {}
                return {str(k): str(v) for k, v in raw.items() if str(k) and str(v)}
        owner = scope.owner_user_id if scope.kind == "personal" else OWNER_SHARED
        return self.list_assignments(owner_user_id=owner)

    def _records_from_preset(self, preset: dict[str, Any]) -> list[LayerGroupRecord]:
        now = datetime.now(UTC).isoformat()
        records: list[LayerGroupRecord] = []
        for index, raw in enumerate(preset.get("groups") or []):
            if not isinstance(raw, dict):
                continue
            gid = str(raw.get("id") or "").strip()
            if not gid:
                continue
            is_custom = bool(raw.get("is_custom"))
            records.append(
                LayerGroupRecord(
                    id=-(index + 1),
                    group_id=gid,
                    name=str(raw.get("name") or gid),
                    icon=raw.get("icon"),
                    accent_color=raw.get("accent_color"),
                    chip_tone=raw.get("chip_tone"),
                    sub_categories=[
                        str(s)
                        for s in (raw.get("sub_categories") or [])
                        if str(s).strip()
                    ],
                    position=float(
                        raw.get("position")
                        if raw.get("position") is not None
                        else float(index) * 10.0
                    ),
                    source=_GROUP_SOURCE_CUSTOM if is_custom else _GROUP_SOURCE_SEED,
                    owner_user_id=OWNER_SHARED,
                    created_at=now,
                    updated_at=now,
                )
            )
        records.sort(key=lambda g: (g.position, g.group_id))
        return records

    # ------------------------------------------------------------------
    # Theme presets
    # ------------------------------------------------------------------

    def export_workspace(self, owner_user_id: int) -> dict[str, Any]:
        groups = self.list_groups(owner_user_id=owner_user_id)
        assignments = self.list_assignments(owner_user_id=owner_user_id)
        return {
            "groups": [g.to_category_def_dict() for g in groups],
            "assignments": assignments,
        }

    def get_theme_preset(self, theme_id: int) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT payload FROM theme_layer_group_presets WHERE theme_id=?",
                (int(theme_id),),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload"]))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def theme_preset_meta(self, theme_id: int) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT theme_id, updated_at, updated_by_user_id FROM "
                "theme_layer_group_presets WHERE theme_id=?",
                (int(theme_id),),
            ).fetchone()
        if row is None:
            return None
        return {
            "theme_id": int(row["theme_id"]),
            "updated_at": str(row["updated_at"]),
            "updated_by_user_id": (
                int(row["updated_by_user_id"])
                if row["updated_by_user_id"] is not None
                else None
            ),
            "has_preset": True,
        }

    def save_theme_preset(
        self,
        theme_id: int,
        payload: dict[str, Any],
        *,
        updated_by_user_id: int | None = None,
    ) -> dict[str, Any]:
        self._ensure_schema()
        if not isinstance(payload.get("groups"), list):
            raise LayerGroupError("主题预设缺少 groups 列表")
        if not isinstance(payload.get("assignments"), dict):
            raise LayerGroupError("主题预设缺少 assignments 映射")
        now = datetime.now(UTC).isoformat()
        blob = json.dumps(payload, ensure_ascii=False)
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO theme_layer_group_presets
                    (theme_id, payload, updated_at, updated_by_user_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(theme_id) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at,
                    updated_by_user_id=excluded.updated_by_user_id
                """,
                (int(theme_id), blob, now, updated_by_user_id),
            )
            conn.commit()
        self.invalidate_cache()
        return {
            "theme_id": int(theme_id),
            "updated_at": now,
            "updated_by_user_id": updated_by_user_id,
            "has_preset": True,
        }

    def delete_theme_preset(self, theme_id: int) -> bool:
        self._ensure_schema()
        with self._pool.connection() as conn:
            cur = conn.execute(
                "DELETE FROM theme_layer_group_presets WHERE theme_id=?",
                (int(theme_id),),
            )
            conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            self.invalidate_cache()
        return deleted

    def sync_workspace_to_theme(
        self, owner_user_id: int, theme_id: int
    ) -> dict[str, Any]:
        payload = self.export_workspace(owner_user_id)
        return self.save_theme_preset(
            theme_id, payload, updated_by_user_id=owner_user_id
        )

    # ------------------------------------------------------------------
    # Writes (always personal when owner_user_id != 0)
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
        owner_user_id: int = OWNER_SHARED,
    ) -> LayerGroupRecord:
        self._ensure_schema()
        self._ensure_seed_groups()
        gid = self._validate_group_id(group_id)
        name = name.strip()
        if not name:
            raise LayerGroupError("分组名称不能为空")
        owner = int(owner_user_id or OWNER_SHARED)
        # Collision with shared seed id is forbidden even for personal customs.
        if owner != OWNER_SHARED:
            self._ensure_personal_workspace(owner)
        if self.get_by_group_id(gid, owner_user_id=OWNER_SHARED) is not None:
            shared = self.get_by_group_id(gid, owner_user_id=OWNER_SHARED)
            if shared and shared.source == _GROUP_SOURCE_SEED:
                raise LayerGroupError(f"分组 id 与种子冲突: {gid}")
        if self.get_by_group_id(gid, owner_user_id=owner) is not None:
            raise LayerGroupError(f"分组 id 已存在: {gid}")
        now = datetime.now(UTC).isoformat()
        with self._pool.connection() as conn:
            max_pos = conn.execute(
                "SELECT COALESCE(MAX(position), 0) AS m FROM layer_groups "
                "WHERE owner_user_id IN (0, ?)",
                (owner,),
            ).fetchone()
            position = float(max_pos["m"]) + 10.0
            conn.execute(
                """
                INSERT INTO layer_groups
                    (group_id, name, icon, accent_color, chip_tone,
                     sub_categories, position, source, owner_user_id,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'custom', ?, ?, ?)
                """,
                (
                    gid,
                    name,
                    icon,
                    accent_color,
                    chip_tone,
                    json.dumps(sub_categories or [], ensure_ascii=False),
                    position,
                    owner,
                    now,
                    now,
                ),
            )
            conn.commit()
        record = self.get_by_group_id(gid, owner_user_id=owner)
        assert record is not None
        return record

    def update_group(
        self,
        group_id: str,
        *,
        name: str | None = None,
        icon: str | None = None,
        accent_color: str | None = None,
        chip_tone: str | None = None,
        sub_categories: list[str] | None = None,
        owner_user_id: int = OWNER_SHARED,
    ) -> LayerGroupRecord:
        owner = int(owner_user_id or OWNER_SHARED)
        if owner != OWNER_SHARED:
            self._ensure_personal_workspace(owner)
        record = self.get_by_group_id(group_id, owner_user_id=owner)
        if record is None:
            raise LayerGroupError(f"分组不存在: {group_id}")

        # Seed edits for a personal owner become / update an override row.
        if (
            owner != OWNER_SHARED
            and record.owner_user_id == OWNER_SHARED
            and record.source == _GROUP_SOURCE_SEED
        ):
            return self._upsert_seed_override(
                record,
                owner_user_id=owner,
                name=name,
                icon=icon,
                accent_color=accent_color,
                chip_tone=chip_tone,
                sub_categories=sub_categories,
            )

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
        updated = self.get_by_group_id(record.group_id, owner_user_id=owner)
        assert updated is not None
        return updated

    def _upsert_seed_override(
        self,
        seed: LayerGroupRecord,
        *,
        owner_user_id: int,
        name: str | None = None,
        icon: str | None = None,
        accent_color: str | None = None,
        chip_tone: str | None = None,
        sub_categories: list[str] | None = None,
        position: float | None = None,
    ) -> LayerGroupRecord:
        now = datetime.now(UTC).isoformat()
        new_name = (name.strip() if name is not None else seed.name) or seed.name
        if name is not None and not name.strip():
            raise LayerGroupError("分组名称不能为空")
        new_icon = icon if icon is not None else seed.icon
        new_accent = accent_color if accent_color is not None else seed.accent_color
        new_chip = chip_tone if chip_tone is not None else seed.chip_tone
        new_subs = (
            sub_categories if sub_categories is not None else list(seed.sub_categories)
        )
        new_pos = float(position) if position is not None else seed.position
        with self._pool.connection() as conn:
            existing = conn.execute(
                "SELECT id FROM layer_groups WHERE owner_user_id=? AND group_id=?",
                (int(owner_user_id), seed.group_id),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO layer_groups
                        (group_id, name, icon, accent_color, chip_tone,
                         sub_categories, position, source, owner_user_id,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'override', ?, ?, ?)
                    """,
                    (
                        seed.group_id,
                        new_name,
                        new_icon,
                        new_accent,
                        new_chip,
                        json.dumps(new_subs, ensure_ascii=False),
                        new_pos,
                        int(owner_user_id),
                        now,
                        now,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE layer_groups SET
                        name=?, icon=?, accent_color=?, chip_tone=?,
                        sub_categories=?, position=?, source='override',
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        new_name,
                        new_icon,
                        new_accent,
                        new_chip,
                        json.dumps(new_subs, ensure_ascii=False),
                        new_pos,
                        now,
                        int(existing["id"]),
                    ),
                )
            conn.commit()
        updated = self.get_by_group_id(seed.group_id, owner_user_id=owner_user_id)
        assert updated is not None
        return updated

    def delete_group(
        self, group_id: str, *, owner_user_id: int = OWNER_SHARED
    ) -> None:
        owner = int(owner_user_id or OWNER_SHARED)
        # Seed ids are never deletable (even when a personal override exists).
        shared = self.get_by_group_id(group_id, owner_user_id=OWNER_SHARED)
        if shared is not None and shared.source == _GROUP_SOURCE_SEED:
            raise LayerGroupError("种子分组不可删除（来自 layer_categories.json）")
        if owner != OWNER_SHARED:
            self._ensure_personal_workspace(owner)

        record = self.get_by_group_id(group_id, owner_user_id=owner)
        if record is None:
            raise LayerGroupError(f"分组不存在: {group_id}")
        if record.source == _GROUP_SOURCE_OVERRIDE:
            with self._pool.connection() as conn:
                conn.execute("DELETE FROM layer_groups WHERE id=?", (record.id,))
                conn.commit()
            self.invalidate_cache()
            return
        if record.source != _GROUP_SOURCE_CUSTOM:
            raise LayerGroupError("种子分组不可删除（来自 layer_categories.json）")
        if record.owner_user_id != owner and owner != OWNER_SHARED:
            raise LayerGroupError("只能删除自己工作区中的自建分组")
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM layer_group_assignments WHERE group_row_id=?",
                (record.id,),
            )
            conn.execute("DELETE FROM layer_groups WHERE id=?", (record.id,))
            conn.commit()
        self.invalidate_cache()

    def reorder_groups(
        self,
        ordered_group_ids: list[str],
        *,
        owner_user_id: int = OWNER_SHARED,
    ) -> list[LayerGroupRecord]:
        """Rewrite positions to match the given id order."""
        self._ensure_schema()
        self._ensure_seed_groups()
        owner = int(owner_user_id or OWNER_SHARED)
        if owner != OWNER_SHARED:
            self._ensure_personal_workspace(owner)
        known = {g.group_id: g for g in self.list_groups(owner_user_id=owner)}
        unknown = [gid for gid in ordered_group_ids if gid not in known]
        if unknown:
            raise LayerGroupError(f"未知分组 id: {', '.join(unknown)}")
        tail = [
            g.group_id for g in known.values() if g.group_id not in set(ordered_group_ids)
        ]
        full_order = list(ordered_group_ids) + tail
        now = datetime.now(UTC).isoformat()

        if owner == OWNER_SHARED:
            with self._pool.connection() as conn:
                for index, gid in enumerate(full_order):
                    conn.execute(
                        "UPDATE layer_groups SET position=?, updated_at=? "
                        "WHERE owner_user_id=0 AND group_id=?",
                        (float(index) * 10.0, now, gid),
                    )
                conn.commit()
            return self.list_groups(owner_user_id=OWNER_SHARED)

        for index, gid in enumerate(full_order):
            record = known[gid]
            pos = float(index) * 10.0
            if (
                record.owner_user_id == OWNER_SHARED
                and record.source == _GROUP_SOURCE_SEED
            ):
                self._upsert_seed_override(
                    record, owner_user_id=owner, position=pos
                )
            else:
                with self._pool.connection() as conn:
                    conn.execute(
                        "UPDATE layer_groups SET position=?, updated_at=? WHERE id=?",
                        (pos, now, record.id),
                    )
                    conn.commit()
        return self.list_groups(owner_user_id=owner)

    def set_layer_assignments(
        self,
        group_id: str,
        layer_ids: list[str],
        *,
        owner_user_id: int = OWNER_SHARED,
    ) -> dict[str, str]:
        """Replace membership of *group_id* with *layer_ids* for this owner."""
        owner = int(owner_user_id or OWNER_SHARED)
        if owner != OWNER_SHARED:
            self._ensure_personal_workspace(owner)
        record = self.get_by_group_id(group_id, owner_user_id=owner)
        if record is None:
            raise LayerGroupError(f"分组不存在: {group_id}")
        # Prefer personal row id when assigning under a personal workspace so
        # FK targets the owner's override/custom row when present.
        target_row_id = record.id
        if owner != OWNER_SHARED and record.owner_user_id == OWNER_SHARED:
            # Assignments may point at the shared seed row id; that's fine.
            target_row_id = record.id

        cleaned: list[str] = []
        for lid in layer_ids:
            lid = str(lid).strip()
            if lid and lid not in cleaned:
                cleaned.append(lid)
        now = datetime.now(UTC).isoformat()
        with self._pool.connection() as conn:
            # Drop personal (or shared) memberships currently pointing at this
            # logical group_id for this owner.
            conn.execute(
                """
                DELETE FROM layer_group_assignments
                WHERE owner_user_id=? AND group_row_id IN (
                    SELECT id FROM layer_groups WHERE group_id=?
                )
                """,
                (owner, group_id),
            )
            for lid in cleaned:
                conn.execute(
                    """
                    INSERT INTO layer_group_assignments
                        (owner_user_id, layer_id, group_row_id, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(owner_user_id, layer_id) DO UPDATE SET
                        group_row_id=excluded.group_row_id,
                        updated_at=excluded.updated_at
                    """,
                    (owner, lid, target_row_id, now),
                )
            conn.commit()
        self.invalidate_cache()
        return self.list_assignments(owner_user_id=owner)

    # ------------------------------------------------------------------
    # Resolution (assignment override → descriptor category fallback)
    # ------------------------------------------------------------------

    def resolve_group_id_for_layer(
        self,
        layer_id: str,
        descriptor_category: str | None,
        *,
        owner_user_id: int = OWNER_SHARED,
        scope: CatalogGroupScope | None = None,
    ) -> str | None:
        """Group id for ACL / catalog: assignment override wins, else descriptor."""
        if scope is not None:
            assignments = self.list_assignments_for_scope(scope)
        else:
            assignments = self.list_assignments(owner_user_id=owner_user_id)
        override = assignments.get(layer_id)
        if override is not None:
            return override
        return descriptor_category

    def invalidate_cache(self) -> None:
        self._assignment_cache.clear()
        from app.services.permission_repository import invalidate_access_cache

        invalidate_access_cache(None)

    def close(self) -> None:
        self._pool.close_all()


def resolve_catalog_group_scope(
    *,
    user_id: int | None,
    role: str | None,
    theme_id: int | None = None,
) -> CatalogGroupScope:
    """Pick personal / theme / shared scope for catalog reads."""
    if role == "admin" and user_id is not None:
        return CatalogGroupScope.personal(int(user_id))
    tid = theme_id
    if tid is None and user_id is not None:
        try:
            from app.services.permission_repository import get_permission_repository

            tid = get_permission_repository()._user_theme_id(int(user_id))
        except Exception:
            tid = None
    if tid is not None:
        repo = get_layer_group_repository()
        if repo.get_theme_preset(int(tid)) is not None:
            return CatalogGroupScope.theme(int(tid))
    return CatalogGroupScope.shared()


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
