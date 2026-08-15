"""可用数据集注册表（运行时可编辑，落 research_data_settings.sqlite3）。

- ``source=algorithm_registry``：启动时从算法包 ``dataset_config.DATASET_REGISTRY``
  同步，UI 只读保护（禁删禁改名，允许改 path 覆盖）。
- ``source=scan``：``rescan()`` 扫描数据根一级/二级目录生成。
- ``source=manual``：用户手动添加。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from app.core import config
from app.services._sqlite_pool import SQLiteConnectionPool

logger = logging.getLogger(__name__)

VALID_SOURCES = frozenset({"manual", "scan", "algorithm_registry"})


class DatasetRegistryError(ValueError):
    """注册表操作校验失败。"""


def _db_path() -> Path:
    return (
        Path(config.settings.gee_credentials_db_path).parent
        / "research_data_settings.sqlite3"
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class DatasetRegistryRepository:
    """available_datasets 表（与 research_data_settings KV 同库，additive）。"""

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
                CREATE TABLE IF NOT EXISTS available_datasets (
                    dataset_id TEXT PRIMARY KEY,
                    logical_name TEXT NOT NULL UNIQUE,
                    path TEXT NOT NULL,
                    file_format TEXT DEFAULT '',
                    variables TEXT DEFAULT '[]',
                    time_range TEXT DEFAULT '',
                    resolution TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    description TEXT DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    file_count INTEGER,
                    last_scanned_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> dict[str, Any]:
        entry = dict(row)
        for json_key in ("variables", "tags"):
            raw = entry.get(json_key)
            try:
                parsed = json.loads(raw) if isinstance(raw, str) and raw else []
            except json.JSONDecodeError:
                parsed = []
            entry[json_key] = parsed if isinstance(parsed, list) else []
        entry["enabled"] = bool(entry.get("enabled"))
        return entry

    def list_entries(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM available_datasets"
        if not include_disabled:
            query += " WHERE enabled = 1"
        query += " ORDER BY logical_name"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_by_logical_name(self, logical_name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM available_datasets WHERE logical_name = ?",
                (str(logical_name),),
            ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def get(self, dataset_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM available_datasets WHERE dataset_id = ?",
                (str(dataset_id),),
            ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def upsert(
        self,
        *,
        dataset_id: str | None,
        logical_name: str,
        path: str,
        file_format: str = "",
        variables: list[str] | None = None,
        time_range: str = "",
        resolution: str = "",
        tags: list[str] | None = None,
        description: str = "",
        source: str = "manual",
        enabled: bool = True,
        file_count: int | None = None,
        last_scanned_at: str | None = None,
    ) -> dict[str, Any]:
        logical_name = str(logical_name or "").strip()
        path = str(path or "").strip()
        if not logical_name:
            raise DatasetRegistryError("logical_name must not be empty")
        if not path:
            raise DatasetRegistryError("path must not be empty")
        now = _now_iso()
        existing: dict[str, Any] | None = None
        if dataset_id:
            existing = self.get(dataset_id)
        if existing is None:
            conflict = self.get_by_logical_name(logical_name)
            if conflict is not None and conflict["logical_name"] == logical_name:
                if dataset_id and conflict["dataset_id"] != dataset_id:
                    raise DatasetRegistryError(
                        f"logical_name '{logical_name}' already used by dataset "
                        f"'{conflict['dataset_id']}'"
                    )
                existing = conflict

        if existing is not None:
            if existing["source"] == "algorithm_registry" and (
                logical_name != existing["logical_name"]
            ):
                raise DatasetRegistryError(
                    f"built-in dataset '{existing['logical_name']}' cannot be renamed"
                )
            merged = dict(existing)
            merged["logical_name"] = logical_name
            merged["path"] = path
            merged["time_range"] = time_range or merged.get("time_range") or ""
            merged["resolution"] = resolution or merged.get("resolution") or ""
            if file_format:
                merged["file_format"] = file_format
            if description:
                merged["description"] = description
            merged["source"] = existing["source"]
            merged["enabled"] = enabled
            if variables is not None:
                merged["variables"] = variables
            if tags is not None:
                merged["tags"] = tags
            if file_count is not None:
                merged["file_count"] = file_count
            if last_scanned_at is not None:
                merged["last_scanned_at"] = last_scanned_at
        else:
            if source not in VALID_SOURCES:
                raise DatasetRegistryError(
                    f"Invalid source: {source}; expected one of {sorted(VALID_SOURCES)}"
                )
            merged = {
                "dataset_id": self._unique_dataset_id(
                    dataset_id or self._derive_dataset_id(logical_name),
                    logical_name,
                ),
                "logical_name": logical_name,
                "path": path,
                "file_format": file_format,
                "variables": variables or [],
                "time_range": time_range,
                "resolution": resolution,
                "tags": tags or [],
                "description": description,
                "source": source,
                "enabled": enabled,
                "file_count": file_count,
                "last_scanned_at": last_scanned_at,
                "created_at": now,
            }

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO available_datasets (
                    dataset_id, logical_name, path, file_format, variables,
                    time_range, resolution, tags, description, source, enabled,
                    file_count, last_scanned_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id) DO UPDATE SET
                    logical_name = excluded.logical_name,
                    path = excluded.path,
                    file_format = excluded.file_format,
                    variables = excluded.variables,
                    time_range = excluded.time_range,
                    resolution = excluded.resolution,
                    tags = excluded.tags,
                    description = excluded.description,
                    source = excluded.source,
                    enabled = excluded.enabled,
                    file_count = excluded.file_count,
                    last_scanned_at = excluded.last_scanned_at,
                    updated_at = excluded.updated_at
                """,
                (
                    merged["dataset_id"],
                    merged["logical_name"],
                    merged["path"],
                    merged.get("file_format") or "",
                    json.dumps(merged.get("variables") or [], ensure_ascii=False),
                    merged.get("time_range") or "",
                    merged.get("resolution") or "",
                    json.dumps(merged.get("tags") or [], ensure_ascii=False),
                    merged.get("description") or "",
                    merged.get("source") or "manual",
                    1 if merged.get("enabled") else 0,
                    merged.get("file_count"),
                    merged.get("last_scanned_at"),
                    merged.get("created_at") or now,
                    now,
                ),
            )
            conn.commit()
        return self.get(merged["dataset_id"]) or merged

    @staticmethod
    def _derive_dataset_id(logical_name: str) -> str:
        base = "".join(c if c.isalnum() else "-" for c in logical_name.lower())
        return base.strip("-") or f"ds-{_now_iso()}"

    def _unique_dataset_id(self, candidate: str, logical_name: str) -> str:
        """派生 id 被其它 logical_name 占用时追加序号，避免 ON CONFLICT 静默覆盖。"""
        existing = self.get(candidate)
        if existing is None or existing["logical_name"] == logical_name:
            return candidate
        suffix = 2
        while True:
            alt = f"{candidate}-{suffix}"
            existing = self.get(alt)
            if existing is None or existing["logical_name"] == logical_name:
                return alt
            suffix += 1

    def update_scan_stats(self, logical_name: str, *, file_count: int | None) -> None:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE available_datasets SET file_count = ?, last_scanned_at = ?, "
                "updated_at = ? WHERE logical_name = ?",
                (file_count, now, now, logical_name),
            )
            conn.commit()

    def delete(self, dataset_id: str) -> bool:
        entry = self.get(dataset_id)
        if entry is None:
            return False
        if entry["source"] == "algorithm_registry":
            raise DatasetRegistryError(
                f"built-in dataset '{dataset_id}' cannot be deleted "
                "(path override can be edited)"
            )
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM available_datasets WHERE dataset_id = ?", (dataset_id,)
            )
            conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._pool.close_all()


