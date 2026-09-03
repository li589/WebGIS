"""Product themes: branding + default resource ACL (SQLite, users.sqlite3)."""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services._sqlite_pool import SQLiteConnectionPool
from app.services.permission_repository import (
    PermissionInput,
    _VALID_MODES,
    _VALID_PERMISSIONS,
    _VALID_RESOURCE_TYPES,
)
from app.services.user_repository import _users_db_path

logger = logging.getLogger(__name__)

SGFS_SLUG = "sgfs"
SGFS_NAME_ZH = "星地融合土壤数据平台"
SGFS_FULL_NAME_ZH = "星地融合土壤水分监测与干旱预警数据分析与可视化系统"
SGFS_NAME_EN = "Satellite-Ground Fusion Soil Data Platform"
SGFS_ABBR = "SGFS"
SGFS_DESCRIPTION = (
    "面向课题组与大气研究院的星地融合土壤水分监测与干旱预警数据分析与可视化平台。"
)

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_LOGO_MAX_BYTES = 2 * 1024 * 1024
_LOGO_ALLOWED_EXT = frozenset({".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"})

# 登录页氛围色方案（仅影响 LoginView，不改应用内主题）
VALID_LOGIN_PALETTES = frozenset({"cyan", "green", "warm", "violet", "slate"})
DEFAULT_LOGIN_PALETTE = "cyan"


def normalize_login_palette(value: str | None) -> str:
    key = (value or "").strip().lower()
    if key in VALID_LOGIN_PALETTES:
        return key
    return DEFAULT_LOGIN_PALETTE


def infer_login_palette(*, slug: str, name_zh: str, full_name_zh: str = "") -> str:
    """按品牌文案推断默认登录配色（迁移/新建兜底）。"""
    blob = f"{slug} {name_zh} {full_name_zh}".lower()
    if any(tok in blob for tok in ("植被", "生态", "vegetation", "ecology", "vemp", "ndvi")):
        return "green"
    if any(tok in blob for tok in ("warm", "soil", "干旱", "土壤")):
        return "warm"
    if "sgfs" in blob or "星地" in blob:
        return "cyan"
    return DEFAULT_LOGIN_PALETTE


@dataclass(frozen=True)
class ThemeRecord:
    id: int
    slug: str
    name_zh: str
    full_name_zh: str
    name_en: str
    abbr: str
    description: str
    logo_path: str | None
    default_permission_mode: str
    is_primary: bool
    login_palette: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ThemeResourcePermission:
    id: int
    theme_id: int
    resource_type: str
    resource_id: str
    permission: str
    created_at: str
    updated_at: str


