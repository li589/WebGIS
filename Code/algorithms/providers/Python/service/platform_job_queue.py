from __future__ import annotations

from datetime import UTC, datetime
from threading import local
from typing import Any, Callable

from contracts.job import JobRequest
from service.job_queue import QueuedJobSubmission


PublishSubmissionFn = Callable[[QueuedJobSubmission], None]
ClaimSubmissionFn = Callable[[float | None], QueuedJobSubmission | None]
AckSubmissionFn = Callable[[QueuedJobSubmission], None]


class CallbackJobQueueBackend:
    def __init__(
        self,
        *,
        publish_submission_fn: PublishSubmissionFn,
        claim_submission_fn: ClaimSubmissionFn,
        ack_submission_fn: AckSubmissionFn | None = None,
    ) -> None:
        self._publish_submission_fn = publish_submission_fn
        self._claim_submission_fn = claim_submission_fn
        self._ack_submission_fn = ack_submission_fn
        self._state = local()

    def enqueue(self, submission_id: str, request: JobRequest) -> QueuedJobSubmission:
        item = QueuedJobSubmission(
            submission_id=submission_id,
            request=request,
            enqueued_at=datetime.now(UTC),
        )
        self._publish_submission_fn(item)
        return item

    def dequeue(self, *, timeout: float | None = None) -> QueuedJobSubmission | None:
        item = self._claim_submission_fn(timeout)
        self._state.current_item = item
        return item

    def task_done(self) -> None:
        item = getattr(self._state, "current_item", None)
        if item is None:
            return
        if self._ack_submission_fn is not None:
            self._ack_submission_fn(item)
        self._state.current_item = None


class PlatformJobQueueTemplate:
    def __init__(self) -> None:
        self._state = local()

    def enqueue(self, submission_id: str, request: JobRequest) -> QueuedJobSubmission:
        item = QueuedJobSubmission(
            submission_id=submission_id,
            request=request,
            enqueued_at=datetime.now(UTC),
        )
        self.publish_submission(item)
        return item

    def dequeue(self, *, timeout: float | None = None) -> QueuedJobSubmission | None:
        item = self.claim_submission(timeout=timeout)
        self._state.current_item = item
        return item

    def task_done(self) -> None:
        item = getattr(self._state, "current_item", None)
        if item is None:
            return
        self.ack_submission(item)
        self._state.current_item = None

    def publish_submission(self, item: QueuedJobSubmission) -> None:
        raise NotImplementedError

    def claim_submission(self, *, timeout: float | None = None) -> QueuedJobSubmission | None:
        raise NotImplementedError

    def ack_submission(self, item: QueuedJobSubmission) -> None:
        _ = item


class PlatformJobQueue(PlatformJobQueueTemplate):
    def __init__(
        self,
        *,
        platform_client: Any = None,
        publish_submission_fn: PublishSubmissionFn | None = None,
        claim_submission_fn: ClaimSubmissionFn | None = None,
        ack_submission_fn: AckSubmissionFn | None = None,
    ) -> None:
        super().__init__()
        self._platform_client = platform_client
        self._publish_submission_fn = publish_submission_fn
        self._claim_submission_fn = claim_submission_fn
        self._ack_submission_fn = ack_submission_fn

    def publish_submission(self, item: QueuedJobSubmission) -> None:
        if self._publish_submission_fn is not None:
            self._publish_submission_fn(item)
            return
        if self._platform_client is not None and hasattr(self._platform_client, "publish_submission"):
            self._platform_client.publish_submission(item)
            return
        raise NotImplementedError("PlatformJobQueue requires publish_submission support.")

    def claim_submission(self, *, timeout: float | None = None) -> QueuedJobSubmission | None:
        if self._claim_submission_fn is not None:
            return self._claim_submission_fn(timeout)
        if self._platform_client is not None and hasattr(self._platform_client, "claim_submission"):
            return self._platform_client.claim_submission(timeout=timeout)
        raise NotImplementedError("PlatformJobQueue requires claim_submission support.")

    def ack_submission(self, item: QueuedJobSubmission) -> None:
        if self._ack_submission_fn is not None:
            self._ack_submission_fn(item)
            return
        if self._platform_client is not None and hasattr(self._platform_client, "ack_submission"):
            self._platform_client.ack_submission(item)