_repo_instance: DatasetRegistryRepository | None = None


def get_dataset_registry() -> DatasetRegistryRepository:
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = DatasetRegistryRepository(_db_path())
    return _repo_instance


# ── 同步与扫描 ───────────────────────────────────────────────────────────────


def sync_algorithm_datasets() -> int:
    """启动时从算法包 DATASET_REGISTRY 同步内置条目（失败仅告警）。

    只增改不删（算法包条目下线时保留 DB 条目，避免误删用户 path 覆盖）。
    已存在条目刷新元数据，但保留用户 path 覆盖（path 不同的不回写）。
    """
    import concurrent.futures

    from app.services.workflow_request_resolver import _python_provider_import_path

    provider_root = Path(config.settings.python_provider_root)
    if not provider_root.exists():
        return 0

    def _load_registry() -> dict[str, Any]:
        with _python_provider_import_path(provider_root):
            module = __import__("dataset_config")
            return dict(getattr(module, "DATASET_REGISTRY", {}))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            registry = executor.submit(_load_registry).result(timeout=5.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("dataset registry sync: import dataset_config failed: %s", exc)
        return 0

    repo = get_dataset_registry()
    synced = 0
    for logical_name, info in registry.items():
        try:
            rel_path = str(getattr(info, "relative_path", "") or "")
            if not rel_path:
                continue
            variables = [str(v) for v in (getattr(info, "variables", ()) or ())]
            time_range_raw = getattr(info, "time_range", None)
            if isinstance(time_range_raw, (tuple, list)) and time_range_raw:
                time_range = "~".join(str(t) for t in time_range_raw)
            else:
                time_range = ""
            tags = [str(t) for t in (getattr(info, "tags", ()) or ())]
            # 已存在条目若 path 与算法包 relative_path 不同，视为用户覆盖，不回写；
            # enabled 同理保留用户启停（sync 不得复活被禁用的内置条目）
            effective_path = rel_path
            effective_enabled = True
            prev = repo.get_by_logical_name(str(logical_name))
            if prev is not None:
                if str(prev.get("path") or "").strip() not in ("", rel_path):
                    effective_path = str(prev["path"])
                effective_enabled = bool(prev.get("enabled"))
            repo.upsert(
                dataset_id=None,
                logical_name=str(logical_name),
                path=effective_path,
                file_format=str(getattr(info, "file_format", "") or ""),
                variables=variables,
                time_range=time_range,
                resolution=str(getattr(info, "resolution", "") or ""),
                tags=tags,
                description=str(getattr(info, "description", "") or ""),
                source="algorithm_registry",
                enabled=effective_enabled,
            )
            synced += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "dataset registry sync: failed for %s: %s", logical_name, exc
            )
    return synced


