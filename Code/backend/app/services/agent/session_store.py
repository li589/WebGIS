"""Short agent chat session history (per user / anon)."""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_MAX_TURNS = 12
_lock = threading.Lock()
_SAFE_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


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
    messages = data.get("messages") if isinstance(data, dict) else None
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
    with _lock:
        history = []
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("messages"), list):
                    history = list(data["messages"])
            except (OSError, json.JSONDecodeError):
                history = []
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": assistant_message})
        # Keep last N *pairs* ≈ 2N messages
        history = history[-(_MAX_TURNS * 2) :]
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"messages": history}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