def _theme_assets_root() -> Path:
    root = Path(settings.workflow_state_dir) / "theme-assets"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _row_to_theme(row: Any) -> ThemeRecord:
    keys = row.keys() if hasattr(row, "keys") else ()
    login_palette = (
        str(row["login_palette"])
        if "login_palette" in keys and row["login_palette"]
        else DEFAULT_LOGIN_PALETTE
    )
    return ThemeRecord(
        id=int(row["id"]),
        slug=str(row["slug"]),
        name_zh=str(row["name_zh"]),
        full_name_zh=str(row["full_name_zh"]),
        name_en=str(row["name_en"]),
        abbr=str(row["abbr"]),
        description=str(row["description"] or ""),
        logo_path=str(row["logo_path"]) if row["logo_path"] else None,
        default_permission_mode=str(row["default_permission_mode"] or "open"),
        is_primary=bool(row["is_primary"]),
        login_palette=normalize_login_palette(login_palette),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class ThemeRepository:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or _users_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool = SQLiteConnectionPool(self.db_path)
        self._init_schema()
        self.ensure_primary_theme()

    def _init_schema(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS themes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    name_zh TEXT NOT NULL,
                    full_name_zh TEXT NOT NULL,
                    name_en TEXT NOT NULL,
                    abbr TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    logo_path TEXT,
                    default_permission_mode TEXT NOT NULL DEFAULT 'open',
                    is_primary INTEGER NOT NULL DEFAULT 0,
                    login_palette TEXT NOT NULL DEFAULT 'cyan',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # Additive migration for existing DBs
            login_palette_added = False
            try:
                conn.execute(
                    "ALTER TABLE themes ADD COLUMN login_palette TEXT NOT NULL DEFAULT 'cyan'"
                )
                login_palette_added = True
            except Exception:
                pass
            # Only auto-infer when column is newly added (avoid clobbering admin choices)
            if login_palette_added:
                rows = conn.execute(
                    "SELECT id, slug, name_zh, full_name_zh FROM themes"
                ).fetchall()
                for row in rows:
                    inferred = infer_login_palette(
                        slug=str(row["slug"]),
                        name_zh=str(row["name_zh"]),
                        full_name_zh=str(row["full_name_zh"] or ""),
                    )
                    if inferred != DEFAULT_LOGIN_PALETTE:
                        conn.execute(
                            "UPDATE themes SET login_palette=? WHERE id=?",
                            (inferred, int(row["id"])),
                        )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS theme_resource_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    theme_id INTEGER NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(theme_id, resource_type, resource_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_theme_perms_theme "
                "ON theme_resource_permissions(theme_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_theme_perms_theme_type "
                "ON theme_resource_permissions(theme_id, resource_type)"
            )
            # users.theme_id — additive migration
            try:
                conn.execute("ALTER TABLE users ADD COLUMN theme_id INTEGER")
            except Exception:
                pass

            # 一次性：按品牌文案把仍为默认 cyan 的主题推断为 green/warm 等
            # （仅跑一次，之后管理员在主题设置中的选择不受影响）
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS theme_schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            infer_done = conn.execute(
                "SELECT 1 FROM theme_schema_meta WHERE key='login_palette_infer_v1'"
            ).fetchone()
            if infer_done is None:
                rows = conn.execute(
                    "SELECT id, slug, name_zh, full_name_zh, login_palette FROM themes"
                ).fetchall()
                for row in rows:
                    current = normalize_login_palette(
                        str(row["login_palette"]) if row["login_palette"] else None
                    )
                    if current != DEFAULT_LOGIN_PALETTE:
                        continue
                    inferred = infer_login_palette(
                        slug=str(row["slug"]),
                        name_zh=str(row["name_zh"]),
                        full_name_zh=str(row["full_name_zh"] or ""),
                    )
                    if inferred != DEFAULT_LOGIN_PALETTE:
                        conn.execute(
                            "UPDATE themes SET login_palette=? WHERE id=?",
                            (inferred, int(row["id"])),
                        )
                conn.execute(
                    "INSERT OR REPLACE INTO theme_schema_meta(key, value) VALUES (?, ?)",
                    ("login_palette_infer_v1", "1"),
                )

            conn.commit()

    def close(self) -> None:
        self._pool.close_all()

    def ensure_primary_theme(self) -> ThemeRecord:
        """Seed SGFS primary theme and backfill users.theme_id."""
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM themes WHERE is_primary=1 LIMIT 1"
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM themes WHERE slug=? COLLATE NOCASE", (SGFS_SLUG,)
                ).fetchone()
            now = datetime.now(UTC).isoformat()
            if row is None:
                cur = conn.execute(
                    """
                    INSERT INTO themes (
                        slug, name_zh, full_name_zh, name_en, abbr, description,
                        logo_path, default_permission_mode, is_primary, login_palette,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, 'open', 1, ?, ?, ?)
                    """,
                    (
                        SGFS_SLUG,
                        SGFS_NAME_ZH,
                        SGFS_FULL_NAME_ZH,
                        SGFS_NAME_EN,
                        SGFS_ABBR,
                        SGFS_DESCRIPTION,
                        DEFAULT_LOGIN_PALETTE,
                        now,
                        now,
                    ),
                )
                theme_id = int(cur.lastrowid)
            else:
                theme_id = int(row["id"])
                # Keep primary branding in sync with product rename for the seed slug.
                if str(row["slug"]).lower() == SGFS_SLUG:
                    conn.execute(
                        """
                        UPDATE themes SET
                            name_zh=?, full_name_zh=?, name_en=?, abbr=?,
                            is_primary=1, updated_at=?
                        WHERE id=?
                        """,
                        (
                            SGFS_NAME_ZH,
                            SGFS_FULL_NAME_ZH,
                            SGFS_NAME_EN,
                            SGFS_ABBR,
                            now,
                            theme_id,
                        ),
                    )
                else:
                    conn.execute(
                        "UPDATE themes SET is_primary=1, updated_at=? WHERE id=?",
                        (now, theme_id),
                    )
                conn.execute(
                    "UPDATE themes SET is_primary=0, updated_at=? WHERE id!=?",
                    (now, theme_id),
                )

            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users' LIMIT 1"
            ).fetchone():
                # Mandatory binding: null or orphaned theme_id → primary (sgfs).
                conn.execute(
                    """
                    UPDATE users SET theme_id=?
                    WHERE theme_id IS NULL
                       OR theme_id NOT IN (SELECT id FROM themes)
                    """,
                    (theme_id,),
                )
            conn.commit()

        theme = self.get_by_id(theme_id)
        assert theme is not None
        return theme

    def list_themes(self) -> list[ThemeRecord]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM themes ORDER BY is_primary DESC, id ASC"
            ).fetchall()
        return [_row_to_theme(r) for r in rows]

    def get_by_id(self, theme_id: int) -> ThemeRecord | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM themes WHERE id=?", (theme_id,)
            ).fetchone()
        return _row_to_theme(row) if row else None

    def get_by_slug(self, slug: str) -> ThemeRecord | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM themes WHERE slug=? COLLATE NOCASE",
                (slug.strip(),),
            ).fetchone()
        return _row_to_theme(row) if row else None

    def get_primary(self) -> ThemeRecord:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM themes WHERE is_primary=1 LIMIT 1"
            ).fetchone()
        if row:
            return _row_to_theme(row)
        return self.ensure_primary_theme()

    def create_theme(
        self,
        *,
        slug: str,
        name_zh: str,
        full_name_zh: str,
        name_en: str,
        abbr: str,
        description: str = "",
        default_permission_mode: str = "open",
        is_primary: bool = False,
        login_palette: str | None = None,
    ) -> ThemeRecord:
        slug_n = slug.strip().lower()
        if not _SLUG_RE.match(slug_n):
            raise ValueError(
                "slug must be 2-64 chars: lowercase letter, then [a-z0-9_-]"
            )
        if default_permission_mode not in _VALID_MODES:
            raise ValueError(
                f"invalid default_permission_mode: {default_permission_mode}"
            )
        palette = (
            normalize_login_palette(login_palette)
            if login_palette is not None and str(login_palette).strip()
            else infer_login_palette(
                slug=slug_n, name_zh=name_zh, full_name_zh=full_name_zh
            )
        )
        now = datetime.now(UTC).isoformat()
        with self._pool.connection() as conn:
            if is_primary:
                conn.execute("UPDATE themes SET is_primary=0, updated_at=?", (now,))
            try:
                cur = conn.execute(
                    """
                    INSERT INTO themes (
                        slug, name_zh, full_name_zh, name_en, abbr, description,
                        logo_path, default_permission_mode, is_primary, login_palette,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
                    """,
                    (
                        slug_n,
                        name_zh.strip(),
                        full_name_zh.strip(),
                        name_en.strip(),
                        abbr.strip() or SGFS_ABBR,
                        description.strip(),
                        default_permission_mode,
                        1 if is_primary else 0,
                        palette,
                        now,
                        now,
                    ),
                )
            except Exception as exc:
                raise ValueError("theme slug already exists") from exc
            theme_id = int(cur.lastrowid)
            conn.commit()
        theme = self.get_by_id(theme_id)
        assert theme is not None
        return theme

    def update_theme(
        self,
        theme_id: int,
        *,
        name_zh: str | None = None,
        full_name_zh: str | None = None,
        name_en: str | None = None,
        abbr: str | None = None,
        description: str | None = None,
        default_permission_mode: str | None = None,
        is_primary: bool | None = None,
        login_palette: str | None = None,
    ) -> ThemeRecord | None:
        theme = self.get_by_id(theme_id)
        if theme is None:
            return None
        if (
            default_permission_mode is not None
            and default_permission_mode not in _VALID_MODES
        ):
            raise ValueError(
                f"invalid default_permission_mode: {default_permission_mode}"
            )
        if login_palette is not None and str(login_palette).strip():
            if normalize_login_palette(login_palette) not in VALID_LOGIN_PALETTES:
                raise ValueError(f"invalid login_palette: {login_palette}")
        now = datetime.now(UTC).isoformat()
        fields: list[str] = ["updated_at=?"]
        params: list[Any] = [now]
        if name_zh is not None:
            fields.append("name_zh=?")
            params.append(name_zh.strip())
        if full_name_zh is not None:
            fields.append("full_name_zh=?")
            params.append(full_name_zh.strip())
        if name_en is not None:
            fields.append("name_en=?")
            params.append(name_en.strip())
        if abbr is not None:
            fields.append("abbr=?")
            params.append(abbr.strip())
        if description is not None:
            fields.append("description=?")
            params.append(description.strip())
        if default_permission_mode is not None:
            fields.append("default_permission_mode=?")
            params.append(default_permission_mode)
        if login_palette is not None:
            fields.append("login_palette=?")
            params.append(normalize_login_palette(login_palette))
        with self._pool.connection() as conn:
            if is_primary is True:
                conn.execute(
                    "UPDATE themes SET is_primary=0, updated_at=? WHERE id!=?",
                    (now, theme_id),
                )
                fields.append("is_primary=?")
                params.append(1)
            elif is_primary is False and theme.is_primary:
                raise ValueError("cannot unset primary without promoting another theme")
            params.append(theme_id)
            conn.execute(
                f"UPDATE themes SET {', '.join(fields)} WHERE id=?",
                params,
            )
            conn.commit()
        from app.services.permission_repository import invalidate_access_cache

        invalidate_access_cache()
        return self.get_by_id(theme_id)

    def delete_theme(self, theme_id: int) -> bool:
        theme = self.get_by_id(theme_id)
        if theme is None:
            return False
        if theme.is_primary:
            raise ValueError("cannot delete the primary theme")
        primary = self.get_primary()
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE users SET theme_id=? WHERE theme_id=?",
                (primary.id, theme_id),
            )
            cur = conn.execute("DELETE FROM themes WHERE id=?", (theme_id,))
            conn.commit()
        assets = _theme_assets_root() / str(theme_id)
        if assets.exists():
            shutil.rmtree(assets, ignore_errors=True)
        from app.services.permission_repository import invalidate_access_cache

        invalidate_access_cache()
        return cur.rowcount > 0

    def get_theme_permissions(self, theme_id: int) -> list[ThemeResourcePermission]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, theme_id, resource_type, resource_id, permission, "
                "created_at, updated_at "
                "FROM theme_resource_permissions WHERE theme_id=? "
                "ORDER BY resource_type, resource_id",
                (theme_id,),
            ).fetchall()
        return [
            ThemeResourcePermission(
                id=int(r["id"]),
                theme_id=int(r["theme_id"]),
                resource_type=str(r["resource_type"]),
                resource_id=str(r["resource_id"]),
                permission=str(r["permission"]),
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    def set_theme_permissions(
        self, theme_id: int, permissions: list[PermissionInput]
    ) -> list[ThemeResourcePermission]:
        if self.get_by_id(theme_id) is None:
            raise ValueError("theme not found")
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
                "DELETE FROM theme_resource_permissions WHERE theme_id=?",
                (theme_id,),
            )
            for p in permissions:
                conn.execute(
                    """
                    INSERT INTO theme_resource_permissions
                        (theme_id, resource_type, resource_id, permission, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        theme_id,
                        p.resource_type,
                        p.resource_id.strip(),
                        p.permission,
                        now,
                        now,
                    ),
                )
            conn.commit()
        from app.services.permission_repository import invalidate_access_cache

        invalidate_access_cache()
        return self.get_theme_permissions(theme_id)

    def save_logo(self, theme_id: int, *, filename: str, content: bytes) -> ThemeRecord:
        theme = self.get_by_id(theme_id)
        if theme is None:
            raise ValueError("theme not found")
        if len(content) > _LOGO_MAX_BYTES:
            raise ValueError("logo file too large (max 2 MiB)")
        ext = Path(filename).suffix.lower()
        if ext not in _LOGO_ALLOWED_EXT:
            raise ValueError(f"unsupported logo type: {ext or '(none)'}")
        dest_dir = _theme_assets_root() / str(theme_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"logo{ext}"
        dest.write_bytes(content)
        rel = str(dest)
        now = datetime.now(UTC).isoformat()
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE themes SET logo_path=?, updated_at=? WHERE id=?",
                (rel, now, theme_id),
            )
            conn.commit()
        updated = self.get_by_id(theme_id)
        assert updated is not None
        return updated

    def resolve_logo_path(self, theme_id: int) -> Path | None:
        theme = self.get_by_id(theme_id)
        if theme is None or not theme.logo_path:
            return None
        path = Path(theme.logo_path)
        if not path.is_file():
            return None
        # Path traversal guard: must live under theme-assets/{id}/
        try:
            path.resolve().relative_to((_theme_assets_root() / str(theme_id)).resolve())
        except ValueError:
            return None
        return path


_repo: ThemeRepository | None = None


def get_theme_repository() -> ThemeRepository:
    global _repo
    if _repo is None:
        _repo = ThemeRepository()
    return _repo


def reset_theme_repository_for_tests() -> None:
    global _repo
    if _repo is not None:
        _repo.close()
    _repo = None
