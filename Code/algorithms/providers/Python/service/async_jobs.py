from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

from contracts.job import JobResult


@dataclass(slots=True)
class AsyncJobSnapshot:
    submission_id: str
    job_id: str
    state: str
    accepted_at: datetime
    updated_at: datetime
    run_id: str | None = None
    scheduler_status: str | None = None
    status_detail: dict[str, Any] = field(default_factory=dict)
    job_result: JobResult | None = None
    final_response_status: int | None = None
    final_response_body: dict[str, Any] | None = None


class AsyncJobStore(Protocol):
    def create_submission(self, job_id: str) -> AsyncJobSnapshot: ...

    def mark_running(self, submission_id: str) -> None: ...

    def mark_queued(self, submission_id: str) -> None: ...

    def record_status(
        self,
        submission_id: str,
        *,
        job_id: str,
        run_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None: ...

    def record_completion(self, submission_id: str, *, result: JobResult) -> None: ...

    def record_response(self, submission_id: str, response) -> None: ...

    def get_submission(self, submission_id: str) -> AsyncJobSnapshot | None: ...


class AsyncJobRegistry:
    def __init__(self) -> None:
        self._items: dict[str, AsyncJobSnapshot] = {}
        self._lock = Lock()

    def create_submission(self, job_id: str) -> AsyncJobSnapshot:
        now = datetime.now(UTC)
        snapshot = AsyncJobSnapshot(
            submission_id=uuid4().hex,
            job_id=job_id,
            state="accepted",
            accepted_at=now,
            updated_at=now,
        )
        with self._lock:
            self._items[snapshot.submission_id] = snapshot
        return snapshot

    def mark_running(self, submission_id: str) -> None:
        with self._lock:
            snapshot = self._items.get(submission_id)
            if snapshot is None:
                return
            snapshot.state = "running"
            snapshot.updated_at = datetime.now(UTC)

    def mark_queued(self, submission_id: str) -> None:
        with self._lock:
            snapshot = self._items.get(submission_id)
            if snapshot is None:
                return
            snapshot.state = "queued"
            snapshot.updated_at = datetime.now(UTC)

    def record_status(
        self,
        submission_id: str,
        *,
        job_id: str,
        run_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            snapshot = self._items.get(submission_id)
            if snapshot is None:
                return
            snapshot.job_id = job_id
            snapshot.run_id = run_id
            snapshot.scheduler_status = status
            snapshot.status_detail = {} if detail is None else dict(detail)
            snapshot.updated_at = datetime.now(UTC)

    def record_completion(self, submission_id: str, *, result: JobResult) -> None:
        with self._lock:
            snapshot = self._items.get(submission_id)
            if snapshot is None:
                return
            snapshot.job_result = result
            snapshot.run_id = result.run_id
            snapshot.state = "completed" if result.status == "success" else "failed"
            snapshot.updated_at = datetime.now(UTC)

    def record_response(self, submission_id: str, response) -> None:
        with self._lock:
            snapshot = self._items.get(submission_id)
            if snapshot is None:
                return
            snapshot.final_response_status = response.status_code
            snapshot.final_response_body = dict(response.body)
            if snapshot.job_result is None and response.status_code >= 400:
                snapshot.state = "failed"
            snapshot.updated_at = datetime.now(UTC)

    def get_submission(self, submission_id: str) -> AsyncJobSnapshot | None:
        with self._lock:
            snapshot = self._items.get(submission_id)
            if snapshot is None:
                return None
            return _clone_snapshot(snapshot)


class FileAsyncJobRegistry:
    def __init__(self, root_dir: str | Path) -> None:
        self._root_dir = Path(root_dir)
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def create_submission(self, job_id: str) -> AsyncJobSnapshot:
        now = datetime.now(UTC)
        snapshot = AsyncJobSnapshot(
            submission_id=uuid4().hex,
            job_id=job_id,
            state="accepted",
            accepted_at=now,
            updated_at=now,
        )
        with self._lock:
            self._write_snapshot(snapshot)
        return _clone_snapshot(snapshot)

    def mark_running(self, submission_id: str) -> None:
        self._update_snapshot(
            submission_id,
            lambda snapshot: _set_state(snapshot, "running"),
        )

    def mark_queued(self, submission_id: str) -> None:
        self._update_snapshot(
            submission_id,
            lambda snapshot: _set_state(snapshot, "queued"),
        )

    def record_status(
        self,
        submission_id: str,
        *,
        job_id: str,
        run_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        def apply(snapshot: AsyncJobSnapshot) -> None:
            snapshot.job_id = job_id
            snapshot.run_id = run_id
            snapshot.scheduler_status = status
            snapshot.status_detail = {} if detail is None else dict(detail)
            snapshot.updated_at = datetime.now(UTC)

        self._update_snapshot(submission_id, apply)

    def record_completion(self, submission_id: str, *, result: JobResult) -> None:
        def apply(snapshot: AsyncJobSnapshot) -> None:
            snapshot.job_result = result
            snapshot.run_id = result.run_id
            snapshot.state = "completed" if result.status == "success" else "failed"
            snapshot.updated_at = datetime.now(UTC)

        self._update_snapshot(submission_id, apply)

    def record_response(self, submission_id: str, response) -> None:
        def apply(snapshot: AsyncJobSnapshot) -> None:
            snapshot.final_response_status = response.status_code
            snapshot.final_response_body = dict(response.body)
            if snapshot.job_result is None and response.status_code >= 400:
                snapshot.state = "failed"
            snapshot.updated_at = datetime.now(UTC)

        self._update_snapshot(submission_id, apply)

    def get_submission(self, submission_id: str) -> AsyncJobSnapshot | None:
        with self._lock:
            snapshot = self._read_snapshot(submission_id)
            if snapshot is None:
                return None
            return _clone_snapshot(snapshot)

    def _update_snapshot(self, submission_id: str, apply) -> None:
        with self._lock:
            snapshot = self._read_snapshot(submission_id)
            if snapshot is None:
                return
            apply(snapshot)
            self._write_snapshot(snapshot)

    def _read_snapshot(self, submission_id: str) -> AsyncJobSnapshot | None:
        path = self._get_snapshot_path(submission_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _snapshot_from_dict(payload)

    def _write_snapshot(self, snapshot: AsyncJobSnapshot) -> None:
        payload = _snapshot_to_dict(snapshot)
        self._get_snapshot_path(snapshot.submission_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _get_snapshot_path(self, submission_id: str) -> Path:
        return self._root_dir / f"{submission_id}.json"


def _set_state(snapshot: AsyncJobSnapshot, state: str) -> None:
    snapshot.state = state
    snapshot.updated_at = datetime.now(UTC)


def _clone_snapshot(snapshot: AsyncJobSnapshot) -> AsyncJobSnapshot:
    return AsyncJobSnapshot(
        submission_id=snapshot.submission_id,
        job_id=snapshot.job_id,
        state=snapshot.state,
        accepted_at=snapshot.accepted_at,
        updated_at=snapshot.updated_at,
        run_id=snapshot.run_id,
        scheduler_status=snapshot.scheduler_status,
        status_detail=dict(snapshot.status_detail),
        job_result=snapshot.job_result,
        final_response_status=snapshot.final_response_status,
        final_response_body=None if snapshot.final_response_body is None else dict(snapshot.final_response_body),
    )


def _snapshot_to_dict(snapshot: AsyncJobSnapshot) -> dict[str, Any]:
    payload = _to_jsonable(snapshot)
    return dict(payload)


def _snapshot_from_dict(payload: dict[str, Any]) -> AsyncJobSnapshot:
    job_result_payload = payload.get("job_result")
    job_result = None if job_result_payload is None else _job_result_from_dict(job_result_payload)
    final_response_body = payload.get("final_response_body")
    return AsyncJobSnapshot(
        submission_id=str(payload["submission_id"]),
        job_id=str(payload["job_id"]),
        state=str(payload["state"]),
        accepted_at=datetime.fromisoformat(str(payload["accepted_at"])),
        updated_at=datetime.fromisoformat(str(payload["updated_at"])),
        run_id=None if payload.get("run_id") is None else str(payload["run_id"]),
        scheduler_status=None if payload.get("scheduler_status") is None else str(payload["scheduler_status"]),
        status_detail={} if payload.get("status_detail") is None else dict(payload["status_detail"]),
        job_result=job_result,
        final_response_status=payload.get("final_response_status"),
        final_response_body=None if final_response_body is None else dict(final_response_body),
    )


def _job_result_from_dict(payload: dict[str, Any]) -> JobResult:
    decoded = dict(payload)
    decoded["started_at"] = datetime.fromisoformat(str(decoded["started_at"]))
    decoded["finished_at"] = datetime.fromisoformat(str(decoded["finished_at"]))
    decoded["metrics"] = {} if decoded.get("metrics") is None else dict(decoded["metrics"])
    return JobResult(**decoded)


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
