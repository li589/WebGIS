"""天气引擎全局设置持久化（SQLite key-value）。

当前键：
- ``default_model`` — 全局默认预报模型
- ``last_sync`` — Open-Meteo sync 最近一次结果 JSON
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services._sqlite_pool import SQLiteConnectionPool

logger = logging.getLogger(__name__)

KEY_DEFAULT_MODEL = "default_model"
KEY_LAST_SYNC = "last_sync"


class WeatherEngineSettingsRepository:
    """天气引擎设置 KV 存储（与 weather_providers 同目录）。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool = SQLiteConnectionPool(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS weather_engine_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _connect(self):
        return self._pool.connection()

    def close(self) -> None:
        self._pool.close_all()

    def __del__(self) -> None:
        try:
            self._pool.close_all(quiet=True)
        except Exception:
            pass

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM weather_engine_settings WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return str(row[0])

    def set(self, key: str, value: str) -> None:
        now = self._now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO weather_engine_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, now),
            )
            conn.commit()

    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self.get(key)
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in weather_engine_settings key=%s", key)
            return None
        return parsed if isinstance(parsed, dict) else None

    def set_json(self, key: str, value: dict[str, Any]) -> None:
        self.set(key, json.dumps(value, ensure_ascii=False))
