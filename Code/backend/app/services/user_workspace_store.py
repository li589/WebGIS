"""Per-user workspace snapshots (SQLite) for cross-device sync.

存储前端图层工作区快照（叠加/目录/矢量图层 + 分组 + 移除登记），
使同一账号在多台设备上登录后看到一致的图层列表与状态。
payload 对服务端不透明（前端契约，version==1），仅做体量与 revision 校验。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from app.services._sqlite_pool import SQLiteConnectionPool
from app.services.user_repository import _users_db_path

logger = logging.getLogger(__name__)

#: 快照体量上限：80 图层 × 元数据远小于此；超出视为异常（防 DoS/误传 GeoJSON）。
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024


class WorkspaceConflictError(RuntimeError):
    """base_revision 与服务端不一致（其它设备先写入了新版本）。"""

    def __init__(self, server_revision: int, server_updated_at: str) -> None:
        super().__init__(f"workspace revision conflict (server={server_revision})")
        self.server_revision = server_revision
        self.server_updated_at = server_updated_at


class WorkspacePayloadTooLargeError(RuntimeError):
    """快照超过 MAX_PAYLOAD_BYTES。"""


@dataclass(frozen=True)
class WorkspaceRecord:
    user_id: int
    revision: int
    updated_at: str
    payload: dict[str, Any] | None


class UserWorkspaceStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or _users_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool = SQLiteConnectionPool(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_workspaces (
                    user_id INTEGER PRIMARY KEY,
                    revision INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def close(self) -> None:
        self._pool.close_all()

    def get(self, user_id: int) -> WorkspaceRecord:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT revision, updated_at, payload FROM user_workspaces WHERE user_id=?",
                (user_id,),
            ).fetchone()
        if row is None:
            return WorkspaceRecord(
                user_id=user_id, revision=0, updated_at="", payload=None
            )
        return WorkspaceRecord(
            user_id=user_id,
            revision=int(row["revision"]),
            updated_at=str(row["updated_at"]),
            payload=json.loads(row["payload"]),
        )

    def put(
        self,
        user_id: int,
        payload: dict[str, Any],
        base_revision: int | None = None,
    ) -> WorkspaceRecord:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise WorkspacePayloadTooLargeError(
                f"workspace payload exceeds {MAX_PAYLOAD_BYTES} bytes"
            )
        now = datetime.now(UTC).isoformat()
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT revision, updated_at FROM user_workspaces WHERE user_id=?",
                (user_id,),
            ).fetchone()
            current = int(row["revision"]) if row else 0
            if base_revision is not None and base_revision != current:
                raise WorkspaceConflictError(
                    current, str(row["updated_at"]) if row else ""
                )
            conn.execute(
                """
                INSERT INTO user_workspaces (user_id, revision, updated_at, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    revision = excluded.revision,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (user_id, current + 1, now, raw),
            )
            conn.commit()
        return WorkspaceRecord(
            user_id=user_id, revision=current + 1, updated_at=now, payload=payload
        )

    def delete(self, user_id: int) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM user_workspaces WHERE user_id=?", (user_id,))
            conn.commit()


_store: UserWorkspaceStore | None = None


def get_user_workspace_store() -> UserWorkspaceStore:
    global _store
    if _store is None:
        _store = UserWorkspaceStore()
    return _store


def reset_user_workspace_store() -> None:
    """测试隔离：清空进程级单例（下次访问按当前 settings 重建）。"""
    global _store
    if _store is not None:
        try:
            _store.close()
        except Exception:
            logger.debug("close workspace store failed", exc_info=True)
    _store = None
