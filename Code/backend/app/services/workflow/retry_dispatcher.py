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

from datetime import datetime, timezone
from typing import Callable

from app.services.workflow_repository import SQLiteWorkflowRepository
from app.services.workflow.persistence_service import WorkflowPersistenceService
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
        now = datetime.now(timezone.utc)
        request_json = self._repository.get_run_request_json(run_id)
        if request_json is None:
            raise ValueError(f"Cannot retry: no request found for run {run_id}")

        payload = WorkflowSubmitRequest.model_validate_json(request_json)
        new_response = self._submit_fn(payload)
        new_run = self._repository.get_run(new_response.run_id)

        if new_run:
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
                    executor_metadata={
                        **new_run.executor_metadata,
                        "retry_of_run_id": run_id,
                    },
                )
            )
        return new_response
