"""Short agent chat session history (per user / anon)."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_MAX_TURNS = 12
_lock = threading.Lock()
_SAFE_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# Session retention / quota (Phase 0 / M-2).
_SESSION_TTL_HOURS = max(1, int(os.getenv("BACKEND_AGENT_SESSION_TTL_HOURS", "24")))
_MAX_SESSIONS_PER_USER = max(
    1, int(os.getenv("BACKEND_AGENT_MAX_SESSIONS_PER_USER", "40"))
)


def _sessions_root() -> Path:
    root = Path(settings.data_root or settings.workflow_state_dir or ".")
    path = root / "_runtime" / "agent" / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _session_path(user_key: str, session_id: str) -> Path:
    if not _SAFE_SESSION.match(session_id):
        raise ValueError("无效的 session_id")
    safe_user = re.sub(r"[^A-Za-z0-9_-]", "_", user_key)[:64] or "anon"
    folder = _sessions_root() / safe_user
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{session_id}.json"


def _parse_updated_at(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _is_expired(updated_at: datetime | None, *, now: datetime | None = None) -> bool:
    if updated_at is None:
        # Legacy files without timestamp: treat as expired so they get rewritten or dropped.
        return True
    ref = now or datetime.now(UTC)
    return updated_at + timedelta(hours=_SESSION_TTL_HOURS) < ref


def _user_session_dir(user_key: str) -> Path:
    safe_user = re.sub(r"[^A-Za-z0-9_-]", "_", user_key)[:64] or "anon"
    folder = _sessions_root() / safe_user
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _enforce_session_quota(user_key: str, *, keep_path: Path | None = None) -> None:
    """Drop oldest sessions when over per-user cap (by mtime / updated_at)."""
    folder = _user_session_dir(user_key)
    files = [p for p in folder.glob("*.json") if p.is_file()]
    if keep_path is not None and keep_path not in files and keep_path.exists():
        files.append(keep_path)
    if len(files) <= _MAX_SESSIONS_PER_USER:
        return

    def _sort_key(p: Path) -> float:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            ts = _parse_updated_at(
                data.get("updated_at") if isinstance(data, dict) else None
            )
            if ts is not None:
                return ts.timestamp()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    files.sort(key=_sort_key)
    overflow = len(files) - _MAX_SESSIONS_PER_USER
    for victim in files[:overflow]:
        if keep_path is not None and victim.resolve() == keep_path.resolve():
            continue
        try:
            victim.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to prune agent session %s: %s", victim, exc)


def purge_expired_sessions(*, user_id: int | None = None) -> int:
    """Delete expired session files. If user_id set, only that bucket; else all."""
    removed = 0
    now = datetime.now(UTC)
    root = _sessions_root()
    if user_id is not None:
        dirs = [_user_session_dir(str(user_id))]
    else:
        dirs = [p for p in root.iterdir() if p.is_dir()] if root.exists() else []
    with _lock:
        for folder in dirs:
            for path in folder.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    try:
                        path.unlink(missing_ok=True)
                        removed += 1
                    except OSError:
                        pass
                    continue
                updated = (
                    _parse_updated_at(data.get("updated_at"))
                    if isinstance(data, dict)
                    else None
                )
                # Prefer file mtime when legacy missing updated_at
                if updated is None:
                    try:
                        updated = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                    except OSError:
                        updated = None
                if _is_expired(updated, now=now):
                    try:
                        path.unlink(missing_ok=True)
                        removed += 1
                    except OSError as exc:
                        logger.warning(
                            "Failed to delete expired session %s: %s", path, exc
                        )
    return removed


def load_history(*, user_id: int | None, session_id: str) -> list[dict[str, str]]:
    user_key = str(user_id) if user_id is not None else "anon"
    path = _session_path(user_key, session_id)
    with _lock:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, dict):
            return []
        updated = _parse_updated_at(data.get("updated_at"))
        if updated is None:
            try:
                updated = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            except OSError:
                updated = None
        if _is_expired(updated):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return []
    messages = data.get("messages")
    if not isinstance(messages, list):
        return []
    out: list[dict[str, str]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        if role in {"user", "assistant"} and content:
            out.append({"role": role, "content": content})
    return out[-_MAX_TURNS:]


def append_turn(
    *,
    user_id: int | None,
    session_id: str,
    user_message: str,
    assistant_message: str,
) -> None:
    user_key = str(user_id) if user_id is not None else "anon"
    path = _session_path(user_key, session_id)
    now = datetime.now(UTC)
    with _lock:
        history: list[Any] = []
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("messages"), list):
                    updated = _parse_updated_at(data.get("updated_at"))
                    if updated is None:
                        try:
                            updated = datetime.fromtimestamp(
                                path.stat().st_mtime, tz=UTC
                            )
                        except OSError:
                            updated = None
                    if not _is_expired(updated, now=now):
                        history = list(data["messages"])
            except (OSError, json.JSONDecodeError):
                history = []
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": assistant_message})
        # Keep last N *pairs* ≈ 2N messages
        history = history[-(_MAX_TURNS * 2) :]
        payload = {
            "messages": history,
            "updated_at": now.isoformat(),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        _enforce_session_quota(user_key, keep_path=path)
