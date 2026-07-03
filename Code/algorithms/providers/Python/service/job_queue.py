from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty, Queue
from threading import local
from typing import Any, Protocol

from contracts.job import JobRequest
from contracts.serialization import coerce_job_request


@dataclass(slots=True)
class QueuedJobSubmission:
    submission_id: str
    request: JobRequest
    enqueued_at: datetime


class JobQueueBackend(Protocol):
    def enqueue(self, submission_id: str, request: JobRequest) -> QueuedJobSubmission: ...

    def dequeue(self, *, timeout: float | None = None) -> QueuedJobSubmission | None: ...

    def task_done(self) -> None: ...


class InMemoryJobQueue:
    def __init__(self) -> None:
        self._queue: Queue[QueuedJobSubmission] = Queue()

    def enqueue(self, submission_id: str, request: JobRequest) -> QueuedJobSubmission:
        item = QueuedJobSubmission(
            submission_id=submission_id,
            request=request,
            enqueued_at=datetime.now(UTC),
        )
        self._queue.put(item)
        return item

    def dequeue(self, *, timeout: float | None = None) -> QueuedJobSubmission | None:
        try:
            return self._queue.get(timeout=timeout)
        except Empty:
            return None

    def task_done(self) -> None:
        self._queue.task_done()


class FileJobQueue:
    def __init__(self, root_dir: str | Path) -> None:
        self._root_dir = Path(root_dir)
        self._pending_dir = self._root_dir / "pending"
        self._inflight_dir = self._root_dir / "inflight"
        self._pending_dir.mkdir(parents=True, exist_ok=True)
        self._inflight_dir.mkdir(parents=True, exist_ok=True)
        self._state = local()

    def enqueue(self, submission_id: str, request: JobRequest) -> QueuedJobSubmission:
        item = QueuedJobSubmission(
            submission_id=submission_id,
            request=request,
            enqueued_at=datetime.now(UTC),
        )
        payload = {
            "submission_id": item.submission_id,
            "request": _to_jsonable(item.request),
            "enqueued_at": item.enqueued_at.isoformat(),
        }
        self._get_pending_path(item.submission_id, item.enqueued_at).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return item

    def dequeue(self, *, timeout: float | None = None) -> QueuedJobSubmission | None:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            claimed = self._claim_next_pending()
            if claimed is not None:
                setattr(self._state, "current_claim_path", claimed[0])
                return claimed[1]
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(0.05)

    def task_done(self) -> None:
        current_claim_path = getattr(self._state, "current_claim_path", None)
        if current_claim_path is None:
            return
        path = Path(current_claim_path)
        if path.exists():
            path.unlink()
        self._state.current_claim_path = None

    def _claim_next_pending(self) -> tuple[Path, QueuedJobSubmission] | None:
        for pending_path in sorted(self._pending_dir.glob("*.json")):
            inflight_path = self._inflight_dir / pending_path.name
            try:
                pending_path.replace(inflight_path)
            except FileNotFoundError:
                continue
            payload = json.loads(inflight_path.read_text(encoding="utf-8"))
            return inflight_path, _queued_submission_from_dict(payload)
        return None

    def _get_pending_path(self, submission_id: str, enqueued_at: datetime) -> Path:
        timestamp = enqueued_at.strftime("%Y%m%dT%H%M%S%fZ")
        return self._pending_dir / f"{timestamp}_{submission_id}.json"


def _queued_submission_from_dict(payload: dict[str, Any]) -> QueuedJobSubmission:
    return QueuedJobSubmission(
        submission_id=str(payload["submission_id"]),
        request=coerce_job_request(payload["request"]),
        enqueued_at=datetime.fromisoformat(str(payload["enqueued_at"])),
    )


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    return value
