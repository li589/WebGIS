"""Retry dispatcher: handles user-initiated workflow retry.

Extracted from WorkflowLifecycleService to break the bidirectional late binding
between submission_service and lifecycle_service (N3).

Previously, lifecycle_service held a reference to submission_service via
``set_submission_service()`` solely for the ``retry_workflow_run`` method.
By moving retry logic here, the dependency direction becomes one-way:
``submission → lifecycle`` (for finalize), while retry is dispatched through
this stateless dispatcher which receives ``submit_fn`` as a callable.

The automatic retry path (``_schedule_retry`` in lifecycle_service) already
uses ``dispatch_workflow_task`` directly and is unaffected by this extraction.
"""

from __future__ import annotations

from datetime import datetime, UTC
from collections.abc import Callable

from app.services.workflow_repository import SQLiteWorkflowRepository
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.reuse_cache import (
    acquire_retry_reuse_claim,
    inject_retry_reuse_params,
    release_retry_reuse_claim,
    resolve_reuse_output_dir,
    upgrade_retry_reuse_claim,
)
from app.services.workflow.transition_builder import WorkflowTransitionBuilder
from shared.contracts.api_contracts import (
    WorkflowAcceptedResponse,
    WorkflowSubmitRequest,
)

# Type alias: a callable that submits a workflow and returns the accepted response.
# In production this is ``submission_service.submit_workflow``.
SubmitWorkflowFn = Callable[[WorkflowSubmitRequest], WorkflowAcceptedResponse]


class RetryDispatcher:
    """Handles user-initiated workflow retry by re-submitting the original request.

    Stateless: all dependencies are injected at construction time and never
    mutated. The ``submit_fn`` callable decouples this dispatcher from
    ``WorkflowSubmissionService``, breaking the circular dependency.
    """

    def __init__(
        self,
        repository: SQLiteWorkflowRepository,
        persistence: WorkflowPersistenceService,
        transitions: WorkflowTransitionBuilder,
        submit_fn: SubmitWorkflowFn,
    ) -> None:
        self._repository = repository
        self._persistence = persistence
        self._transitions = transitions
        self._submit_fn = submit_fn

    def retry_workflow_run(self, run_id: str) -> WorkflowAcceptedResponse:
        """Re-submit a completed/failed workflow as a new run.

        Fetches the original request JSON, validates it, submits it as a new
        workflow run, then tags the new run with ``retry_of_run_id`` metadata.
        """
        now = datetime.now(UTC)
        request_json = self._repository.get_run_request_json(run_id)
        if request_json is None:
            raise ValueError(f"Cannot retry: no request found for run {run_id}")

        payload = WorkflowSubmitRequest.model_validate_json(request_json)
        reuse_output_dir, _module = resolve_reuse_output_dir(self._repository, run_id)
        claim: str | None = None
        if reuse_output_dir:
            # B-N2：并发双 retry 复用同一目录会并发写块缓存，提交前先拿写互斥 claim
            claim = acquire_retry_reuse_claim(self._repository, reuse_output_dir)
            if claim is None:
                raise ValueError(
                    f"Retry rejected: another retry is already in progress "
                    f"writing to {reuse_output_dir}"
                )
            payload_dict = payload.model_dump(mode="json")
            merged = inject_retry_reuse_params(
                payload_dict, reuse_output_dir=reuse_output_dir
            )
            payload = WorkflowSubmitRequest.model_validate(merged)

        try:
            new_response = self._submit_fn(payload)
        except BaseException:
            if claim is not None:
                release_retry_reuse_claim(reuse_output_dir, claim)
            raise
        new_run = self._repository.get_run(new_response.run_id)

        if new_run:
            if claim is not None:
                # 升级为持有者 run：后续 retry 据其终态懒抢占，TTL 拉长防中途过期
                upgrade_retry_reuse_claim(reuse_output_dir, claim, new_response.run_id)
            retry_meta: dict[str, object] = {
                **new_run.executor_metadata,
                "retry_of_run_id": run_id,
            }
            if reuse_output_dir:
                retry_meta["reuse_block_cache"] = True
                retry_meta["reuse_output_dir"] = reuse_output_dir
            self._persistence.save_run_status(
                run_status=self._transitions.build_execution_transition(
                    run_id=new_response.run_id,
                    payload=payload,
                    status=new_run.status,
                    progress=new_run.progress,
                    message=new_run.message,
                    created_at=new_run.created_at,
                    updated_at=now,
                    result_refs=new_run.result_refs,
                    result_dto=new_run.result_dto,
                    diagnostics=new_run.diagnostics,
                    executor_metadata=retry_meta,
                )
            )
        elif claim is not None:
            # 新 run 未落库：无人会写该目录，立即释放
            release_retry_reuse_claim(reuse_output_dir, claim)
        return new_response
