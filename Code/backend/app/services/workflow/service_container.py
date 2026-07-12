"""Service container: replaces the old interaction_hub global singleton.

Provides module-level instances of the 6 workflow services for use by routes.py
and main.py. Tests can import service classes directly and inject custom
repositories via constructor parameters.

Late binding is used to break the circular dependency between submission_service
and lifecycle_service (retry → submit → process → finalize).
"""
from __future__ import annotations

from app.services.workflow_repository import SQLiteWorkflowRepository
from app.services.workflow.follow_up_dispatch_service import FollowUpDispatchService
from app.services.workflow.lifecycle_service import WorkflowLifecycleService
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.runtime_status_service import RuntimeStatusService
from app.services.workflow.submission_service import WorkflowSubmissionService
from app.services.workflow.transition_builder import WorkflowTransitionBuilder

# Shared repository (matches original InMemoryInteractionHub behavior)
_repository = SQLiteWorkflowRepository()

# Stateless services (no cross-service deps)
transition_builder = WorkflowTransitionBuilder()
persistence_service = WorkflowPersistenceService(_repository)
runtime_status_service = RuntimeStatusService(_repository)

# Services with deps on transition_builder + persistence
follow_up_dispatch_service = FollowUpDispatchService(_repository, persistence_service, transition_builder)

# Services with circular dep — created first, then late-bound
submission_service = WorkflowSubmissionService(
    _repository, persistence_service, transition_builder, follow_up_dispatch_service
)
lifecycle_service = WorkflowLifecycleService(
    _repository, persistence_service, transition_builder, follow_up_dispatch_service
)

# Late binding to break circular dependency
submission_service.set_lifecycle_service(lifecycle_service)
lifecycle_service.set_submission_service(submission_service)
