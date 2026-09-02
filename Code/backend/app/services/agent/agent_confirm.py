"""Short-lived confirmation tickets for dangerous Agent actions (Phase B)."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core import config as app_config
from app.services.agent.file_lock import interprocess_file_lock

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_TTL_SECONDS = max(60, int(os.getenv("BACKEND_AGENT_CONFIRM_TTL_SECONDS", "600")))


def _confirm_root() -> Path:
    s = app_config.settings
    root = Path(s.data_root or s.workflow_state_dir or ".")
    path = root / "_runtime" / "agent" / "confirmations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path_for(confirmation_id: str) -> Path:
    if not _SAFE_ID.match(confirmation_id):
        raise ValueError("无效的 confirmation_id")
    return _confirm_root() / f"{confirmation_id}.json"


def create_confirmation(
    *,
    action: str,
    summary: dict[str, Any],
    submit_payload: dict[str, Any],
    user_id: int | None,
    role: str | None,
) -> dict[str, Any]:
    """Persist a one-shot confirmation ticket. Returns public summary + id."""
    cid = uuid.uuid4().hex[:16]
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=_TTL_SECONDS)
    record = {
        "confirmation_id": cid,
        "action": action,
        "status": "pending",
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "user_id": user_id,
        "role": role,
        "summary": summary,
        "submit_payload": submit_payload,
    }
    path = _path_for(cid)
    with _lock:
        with interprocess_file_lock(path, label="Agent 确认票据"):
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(path)
    return {
        "confirmation_id": cid,
        "action": action,
        "expires_at": expires.isoformat(),
        "summary": summary,
    }


def get_confirmation(confirmation_id: str) -> dict[str, Any] | None:
    path = _path_for(confirmation_id)
    with _lock:
        with interprocess_file_lock(path, label="Agent 确认票据"):
            if not path.exists():
                return None
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
    return data if isinstance(data, dict) else None


def _is_expired(record: dict[str, Any], *, now: datetime | None = None) -> bool:
    ref = now or datetime.now(UTC)
    raw = record.get("expires_at")
    if not isinstance(raw, str):
        return True
    try:
        exp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    return exp.astimezone(UTC) < ref


def consume_confirmation(
    confirmation_id: str,
    *,
    user_id: int | None,
    role: str | None,
    decision: str,
) -> dict[str, Any]:
    """Approve or reject a pending ticket. Approve returns submit_payload.

    Raises ValueError on invalid/expired/unauthorized/already-used tickets.
    """
    decision_n = (decision or "").strip().lower()
    if decision_n not in {"approve", "reject"}:
        raise ValueError("decision 必须为 approve 或 reject")

    path = _path_for(confirmation_id)
    with _lock:
        with interprocess_file_lock(path, label="Agent 确认票据"):
            if not path.exists():
                raise ValueError("确认票据不存在或已使用")
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("确认票据损坏") from exc
            if not isinstance(record, dict):
                raise ValueError("确认票据损坏")
            if str(record.get("status") or "") != "pending":
                raise ValueError("确认票据已处理")
            if _is_expired(record):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise ValueError("确认票据已过期")

            owner = record.get("user_id")
            if role != "admin":
                if user_id is None or owner is None or int(owner) != int(user_id):
                    raise ValueError("无权操作此确认票据")

            if decision_n == "reject":
                record["status"] = "rejected"
                record["resolved_at"] = datetime.now(UTC).isoformat()
                tmp = path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                tmp.replace(path)
                return {
                    "confirmation_id": confirmation_id,
                    "status": "rejected",
                    "summary": record.get("summary") or {},
                }

            payload = record.get("submit_payload")
            if not isinstance(payload, dict):
                raise ValueError("确认票据缺少提交快照")
            record["status"] = "approved"
            record["resolved_at"] = datetime.now(UTC).isoformat()
            # One-shot: delete after approve so it cannot be replayed
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "Failed to delete confirmation %s: %s", confirmation_id, exc
                )
            return {
                "confirmation_id": confirmation_id,
                "status": "approved",
                "summary": record.get("summary") or {},
                "submit_payload": payload,
                "action": str(record.get("action") or ""),
            }


def purge_expired_confirmations() -> int:
    removed = 0
    root = _confirm_root()
    now = datetime.now(UTC)
    with _lock:
        for path in root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                try:
                    path.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    pass
                continue
            if isinstance(data, dict) and _is_expired(data, now=now):
                try:
                    path.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    pass
    return removed
