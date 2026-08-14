"""Queue dispatch service for queued workflow wakeup.

Phase C: When a workflow is queued due to per-user concurrency limits,
this service is triggered after workflow completion (success, failure,
or cancel) to check if queued workflows can now be dispatched to Celery.

The service checks both global pool capacity and per-user concurrency
limits before dispatching each queued run. The per-user limit is an
*additional* constraint on top of the global pool — the global mechanism
remains unchanged.

Duplicate dispatch prevention: before dispatching, the run is atomically
transitioned from ``queued`` to ``accepted`` via CAS (Compare-And-Swap).
This prevents the Beat task and lifecycle triggers from dispatching the
same run concurrently. After CAS, ``submission_service._dispatch_async_workflow``
handles Celery dispatch + status update to ``queued`` (Celery-queue meaning)
+ event recording.
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC

from shared.contracts.api_contracts import ExecutionStatus, WorkflowSubmitRequest

logger = logging.getLogger(__name__)


class QueueDispatchService:
    """Dispatch queued workflows when capacity becomes available.

    Triggered by :class:`WorkflowLifecycleService` after workflow
    success/failure/cancel. Checks both global and per-user capacity
    before dispatching each queued run to Celery.
    """

    def __init__(self, repository, submission_service) -> None:
        self._repository = repository
        self._submission = submission_service

    def dispatch_queued_workflows(self, user_id: int | None = None) -> int:
        """Check and dispatch queued workflows that can now run.

        Args:
            user_id: If provided, only dispatch queued runs for this user.
                If ``None``, dispatch queued runs for all users.

        Returns:
            The number of workflows dispatched.
        """
        queued_runs = self._repository.get_queued_runs(user_id=user_id, limit=50)
        if not queued_runs:
            return 0

        dispatched = 0
        for run in queued_runs:
            run_id = run["run_id"]
            try:
                run_class = run.get("run_class") or "business"

                # 1. Check global pool capacity
                capacity_limit = self._submission._workflow_capacity_limit(run_class)
                active = self._repository.count_active_runs(run_class)
                if active >= capacity_limit:
                    # Global pool full — no more dispatch possible.
                    break

                # 2. Check per-user capacity (exclude queued — they wait for
                #    free slots and must not count against waking peers).
                run_user_id = run.get("user_id")
                if run_user_id is not None:
                    user_limit = self._resolve_user_limit(run_user_id)
                    if user_limit is not None:
                        user_active = self._repository.count_active_runs_by_user(
                            run_user_id,
                            run_class,
                            exclude_queued=True,
                        )
                        if user_active >= user_limit:
                            continue  # User still at capacity, skip

                # 3. Validate request_json BEFORE CAS so a missing payload
                #    cannot leave the run stuck in ``accepted``.
                request_json = run.get("request_json")
                if not request_json:
                    logger.warning(
                        "Queued run %s has no request_json, marking failed",
                        run_id,
                    )
                    self._fail_queued_run(run_id, "Queued run missing request_json")
                    continue
                try:
                    payload = WorkflowSubmitRequest.model_validate_json(request_json)
                except Exception:
                    logger.exception(
                        "Queued run %s has invalid request_json, marking failed",
                        run_id,
                    )
                    self._fail_queued_run(run_id, "Queued run has invalid request_json")
                    continue

                # 4. CAS: queued → accepted to prevent duplicate dispatch.
                current_run = self._repository.get_run(run_id)
                if current_run is None:
                    continue
                if current_run.status != ExecutionStatus.queued:
                    continue
                accepted_status = current_run.model_copy(
                    update={
                        "status": ExecutionStatus.accepted,
                        "updated_at": datetime.now(UTC),
                    }
                )
                try:
                    self._repository.save_run_cas(
                        accepted_status,
                        expected_status=ExecutionStatus.queued,
                    )
                except Exception:
                    logger.debug(
                        "CAS failed for queued run %s "
                        "(likely dispatched by another trigger)",
                        run_id,
                    )
                    continue

                # 5. Dispatch to Celery via submission_service (handles
                #    dispatch + status update to queued + event recording).
                #    If dispatch fails, _dispatch_async_workflow saves the
                #    run back to queued with error diagnostics, allowing
                #    the next Beat cycle to retry.
                self._submission._dispatch_async_workflow(run_id, payload)
                dispatched += 1
                logger.info(
                    "Dispatched queued run %s (user_id=%s, run_class=%s)",
                    run_id,
                    run_user_id,
                    run_class,
                )
            except Exception:
                logger.exception("Failed to dispatch queued run %s", run_id)
        return dispatched

    def _fail_queued_run(self, run_id: str, reason: str) -> None:
        current_run = self._repository.get_run(run_id)
        if current_run is None or current_run.status != ExecutionStatus.queued:
            return
        failed = current_run.model_copy(
            update={
                "status": ExecutionStatus.failed,
                "updated_at": datetime.now(UTC),
                "message": reason,
                "diagnostics": list(current_run.diagnostics or []) + [reason],
            }
        )
        try:
            self._repository.save_run_cas(
                failed,
                expected_status=ExecutionStatus.queued,
            )
        except Exception:
            logger.debug("CAS failed while marking run %s failed", run_id)

    def _resolve_user_limit(self, user_id: int) -> int | None:
        """Resolve the per-user concurrency limit for a user.

        Looks up the user's role from the users table and delegates to
        ``submission_service._user_concurrency_limit``.
        """
        from app.services.user_repository import get_user_repository

        user_repo = get_user_repository()
        user = user_repo.get_by_id(user_id)
        if not user:
            return None
        role = user.get("role")
        return self._submission._user_concurrency_limit(user_id, role)
