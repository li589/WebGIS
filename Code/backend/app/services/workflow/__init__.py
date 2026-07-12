"""Workflow service package.

Split from interaction_hub.py (1454 lines) into 6 focused services:
- transition_builder: stateless transition object builders
- persistence_service: repository persistence + event recording
- follow_up_dispatch_service: follow-up task dispatch + stale cleanup
- runtime_status_service: runtime status/config/health
- submission_service: workflow submission + execution
- lifecycle_service: cancel/retry/timeout/failure handling

Service container provides module-level singletons replacing the old
``interaction_hub`` global. Tests can import service classes directly
and inject custom repositories.
"""
