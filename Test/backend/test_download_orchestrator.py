"""Tests for the download orchestration chain.

Covers:
- ``DownloadOrchestrator.prepare_download`` (cache hit / cache miss)
- ``DownloadOrchestrator.build_follow_up_task``
- ``DownloadProgressTracker.complete_follow_up_task`` (success / partial / all-failed)

All external dependencies (cache_service, source_fetcher_registry,
manifest writer) are mocked — no real network or disk I/O beyond temp dirs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.download_orchestrator import DownloadOrchestrator, DownloadPlan
from app.services.download_progress_tracker import DownloadProgressTracker
from app.services.cache_service import CacheEntry
from app.services.source_fetcher import FetchResult
from shared.contracts.api_contracts import ResultKind, WorkflowResultReference


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(
    data_state_mode: str = "realtime",
    display_name: str = "Test Layer",
    availability_state: str = "available",
) -> SimpleNamespace:
    """Create a lightweight snapshot mock for DownloadOrchestrator.prepare_download."""
    return SimpleNamespace(
        data_state_mode=SimpleNamespace(value=data_state_mode),
        display_name=display_name,
        availability_state=SimpleNamespace(value=availability_state),
        summary="Test snapshot summary",
        status_label="Available",
        data_state_label="Real-time",
    )


def _make_cache_entry(
    cache_key: str = "test-cache-key",
    status: str = "warm",
    metadata: dict | None = None,
    fresh: bool = True,
) -> CacheEntry:
    """Create a CacheEntry with proper timestamps."""
    now = datetime.now(UTC)
    return CacheEntry(
        cache_key=cache_key,
        scope="download-plan",
        created_at=now,
        expires_at=now + timedelta(hours=1) if fresh else now - timedelta(hours=1),
        status=status,
        metadata=metadata or {},
    )


def _make_result_ref(
    result_id: str,
    result_kind: ResultKind = ResultKind.file,
    title: str = "Test Result",
    mime_type: str = "application/json",
    inline_data: dict | None = None,
    resource_key: str | None = "artifacts/test/manifest.json",
    resource_url: str | None = "/artifacts/test/manifest.json",
    resource_backend: str = "local",
    resource_size_bytes: int = 100,
) -> WorkflowResultReference:
    """Create a WorkflowResultReference for test fixtures."""
    return WorkflowResultReference(
        result_id=result_id,
        result_kind=result_kind,
        title=title,
        mime_type=mime_type,
        inline_data=inline_data,
        resource_url=resource_url,
        resource_backend=resource_backend,
        resource_key=resource_key,
        resource_size_bytes=resource_size_bytes,
        updated_at=datetime.now(UTC),
    )


def _make_summary_inline_data(
    source_refs: list[dict] | None = None,
    download_ticket_id: str = "download-abc123",
) -> dict:
    """Create a summary result inline_data structure for complete_follow_up_task.

    The structure must include ``download_plan``, ``execution``, ``cache``,
    and ``preview`` keys because the tracker writes back into them.
    """
    return {
        "download_plan": {
            "source_refs": source_refs or [],
            "target_dataset": "Test Layer",
            "requested_hour": 12.0,
            "source_mode": "realtime",
            "refresh_policy": "scheduled",
            "channel": "download",
        },
        "execution": {
            "download_ticket_id": download_ticket_id,
            "status": "prepared",
            "job_state": {
                "ticket_id": download_ticket_id,
                "phase": "prepared",
                "status": "awaiting_fetch",
                "progress": 45,
                "fetch_attempts": 0,
            },
        },
        "cache": {
            "status": "cold",
            "expires_at": "2024-01-01T00:00:00+00:00",
        },
        "preview": {
            "availability_state": "available",
        },
        "workflow": {
            "command_type": "download",
            "layer_id": "test-layer",
        },
        "source_fetch": {},
    }


def _make_source_refs(count: int = 2) -> list[dict]:
    """Create a list of pending source_refs for the fetch loop."""
    return [
        {
            "ref_id": f"ref-{i}",
            "source_uri": f"http://example.com/data{i}.json",
            "fetch_status": "pending",
            "fetch_stage": "awaiting_dispatch",
            "source_kind": "real_source",
            "estimated_bytes": 100 * (i + 1),
            "layer_id": "test-layer",
            "requested_hour": 12.0,
            "refresh_policy": "scheduled",
        }
        for i in range(count)
    ]


def _make_task_data(
    source_refs: list[dict] | None = None,
    max_attempts: int = 3,
    simulate_fail_attempts: int = 0,
    partial_failure_ref_ids: list[str] | None = None,
) -> dict:
    """Create a task_data dict for complete_follow_up_task."""
    return {
        "task_type": "download_fetch",
        "run_id": "test-run-1",
        "download_ticket_id": "download-abc123",
        "cache_key": "test-cache-key",
        "summary_result_id": "summary-1",
        "manifest_result_id": "manifest-1",
        "artifact_resource_key": "artifacts/test/manifest.json",
        "source_refs": source_refs or _make_source_refs(),
        "max_attempts": max_attempts,
        "simulate_fail_attempts": simulate_fail_attempts,
        "partial_failure_ref_ids": partial_failure_ref_ids or [],
    }


def _make_manifest_ref_for_replace() -> WorkflowResultReference:
    """Create the manifest ref returned by the mock replace_manifest_result_ref."""
    return _make_result_ref(
        result_id="manifest-1",
        title="Test Layer Download Manifest",
        resource_key="artifacts/test-run-1/manifest-updated.json",
        resource_url="/artifacts/test-run-1/manifest-updated.json",
        resource_size_bytes=256,
    )


# ---------------------------------------------------------------------------
# DownloadOrchestrator tests
# ---------------------------------------------------------------------------

def test_download_orchestrator_prepare_download_cache_hit() -> None:
    """Mock cache_service.get_object to return a cached entry → plan has cache_hit, no fetch needed."""
    cached_entry = _make_cache_entry(
        status="warm",
        metadata={
            "download_ticket_id": "download-cached123",
            "artifact_resource_key": "artifacts/cached/manifest.json",
            "artifact_resource_url": "/artifacts/cached/manifest.json",
            "manifest_result_id": "manifest-cached",
            "manifest_result_kind": "file",
            "artifact_title": "Cached Manifest",
            "artifact_mime_type": "application/json",
            "artifact_resource_backend": "local",
            "artifact_resource_size_bytes": 200,
        },
    )
    cached_manifest_ref = _make_result_ref(
        result_id="manifest-cached",
        resource_key="artifacts/cached/manifest.json",
    )

    mock_manifest_writer = MagicMock()
    mock_manifest_writer.build_cached_manifest_result_ref.return_value = cached_manifest_ref

    orchestrator = DownloadOrchestrator(manifest_writer=mock_manifest_writer)
    snapshot = _make_snapshot()

    with patch("app.services.download_orchestrator.cache_service") as mock_cache:
        mock_cache.build_cache_key.return_value = "test-cache-key"
        mock_cache.get_entry.return_value = cached_entry
        mock_cache.upsert_entry.return_value = cached_entry

        plan = orchestrator.prepare_download(
            run_id="test-run-1",
            layer_id="test-layer",
            requested_hour=12.0,
            realtime_preferred=False,
            snapshot=snapshot,
            payload_parameters={},
            requested_at=datetime.now(UTC),
        )

    # Verify cache hit path
    assert plan.execution_status == "cache_hit", 'plan.execution_status == "cache_hit"'
    assert plan.cache_entry == cached_entry, 'plan.cache_entry == cached_entry'
    assert plan.manifest_result_ref == cached_manifest_ref, 'plan.manifest_result_ref == cached_manifest_ref'

    # Verify job_state reflects cache hit
    assert not plan.job_state["requires_fetch"], 'plan.job_state["requires_fetch"] is falsy'
    assert plan.job_state["status"] == "cache_hit", 'plan.job_state["status"] == "cache_hit"'
    assert plan.job_state["phase"] == "fulfilled", 'plan.job_state["phase"] == "fulfilled"'
    assert plan.job_state["cache_hit"], 'plan.job_state["cache_hit"] is truthy'

    # Verify source_fetch_summary
    assert plan.source_fetch_summary["status"] == "cache_reused", 'plan.source_fetch_summary["status"] == "cache_reused"'
    assert plan.source_fetch_summary["pending_sources"] == 0, 'plan.source_fetch_summary["pending_sources"] == 0'

    # build_manifest_result_ref should NOT be called on cache hit
    mock_manifest_writer.build_manifest_result_ref.assert_not_called()


def test_download_orchestrator_prepare_download_cache_miss() -> None:
    """Mock cache_service.get_object to return None → plan requires fetching."""
    fresh_manifest_ref = _make_result_ref(
        result_id="manifest-fresh",
        resource_key="artifacts/test-run-1/manifest.json",
    )

    mock_manifest_writer = MagicMock()
    mock_manifest_writer.build_cached_manifest_result_ref.return_value = None
    mock_manifest_writer.build_manifest_result_ref.return_value = fresh_manifest_ref

    orchestrator = DownloadOrchestrator(manifest_writer=mock_manifest_writer)
    snapshot = _make_snapshot()
    upserted_entry = _make_cache_entry(status="cold")

    with patch("app.services.download_orchestrator.cache_service") as mock_cache:
        mock_cache.build_cache_key.return_value = "test-cache-key"
        mock_cache.get_entry.return_value = None  # cache miss
        mock_cache.upsert_entry.return_value = upserted_entry

        plan = orchestrator.prepare_download(
            run_id="test-run-1",
            layer_id="test-layer",
            requested_hour=12.0,
            realtime_preferred=False,
            snapshot=snapshot,
            payload_parameters={},
            requested_at=datetime.now(UTC),
        )

    # Verify cache miss path
    assert plan.execution_status == "prepared", 'plan.execution_status == "prepared"'
    assert plan.manifest_result_ref == fresh_manifest_ref, 'plan.manifest_result_ref == fresh_manifest_ref'

    # Verify job_state requires fetch
    assert plan.job_state["requires_fetch"], 'plan.job_state["requires_fetch"] is truthy'
    assert plan.job_state["status"] == "awaiting_fetch", 'plan.job_state["status"] == "awaiting_fetch"'
    assert plan.job_state["phase"] == "prepared", 'plan.job_state["phase"] == "prepared"'
    assert not plan.job_state["cache_hit"], 'plan.job_state["cache_hit"] is falsy'

    # Verify source_fetch_summary
    assert plan.source_fetch_summary["status"] == "awaiting_fetch", 'plan.source_fetch_summary["status"] == "awaiting_fetch"'

    # build_manifest_result_ref SHOULD be called on cache miss
    mock_manifest_writer.build_manifest_result_ref.assert_called_once()


def test_download_orchestrator_build_follow_up_task() -> None:
    """Verify build_follow_up_task constructs a proper follow-up task dict."""
    manifest_ref = _make_result_ref(
        result_id="manifest-1",
        resource_key="artifacts/test/manifest.json",
    )
    cache_entry = _make_cache_key_entry()
    plan = DownloadPlan(
        channel="download",
        dataset_key="test-layer",
        requested_hour=12.0,
        refresh_policy="scheduled",
        recommended_cache_ttl_seconds=1800,
        source_mode="realtime",
        target_dataset="Test Layer",
        source_refs=[
            {"ref_id": "ref-1", "source_uri": "http://example.com/data.json"},
        ],
        cache_entry=cache_entry,
        download_ticket_id="download-abc123",
        execution_status="prepared",
        job_state={},
        source_fetch_summary={},
        follow_up_policy={
            "max_attempts": 3,
            "retryable": True,
            "simulate_fail_attempts": 0,
            "partial_failure_ref_ids": [],
        },
        manifest_result_ref=manifest_ref,
    )

    orchestrator = DownloadOrchestrator()

    task = orchestrator.build_follow_up_task(
        run_id="test-run-1",
        plan=plan,
        summary_result_id="summary-1",
    )

    # Verify task dict structure
    assert task["task_type"] == "download_fetch", 'task["task_type"] == "download_fetch"'
    assert task["run_id"] == "test-run-1", 'task["run_id"] == "test-run-1"'
    assert task["download_ticket_id"] == "download-abc123", 'task["download_ticket_id"] == "download-abc123"'
    assert task["cache_key"] == cache_entry.cache_key, 'task["cache_key"] == cache_entry.cache_key'
    assert task["summary_result_id"] == "summary-1", 'task["summary_result_id"] == "summary-1"'
    assert task["manifest_result_id"] == "manifest-1", 'task["manifest_result_id"] == "manifest-1"'
    assert task["artifact_resource_key"] == "artifacts/test/manifest.json", 'task["artifact_resource_key"] == "artifacts/test/manifest.json"'
    assert task["source_refs"] == plan.source_refs, 'task["source_refs"] == plan.source_refs'
    assert task["max_attempts"] == 3, 'task["max_attempts"] == 3'
    assert task["simulate_fail_attempts"] == 0, 'task["simulate_fail_attempts"] == 0'
    assert task["partial_failure_ref_ids"] == [], 'task["partial_failure_ref_ids"] == []'


def _make_cache_key_entry() -> CacheEntry:
    """Create a CacheEntry with a known cache_key for build_follow_up_task tests."""
    return _make_cache_entry(cache_key="test-cache-key-xyz", status="cold")


# ---------------------------------------------------------------------------
# DownloadProgressTracker tests
# ---------------------------------------------------------------------------

def _build_result_refs(
    source_refs: list[dict]
) -> tuple[list[WorkflowResultReference], dict]:
    """Build result_refs list with summary and manifest entries.

    Returns (result_refs, task_data).
    """
    summary_inline = _make_summary_inline_data(source_refs=source_refs)
    summary_ref = _make_result_ref(
        result_id="summary-1",
        result_kind=ResultKind.json,
        title="Download Summary",
        inline_data=summary_inline,
        resource_key=None,
        resource_url=None,
        resource_backend=None,
        resource_size_bytes=None,
    )
    manifest_ref = _make_result_ref(
        result_id="manifest-1",
        result_kind=ResultKind.file,
        title="Download Manifest",
        resource_key="artifacts/test/manifest.json",
    )
    return [summary_ref, manifest_ref], summary_inline


def _setup_tracker(
    fetch_results: list[FetchResult],
    cache_entry: CacheEntry | None = None,
) -> DownloadProgressTracker:
    """Create a DownloadProgressTracker with all dependencies mocked."""
    mock_manifest_writer = MagicMock()
    mock_manifest_writer.replace_manifest_result_ref.return_value = _make_manifest_ref_for_replace()

    tracker = DownloadProgressTracker(manifest_writer=mock_manifest_writer)

    # Patch source_fetcher_registry.fetch with side_effect for sequential calls
    if len(fetch_results) == 1:
        tracker._fetch_side_effect = None
        patcher_fetch = patch(
            "app.services.download_progress_tracker.source_fetcher_registry.fetch",
            return_value=fetch_results[0],
        )
    else:
        patcher_fetch = patch(
            "app.services.download_progress_tracker.source_fetcher_registry.fetch",
            side_effect=fetch_results,
        )

    # Patch cache_service
    if cache_entry is None:
        cache_entry = _make_cache_entry(status="cold")
    patcher_cache = patch(
        "app.services.download_progress_tracker.cache_service",
    )

    mock_cache = patcher_cache.start()
    mock_cache.get_entry.return_value = cache_entry
    mock_cache.upsert_entry.return_value = cache_entry
    patcher_fetch.start()

    return tracker


def test_download_progress_tracker_complete_success() -> None:
    """Mock source_fetcher_registry.fetch to return all-success → 'fetched' status."""
    source_refs = _make_source_refs(count=2)
    result_refs, _ = _build_result_refs(source_refs)
    task_data = _make_task_data(source_refs=source_refs, max_attempts=3)

    fetch_results = [
        FetchResult(
            ref_id="ref-0",
            success=True,
            artifact_key="download-fetch/test-run-1/1/ref-0",
            fetched_bytes=100,
            content_type="application/json",
            fetched_at="2024-01-01T00:00:00+00:00",
        ),
        FetchResult(
            ref_id="ref-1",
            success=True,
            artifact_key="download-fetch/test-run-1/1/ref-1",
            fetched_bytes=200,
            content_type="application/json",
            fetched_at="2024-01-01T00:00:00+00:00",
        ),
    ]

    tracker = _setup_tracker(fetch_results)

    updated_refs, diagnostics, task_report = tracker.complete_follow_up_task(
        run_id="test-run-1",
        result_refs=result_refs,
        task_data=task_data,
        cache_key="test-cache-key",
        summary_result_id="summary-1",
        manifest_result_id="manifest-1",
        updated_at=datetime.now(UTC),
    )

    # Verify execution status
    assert task_report["execution_status"] == "fetched", 'task_report["execution_status"] == "fetched"'
    assert task_report["job_phase"] == "fulfilled", 'task_report["job_phase"] == "fulfilled"'
    assert task_report["fetch_attempts"] == 1, 'task_report["fetch_attempts"] == 1'
    assert task_report["max_attempts"] == 3, 'task_report["max_attempts"] == 3'
    assert task_report["ready_sources"] == 2, 'task_report["ready_sources"] == 2'
    assert task_report["failed_sources"] == 0, 'task_report["failed_sources"] == 0'
    assert not task_report["retry_recommended"], 'task_report["retry_recommended"] is falsy'
    assert not task_report["partial_success"], 'task_report["partial_success"] is falsy'
    assert task_report["source_fetch_status"] == "fetched", 'task_report["source_fetch_status"] == "fetched"'

    # Verify diagnostics
    assert isinstance(diagnostics, list), 'isinstance(diagnostics, list)'
    assert len(diagnostics) > 0, 'len(diagnostics) > 0 is truthy'
    assert any("fetched" in d for d in diagnostics), 'any("fetched" in d for d in diagnostics) is truthy'

    # Verify updated result_refs
    assert len(updated_refs) == 2, 'len(updated_refs) == 2'
    summary_updated = next(r for r in updated_refs if r.result_id == "summary-1")
    assert summary_updated.inline_data is not None, 'summary_updated.inline_data is not None'
    assert summary_updated.inline_data["execution"]["status"] == "fetched", 'summary_updated.inline_data["execution"]["status"] == "fetched"'
    assert summary_updated.inline_data["execution"]["job_state"]["phase"] == "fulfilled", 'summary_updated.inline_data["execution"]["job_state"]["phase"] == "fulfilled"'
    # All source_refs should be ready
    for ref in summary_updated.inline_data["download_plan"]["source_refs"]:
        assert ref["fetch_status"] == "ready", 'ref["fetch_status"] == "ready"'


def test_download_progress_tracker_partial_failure() -> None:
    """Mock fetch to return mixed success/failure → partial completion."""
    source_refs = _make_source_refs(count=2)
    result_refs, _ = _build_result_refs(source_refs)
    task_data = _make_task_data(source_refs=source_refs, max_attempts=3)

    fetch_results = [
        FetchResult(
            ref_id="ref-0",
            success=True,
            artifact_key="download-fetch/test-run-1/1/ref-0",
            fetched_bytes=100,
            content_type="application/json",
            fetched_at="2024-01-01T00:00:00+00:00",
        ),
        FetchResult(
            ref_id="ref-1",
            success=False,
            error="Connection timeout",
            fetched_at="2024-01-01T00:00:00+00:00",
        ),
    ]

    tracker = _setup_tracker(fetch_results)

    updated_refs, diagnostics, task_report = tracker.complete_follow_up_task(
        run_id="test-run-1",
        result_refs=result_refs,
        task_data=task_data,
        cache_key="test-cache-key",
        summary_result_id="summary-1",
        manifest_result_id="manifest-1",
        updated_at=datetime.now(UTC),
    )

    # With max_attempts=3, the failure is transient (retry_pending)
    # → partial_success because some ready and some transient
    assert task_report["ready_sources"] == 1, 'task_report["ready_sources"] == 1'
    assert task_report["retry_recommended"], 'task_report["retry_recommended"] is truthy'
    assert task_report["partial_success"], 'task_report["partial_success"] is truthy'
    assert task_report["source_fetch_status"] == "partial_success", 'task_report["source_fetch_status"] == "partial_success"'

    # Verify source_refs in updated summary
    summary_updated = next(r for r in updated_refs if r.result_id == "summary-1")
    refs = summary_updated.inline_data["download_plan"]["source_refs"]
    assert refs[0]["fetch_status"] == "ready", 'refs[0]["fetch_status"] == "ready"'
    assert refs[1]["fetch_status"] == "retry_pending", 'refs[1]["fetch_status"] == "retry_pending"'


def test_download_progress_tracker_all_failed() -> None:
    """All fetches fail (max_attempts=1 → terminal failure) → job state reflects failure."""
    source_refs = _make_source_refs(count=2)
    result_refs, _ = _build_result_refs(source_refs)
    task_data = _make_task_data(source_refs=source_refs, max_attempts=1)

    fetch_results = [
        FetchResult(
            ref_id="ref-0",
            success=False,
            error="HTTP 500 Internal Server Error",
            fetched_at="2024-01-01T00:00:00+00:00",
        ),
        FetchResult(
            ref_id="ref-1",
            success=False,
            error="Connection refused",
            fetched_at="2024-01-01T00:00:00+00:00",
        ),
    ]

    tracker = _setup_tracker(fetch_results)

    updated_refs, diagnostics, task_report = tracker.complete_follow_up_task(
        run_id="test-run-1",
        result_refs=result_refs,
        task_data=task_data,
        cache_key="test-cache-key",
        summary_result_id="summary-1",
        manifest_result_id="manifest-1",
        updated_at=datetime.now(UTC),
    )

    # With max_attempts=1, attempt_number=1 >= max_attempts → terminal failure
    assert task_report["execution_status"] == "failed", 'task_report["execution_status"] == "failed"'
    assert task_report["job_phase"] == "failed", 'task_report["job_phase"] == "failed"'
    assert task_report["failed_sources"] == 2, 'task_report["failed_sources"] == 2'
    assert task_report["ready_sources"] == 0, 'task_report["ready_sources"] == 0'
    assert not task_report["retry_recommended"], 'task_report["retry_recommended"] is falsy'
    assert task_report["source_fetch_status"] == "failed", 'task_report["source_fetch_status"] == "failed"'
    assert task_report["last_error"] is not None, 'task_report["last_error"] is not None'

    # Verify source_refs are all failed
    summary_updated = next(r for r in updated_refs if r.result_id == "summary-1")
    refs = summary_updated.inline_data["download_plan"]["source_refs"]
    for ref in refs:
        assert ref["fetch_status"] == "failed", 'ref["fetch_status"] == "failed"'
