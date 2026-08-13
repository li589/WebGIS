"""Tests for app.services.workflow.persistence_service.WorkflowPersistenceService.

Focuses on the pure-logic helpers (make_event, augment_result_dto,
extract_exception_diagnostics, get_effective_config_int) and the
record_event validation path, using a mock repository to avoid DB I/O.
"""

from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import MagicMock

from app.services.workflow.persistence_service import WorkflowPersistenceService
from shared.contracts.api_contracts import (
    EventChannel,
    FailureCategory,
    LogLevel,
)
from app.services.bridge_protocol import BridgeExecutionError


def _service() -> tuple[WorkflowPersistenceService, MagicMock]:
    repo = MagicMock()
    return WorkflowPersistenceService(repo), repo


# ---------------------------------------------------------------------------
# make_event
# ---------------------------------------------------------------------------


def test_make_event_generates_event_id_and_defaults():
    """make_event builds a WorkflowEvent with a generated event_id and defaults."""
    svc, _ = _service()
    event = svc.make_event(
        run_id="run-1",
        channel=EventChannel.status,
        message="hello",
    )
    assert event.event_id.startswith("evt-"), "event_id must be generated with evt- prefix"
    assert event.run_id == "run-1", "run_id must be propagated"
    assert event.channel == EventChannel.status, "channel must be preserved"
    assert event.level == LogLevel.info, "default level must be info"
    assert event.message == "hello", "message must be preserved"
    assert event.payload == {}, "default payload must be empty dict"
    assert event.created_at is not None, "created_at must default to now"


def test_make_event_coerces_string_channel_and_level():
    """String channel/level values are coerced into their enum counterparts."""
    svc, _ = _service()
    event = svc.make_event(
        run_id="run-1",
        channel="status",
        message="msg",
        level="warning",
    )
    assert event.channel == EventChannel.status, "string channel 'status' must coerce"
    assert event.level == LogLevel.warning, "string level 'warning' must coerce"


def test_make_event_passes_through_progress_and_payload():
    """Explicit progress and payload are embedded in the event."""
    svc, _ = _service()
    event = svc.make_event(
        run_id="run-1",
        channel=EventChannel.log,
        message="progress update",
        progress=42,
        payload={"step": 3},
    )
    assert event.progress == 42, "progress must be propagated"
    assert event.payload == {"step": 3}, "payload must be propagated"


# ---------------------------------------------------------------------------
# record_event validation
# ---------------------------------------------------------------------------


def test_record_event_requires_fields_when_no_event():
    """Without an event object, run_id/channel/message are all required."""
    svc, repo = _service()
    try:
        svc.record_event(run_id="run-1", channel=EventChannel.status, message=None)
    except ValueError:
        pass
    else:
        raise AssertionError("record_event must raise ValueError when message is missing")
    repo.append_event.assert_not_called(), "append_event must not be called on validation failure"


def test_record_event_appends_provided_event():
    """When a full event object is passed, it is appended directly."""
    svc, repo = _service()
    event = svc.make_event(run_id="r", channel="status", message="m")
    svc.record_event(event=event)
    repo.append_event.assert_called_once_with(event), (
        "provided event must be appended as-is"
    )


def test_record_event_builds_and_appends_from_fields():
    """From fields, an event is built via make_event then appended."""
    svc, repo = _service()
    svc.record_event(
        run_id="run-x",
        channel=EventChannel.system,
        message="built",
        progress=10,
    )
    repo.append_event.assert_called_once()
    appended = repo.append_event.call_args.args[0]
    assert appended.run_id == "run-x", "appended event run_id must match"
    assert appended.message == "built", "appended event message must match"


# ---------------------------------------------------------------------------
# augment_result_dto
# ---------------------------------------------------------------------------


def test_augment_result_dto_merges_extra_fields():
    """Extra fields are merged into a copy of the existing result_dto."""
    svc, _ = _service()
    result = svc.augment_result_dto(
        {"summary": "ok"}, materialized_result_count=3, spill_diagnostics_count=1
    )
    assert result == {"summary": "ok", "materialized_result_count": 3, "spill_diagnostics_count": 1}, (
        "extra fields must be merged into the result dto"
    )


def test_augment_result_dto_none_returns_none():
    """A falsy result_dto is returned unchanged (no mutation)."""
    svc, _ = _service()
    assert svc.augment_result_dto(None, count=5) is None, "None dto must stay None"
    assert svc.augment_result_dto({}, count=5) == {}, "empty dto must stay empty dict"


def test_augment_result_dto_does_not_mutate_original():
    """The original dict is not mutated in place."""
    svc, _ = _service()
    original = {"summary": "ok"}
    svc.augment_result_dto(original, materialized_result_count=2)
    assert original == {"summary": "ok"}, "original dict must not be mutated"