def _count_files(directory: Path, *, max_files: int = 5000) -> tuple[int, bool]:
    count = 0
    truncated = False
    try:
        for _ in directory.rglob("*"):
            count += 1
            if count >= max_files:
                truncated = True
                break
    except OSError:
        pass
    return count, truncated


def rescan_data_root() -> dict[str, Any]:
    """扫描数据根一级/二级目录：未注册目录生成 source=scan 条目，已有条目刷新统计。"""
    repo = get_dataset_registry()
    root = Path(config.settings.data_root) if config.settings.data_root else None
    if root is None or not root.exists():
        return {"root": str(root or ""), "created": 0, "refreshed": 0, "entries": []}

    existing = {e["logical_name"]: e for e in repo.list_entries()}
    now = _now_iso()
    created: list[str] = []
    refreshed = 0

    def _normalize_rel(rel: Path) -> str:
        return rel.as_posix().lstrip("/")

    children = sorted(p for p in root.iterdir() if p.is_dir())
    scan_dirs: list[Path] = []
    for child in children:
        scan_dirs.append(child)
        # 二级目录（一级目录本身通常是分类，如 Soil_Moisture/）
        try:
            for sub in sorted(child.iterdir()):
                if sub.is_dir():
                    scan_dirs.append(sub)
        except OSError:
            continue

    for directory in scan_dirs:
        rel = _normalize_rel(directory.relative_to(root))
        logical = directory.name
        entry = existing.get(logical)
        file_count, truncated = _count_files(directory)
        if entry is not None:
            if entry["source"] == "algorithm_registry" and entry.get("path") == rel:
                repo.upsert(
                    dataset_id=entry["dataset_id"],
                    logical_name=entry["logical_name"],
                    path=entry["path"],
                    file_format=entry.get("file_format") or "",
                    variables=entry.get("variables"),
                    time_range=entry.get("time_range") or "",
                    resolution=entry.get("resolution") or "",
                    tags=entry.get("tags"),
                    source="algorithm_registry",
                    enabled=entry.get("enabled", True),
                    file_count=file_count if not truncated else None,
                    last_scanned_at=now,
                )
            else:
                repo.update_scan_stats(
                    logical, file_count=None if truncated else file_count
                )
            refreshed += 1
        else:
            repo.upsert(
                dataset_id=None,
                logical_name=logical,
                path=rel,
                source="scan",
                enabled=True,
                file_count=file_count if not truncated else None,
                last_scanned_at=now,
            )
            created.append(logical)

    entries = repo.list_entries()
    return {
        "root": str(root),
        "created": len(created),
        "created_names": created,
        "refreshed": refreshed,
        "entries": entries,
    }


def resolve_dataset_path(logical_name: str) -> Path | None:
    """readiness 联动：注册表优先（logical_name → path），未命中返回 None。

    path 可为绝对路径或相对 BACKEND_DATA_ROOT；仅 enabled 且存在的返回。
    """
    try:
        entry = get_dataset_registry().get_by_logical_name(str(logical_name))
    except Exception as exc:  # noqa: BLE001
        logger.debug("dataset registry lookup failed for %s: %s", logical_name, exc)
        return None
    if entry is None or not entry.get("enabled"):
        return None
    raw = str(entry.get("path") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        base = Path(config.settings.data_root) if config.settings.data_root else None
        if base is None:
            return None
        path = base / path
    try:
        if path.exists():
            return path
    except OSError:
        return None
    return None


def invalidate_dataset_caches() -> None:
    """注册表写操作后失效 workflow_request_resolver 的路径缓存。"""
    try:
        from app.services.workflow_request_resolver import invalidate_template_cache

        invalidate_template_cache()
    except Exception as exc:  # noqa: BLE001
        logger.debug("invalidate dataset caches failed: %s", exc)
