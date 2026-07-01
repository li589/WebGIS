from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.config import settings


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


class CacheService:
    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self._cache_dir = Path(cache_dir or settings.cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def build_cache_key(self, *, scope: str, parts: dict[str, Any]) -> str:
        normalized = json.dumps(parts, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
        return f"{scope}-{digest}"

    def get_entry(self, cache_key: str) -> CacheEntry | None:
        file_path = self._cache_dir / f"{cache_key}.json"
        if not file_path.exists():
            return None
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        return CacheEntry(
            cache_key=payload["cache_key"],
            scope=payload["scope"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            status=payload["status"],
            metadata=payload.get("metadata", {}),
        )

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
        return entry


cache_service = CacheService()
