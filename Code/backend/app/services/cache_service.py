from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import threading
from typing import Any

from app.core.config import settings


logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    cache_key: str
    scope: str
    created_at: datetime
    expires_at: datetime
    status: str
    metadata: dict[str, Any]

    @property
    def is_fresh(self) -> bool:
        return self.expires_at > datetime.now(timezone.utc)


@dataclass
class CacheStats:
    """缓存运行时统计快照。"""

    hits: int = 0
    misses: int = 0
    upserts: int = 0
    evictions: int = 0
    total_entries: int = 0
    fresh_entries: int = 0
    expired_entries: int = 0
    scopes: dict[str, int] = field(default_factory=dict)
    hit_rate: float = 0.0


class CacheService:
    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self._cache_dir = Path(cache_dir or settings.cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        # 运行时计数器（进程内存态，重启归零）
        self._hits = 0
        self._misses = 0
        self._upserts = 0
        self._evictions = 0
        # 计数器线程安全锁
        self._lock = threading.Lock()

    def build_cache_key(self, *, scope: str, parts: dict[str, Any]) -> str:
        normalized = json.dumps(parts, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
        return f"{scope}-{digest}"

    def get_entry(self, cache_key: str) -> CacheEntry | None:
        file_path = self._cache_dir / f"{cache_key}.json"
        if not file_path.exists():
            with self._lock:
                self._misses += 1
            return None
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        entry = CacheEntry(
            cache_key=payload["cache_key"],
            scope=payload["scope"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            status=payload["status"],
            metadata=payload.get("metadata", {}),
        )
        if not entry.is_fresh:
            # 过期视为 miss
            with self._lock:
                self._misses += 1
            return None
        with self._lock:
            self._hits += 1
        return entry

    def upsert_entry(
        self,
        *,
        cache_key: str,
        scope: str,
        ttl_seconds: int,
        status: str,
        metadata: dict[str, Any],
    ) -> CacheEntry:
        now = datetime.now(timezone.utc)
        entry = CacheEntry(
            cache_key=cache_key,
            scope=scope,
            created_at=now,
            expires_at=now + timedelta(seconds=max(1, ttl_seconds)),
            status=status,
            metadata=metadata,
        )
        file_path = self._cache_dir / f"{cache_key}.json"
        # 若是覆盖已有过期条目，记为 eviction
        if file_path.exists():
            try:
                previous = json.loads(file_path.read_text(encoding="utf-8"))
                previous_expires = datetime.fromisoformat(previous["expires_at"])
                if previous_expires <= now:
                    with self._lock:
                        self._evictions += 1
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
        file_path.write_text(
            json.dumps(
                {
                    "cache_key": entry.cache_key,
                    "scope": entry.scope,
                    "created_at": entry.created_at.isoformat(),
                    "expires_at": entry.expires_at.isoformat(),
                    "status": entry.status,
                    "metadata": entry.metadata,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with self._lock:
            self._upserts += 1
        return entry

    def get_stats(self) -> CacheStats:
        """返回当前缓存运行时统计快照。"""
        now = datetime.now(timezone.utc)
        total_entries = 0
        fresh_entries = 0
        expired_entries = 0
        scopes: dict[str, int] = {}

        for entry_file in self._cache_dir.glob("*.json"):
            try:
                payload = json.loads(entry_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            total_entries += 1
            scope = str(payload.get("scope", "unknown"))
            scopes[scope] = scopes.get(scope, 0) + 1
            try:
                expires_at = datetime.fromisoformat(payload["expires_at"])
                if expires_at > now:
                    fresh_entries += 1
                else:
                    expired_entries += 1
            except (KeyError, ValueError):
                expired_entries += 1

        with self._lock:
            hits = self._hits
            misses = self._misses
            upserts = self._upserts
            evictions = self._evictions
        total_lookups = hits + misses
        hit_rate = (hits / total_lookups) if total_lookups > 0 else 0.0

        return CacheStats(
            hits=hits,
            misses=misses,
            upserts=upserts,
            evictions=evictions,
            total_entries=total_entries,
            fresh_entries=fresh_entries,
            expired_entries=expired_entries,
            scopes=scopes,
            hit_rate=round(hit_rate, 4),
        )

    def cleanup_expired(self, *, now: datetime | None = None) -> dict[str, int]:
        """扫描缓存目录，删除所有已过期的缓存文件，回收磁盘空间。

        Args:
            now: 用于判断过期的基准时间（默认当前 UTC 时间）

        Returns:
            {"deleted": N, "skipped": M, "errors": K}
        """
        now = now or datetime.now(timezone.utc)
        stats = {"deleted": 0, "skipped": 0, "errors": 0}

        for entry_file in self._cache_dir.glob("*.json"):
            try:
                payload = json.loads(entry_file.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(payload["expires_at"])
                if expires_at > now:
                    stats["skipped"] += 1
                    continue
                entry_file.unlink(missing_ok=True)
                stats["deleted"] += 1
            except (json.JSONDecodeError, KeyError, ValueError):
                # 损坏的缓存文件：直接删除避免持续报错
                try:
                    entry_file.unlink(missing_ok=True)
                    stats["deleted"] += 1
                except OSError:
                    stats["errors"] += 1
            except OSError:
                stats["errors"] += 1

        logger.info(
            "cleanup_expired: deleted %d, skipped %d fresh, errors %d",
            stats["deleted"],
            stats["skipped"],
            stats["errors"],
        )
        return stats


cache_service = CacheService()
