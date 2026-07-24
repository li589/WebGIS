"""Service container: replaces the old interaction_hub global singleton.

Provides module-level instances of the workflow services for use by routes.py
and main.py. Tests can import service classes directly and inject custom
repositories via constructor parameters.

Dependency direction is one-way: ``submission → lifecycle`` (for finalize).
User-initiated retry is handled by ``retry_dispatcher`` which receives
``submission_service.submit_workflow`` as a callable, breaking the former
bidirectional late binding (N3).

Repository is lazily initialized via :func:`get_repository` (``@lru_cache``).
Tests can replace it::

    from app.services.workflow.service_container import get_repository
    get_repository.cache_clear()  # reset cache
    # monkeypatch SQLiteWorkflowRepository or get_repository before reimport

Or construct services with a custom repository via constructor injection
(see ``tests/test_interaction_hub.py::_build_services``).
"""

from __future__ import annotations

from functools import lru_cache

from app.services.workflow_repository import SQLiteWorkflowRepository
from app.services.workflow.follow_up_dispatch_service import FollowUpDispatchService
from app.services.workflow.lifecycle_service import WorkflowLifecycleService
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.retry_dispatcher import RetryDispatcher
from app.services.workflow.runtime_status_service import RuntimeStatusService
from app.services.workflow.submission_service import WorkflowSubmissionService
from app.services.workflow.transition_builder import WorkflowTransitionBuilder


@lru_cache(maxsize=1)
def get_repository() -> SQLiteWorkflowRepository:
    """Lazily create the shared SQLiteWorkflowRepository singleton.

    Schema initialization (CREATE TABLE + migration) is deferred from
    import-time to first call. Tests can ``cache_clear()`` to reset and
    monkeypatch ``SQLiteWorkflowRepository`` or this function to inject
    a custom repository (e.g., in-memory SQLite).
    """
    return SQLiteWorkflowRepository()


# Shared repository — created on first call to get_repository()
_repository = get_repository()

# Stateless services (no cross-service deps)
transition_builder = WorkflowTransitionBuilder()
persistence_service = WorkflowPersistenceService(_repository)
runtime_status_service = RuntimeStatusService(_repository)

# Services with deps on transition_builder + persistence
follow_up_dispatch_service = FollowUpDispatchService(
    _repository, persistence_service, transition_builder
)

# submission → lifecycle (one-way late binding for finalize)
submission_service = WorkflowSubmissionService(
    _repository, persistence_service, transition_builder, follow_up_dispatch_service
)
lifecycle_service = WorkflowLifecycleService(
    _repository, persistence_service, transition_builder, follow_up_dispatch_service
)
submission_service.set_lifecycle_service(lifecycle_service)

# RetryDispatcher: receives submit_fn as callable, no back-reference to lifecycle
retry_dispatcher = RetryDispatcher(
    _repository,
    persistence_service,
    transition_builder,
    submission_service.submit_workflow,
)
