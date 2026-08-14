"""Tests for app.services.download_service.DownloadService facade.

The facade is a thin delegator to DownloadOrchestrator and
DownloadProgressTracker. Tests inject mocks for both delegates and
verify correct argument forwarding and return-value pass-through.
"""

from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import MagicMock

from app.services.download_service import DownloadService


def _facade() -> tuple[DownloadService, MagicMock, MagicMock]:
    orchestrator = MagicMock(name="orchestrator")
    tracker = MagicMock(name="progress_tracker")
    svc = DownloadService(orchestrator=orchestrator, progress_tracker=tracker)
    return svc, orchestrator, tracker


# ---------------------------------------------------------------------------
# prepare_download delegation
# ---------------------------------------------------------------------------


def test_prepare_download_delegates_to_orchestrator():
    """prepare_download forwards all kwargs and returns the orchestrator result."""
    svc, orchestrator, _ = _facade()
    plan = MagicMock(name="plan")
    orchestrator.prepare_download.return_value = plan
    snapshot = {"layer": "ndvi"}
    now = datetime.now(UTC)

    result = svc.prepare_download(
        run_id="run-1",
        layer_id="ndvi_layer",
        requested_hour=12.0,
        realtime_preferred=True,
        snapshot=snapshot,
        payload_parameters={"k": "v"},
        requested_at=now,
    )

    assert result is plan, "facade must return the orchestrator's plan unchanged"
    orchestrator.prepare_download.assert_called_once_with(
        run_id="run-1",
        layer_id="ndvi_layer",
        requested_hour=12.0,
        realtime_preferred=True,
        snapshot=snapshot,
        payload_parameters={"k": "v"},
        requested_at=now,
    ), "all kwargs must be forwarded verbatim"


def test_prepare_download_propagates_orchestrator_exception():
    """Exceptions raised by the orchestrator propagate through the facade."""
    svc, orchestrator, _ = _facade()
    orchestrator.prepare_download.side_effect = RuntimeError("plan failed")
    try:
        svc.prepare_download(
            run_id="run-1",
            layer_id="l",
            requested_hour=0.0,
            realtime_preferred=False,
            snapshot={},
            payload_parameters={},
            requested_at=datetime.now(UTC),
        )
    except RuntimeError as exc:
        assert "plan failed" in str(exc), "original exception message must be preserved"
    else:
        raise AssertionError("facade must propagate orchestrator exceptions")


# ---------------------------------------------------------------------------
# build_follow_up_task delegation
# ---------------------------------------------------------------------------


def test_build_follow_up_task_delegates_to_orchestrator():
    """build_follow_up_task forwards run_id/plan/summary_result_id and returns result."""
    svc, orchestrator, _ = _facade()
    plan = MagicMock(name="plan")
    task_desc = {"task_type": "download_fetch"}
    orchestrator.build_follow_up_task.return_value = task_desc

    result = svc.build_follow_up_task(
        run_id="run-1", plan=plan, summary_result_id="res-1"
    )

    assert result is task_desc, "facade must return orchestrator's task descriptor"
    orchestrator.build_follow_up_task.assert_called_once_with(
        run_id="run-1", plan=plan, summary_result_id="res-1"
    ), "build_follow_up_task kwargs must be forwarded"


# ---------------------------------------------------------------------------
# complete_follow_up_task delegation
# ---------------------------------------------------------------------------


def test_complete_follow_up_task_delegates_to_tracker():
    """complete_follow_up_task forwards to the progress tracker and returns its tuple."""
    svc, _, tracker = _facade()
    tracker.complete_follow_up_task.return_value = ([], ["diag"], {"state": "done"})
    now = datetime.now(UTC)

    refs, diags, state = svc.complete_follow_up_task(
        run_id="run-1",
        result_refs=[],
        task_data={"task_type": "download_fetch"},
        cache_key="ck",
        summary_result_id="sum-1",
        manifest_result_id="man-1",
        updated_at=now,
    )

    assert refs == [], "returned result_refs must match tracker output"
    assert diags == ["diag"], "returned diagnostics must match tracker output"
    assert state == {"state": "done"}, "returned state must match tracker output"
    tracker.complete_follow_up_task.assert_called_once_with(
        run_id="run-1",
        result_refs=[],
        task_data={"task_type": "download_fetch"},
        cache_key="ck",
        summary_result_id="sum-1",
        manifest_result_id="man-1",
        updated_at=now,
    ), "complete_follow_up_task kwargs must be forwarded"


def test_complete_follow_up_task_propagates_tracker_exception():
    """Exceptions from the progress tracker propagate through the facade."""
    svc, _, tracker = _facade()
    tracker.complete_follow_up_task.side_effect = ValueError("bad state")
    try:
        svc.complete_follow_up_task(
            run_id="run-1",
            result_refs=[],
            task_data={},
            cache_key="ck",
            summary_result_id="s",
            manifest_result_id="m",
            updated_at=datetime.now(UTC),
        )
    except ValueError as exc:
        assert "bad state" in str(exc), "tracker exception must propagate with message"
    else:
        raise AssertionError("facade must propagate tracker exceptions")


# ---------------------------------------------------------------------------
# Default singleton wiring
# ---------------------------------------------------------------------------


def test_default_delegates_used_when_none():
    """When no delegates are injected, the module-level singletons are used."""
    svc = DownloadService()
    assert svc._orchestrator is not None, "default orchestrator singleton must be set"
    assert svc._progress_tracker is not None, "default progress tracker singleton must be set"