# ---------------------------------------------------------------------------
# extract_exception_diagnostics
# ---------------------------------------------------------------------------


def test_extract_exception_diagnostics_non_bridge_returns_empty():
    """A plain exception (not BridgeExecutionError) yields no diagnostics."""
    svc, _ = _service()
    assert svc.extract_exception_diagnostics(RuntimeError("boom")) == [], (
        "non-bridge exception must produce no diagnostics"
    )


def test_extract_exception_diagnostics_bridge_without_resolution_returns_empty():
    """A BridgeExecutionError without resolution_diagnostics yields nothing."""
    svc, _ = _service()
    exc = BridgeExecutionError(
        category=FailureCategory.terminal_failure,
        message="fail",
        details={"other": "value"},
    )
    assert svc.extract_exception_diagnostics(exc) == [], (
        "bridge error without resolution_diagnostics must yield []"
    )


def test_extract_exception_diagnostics_bridge_with_resolution():
    """A BridgeExecutionError with a resolution_diagnostics dict is parsed."""
    svc, _ = _service()
    exc = BridgeExecutionError(
        category=FailureCategory.validation_error,
        message="validation failed",
        details={
            "resolution_diagnostics": {
                "layer_id": "ndvi_layer",
                "module_name": "omega_sf",
                "task_type": "inversion",
                "layer_status": "missing",
                "explicit_data_access_datasets": ["ds_a", "ds_b"],
                "unresolved_default_datasets": [
                    {"dataset_name": "missing_ds", "candidate_sources": ["s1", "s2"]},
                ],
            }
        },
    )
    diags = svc.extract_exception_diagnostics(exc)
    joined = " ".join(diags)
    assert "validation_layer_id=ndvi_layer" in joined, "layer_id diagnostic must be present"
    assert "validation_module_name=omega_sf" in joined, "module_name diagnostic must be present"
    assert "validation_explicit_data_access_datasets=ds_a|ds_b" in joined, (
        "explicit datasets must be joined with |"
    )
    assert "validation_dataset_missing=missing_ds" in joined, "missing dataset must be listed"
    assert "validation_dataset_candidates.missing_ds=s1|s2" in joined, (
        "candidate sources must be joined"
    )


# ---------------------------------------------------------------------------
# get_effective_config_int
# ---------------------------------------------------------------------------


def test_get_effective_config_int_returns_db_value():
    """A valid int in the config snapshot is returned."""
    svc, repo = _service()
    repo.get_config_snapshot.return_value = {"backend": {"max_active_runs": 7}}
    assert svc.get_effective_config_int("backend", "max_active_runs", 5) == 7, (
        "DB int value must be returned when present"
    )


def test_get_effective_config_int_falls_back_on_missing_key():
    """Missing key falls back to the default."""
    svc, repo = _service()
    repo.get_config_snapshot.return_value = {"backend": {}}
    assert svc.get_effective_config_int("backend", "max_active_runs", 5) == 5, (
        "missing key must fall back to default"
    )


def test_get_effective_config_int_falls_back_on_exception():
    """If get_config_snapshot raises, the default is returned (not propagated)."""
    svc, repo = _service()
    repo.get_config_snapshot.side_effect = RuntimeError("db unavailable")
    assert svc.get_effective_config_int("backend", "max_active_runs", 9) == 9, (
        "exception in config snapshot must yield default"
    )


def test_get_effective_config_int_ignores_bool_values():
    """Boolean values (which are int subclasses) must not be treated as ints."""
    svc, repo = _service()
    repo.get_config_snapshot.return_value = {"backend": {"max_active_runs": True}}
    assert svc.get_effective_config_int("backend", "max_active_runs", 4) == 4, (
        "bool True must not be returned as an int; default must be used"
    )


# ---------------------------------------------------------------------------
# save_run_status / save_run_status_cas delegation
# ---------------------------------------------------------------------------


def test_save_run_status_delegates_to_repository():
    """save_run_status forwards all kwargs to repository.save_run."""
    svc, repo = _service()
    status = object()
    svc.save_run_status(
        run_status=status,
        request_json="{}",
        run_class="business",
        user_id=3,
    )
    repo.save_run.assert_called_once_with(
        status, request_json="{}", run_class="business", result_dto_override=None, user_id=3
    ), "save_run_status must delegate to repository.save_run with forwarded kwargs"


def test_save_run_status_cas_delegates_to_repository():
    """save_run_status_cas forwards to repository.save_run_cas and returns its result."""
    svc, repo = _service()
    repo.save_run_cas.return_value = True
    status = object()
    result = svc.save_run_status_cas(
        run_status=status, expected_status="running", request_json="{}"
    )
    assert result is True, "must return the repository's CAS result"
    repo.save_run_cas.assert_called_once_with(
        status, expected_status="running", request_json="{}", run_class=None, result_dto_override=None
    ), "CAS must delegate with forwarded kwargs"
