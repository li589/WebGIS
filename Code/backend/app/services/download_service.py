"""Download service facade.

Historically a ~990-line god class mixing orchestration, progress tracking,
and manifest writing. Split (Phase 2 of the architecture review) into three
focused modules, with this file preserved as a thin facade so existing
imports (``from app.services.download_service import download_service``)
continue to work without touching call sites:

- :mod:`download_orchestrator` — :meth:`prepare_download`,
  :meth:`build_follow_up_task`, :class:`DownloadPlan`, source URI resolution.
- :mod:`download_progress_tracker` — :meth:`complete_follow_up_task`,
  fetch loop, job_state machine, cache refresh.
- :mod:`download_manifest_writer` — manifest result ref construction /
  replacement, manifest payload derivation.
- :mod:`download_utils` — shared ``coerce_int`` / ``coerce_str_list`` /
  ``clone_payload`` helpers.

The facade delegates every public method to the corresponding module
singleton; no behaviour changes. New code should depend on the focused
modules directly rather than this facade.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.download_orchestrator import (
    DownloadOrchestrator,
    DownloadPlan,
    download_orchestrator,
)
from app.services.download_progress_tracker import (
    DownloadProgressTracker,
    download_progress_tracker,
)
from shared.contracts.api_contracts import WorkflowResultReference

# Re-export DownloadPlan so existing `from app.services.download_service
# import DownloadPlan` imports keep working.
__all__ = [
    "DownloadPlan",
    "DownloadService",
    "download_service",
]


class DownloadService:
    """Facade delegating to :class:`DownloadOrchestrator` and
    :class:`DownloadProgressTracker`.

    The manifest writer is injected into both delegates so they share a
    single artifact-storage code path.
    """

    def __init__(
        self,
        *,
        orchestrator: DownloadOrchestrator | None = None,
        progress_tracker: DownloadProgressTracker | None = None,
    ) -> None:
        self._orchestrator = orchestrator or download_orchestrator
        self._progress_tracker = progress_tracker or download_progress_tracker

    # ------------------------------------------------------------------
    # Orchestrator delegates (plan + follow-up task descriptor)
    # ------------------------------------------------------------------

    def prepare_download(
        self,
        *,
        run_id: str,
        layer_id: str,
        requested_hour: float,
        realtime_preferred: bool,
        snapshot,
        payload_parameters: dict[str, Any],
        requested_at: datetime,
    ) -> DownloadPlan:
        return self._orchestrator.prepare_download(
            run_id=run_id,
            layer_id=layer_id,
            requested_hour=requested_hour,
            realtime_preferred=realtime_preferred,
            snapshot=snapshot,
            payload_parameters=payload_parameters,
            requested_at=requested_at,
        )

    def build_follow_up_task(
        self,
        *,
        run_id: str,
        plan: DownloadPlan,
        summary_result_id: str,
    ) -> dict[str, Any]:
        return self._orchestrator.build_follow_up_task(
            run_id=run_id,
            plan=plan,
            summary_result_id=summary_result_id,
        )

    # ------------------------------------------------------------------
    # Progress tracker delegate (follow-up fetch execution)
    # ------------------------------------------------------------------

    def complete_follow_up_task(
        self,
        *,
        run_id: str,
        result_refs: list[WorkflowResultReference],
        task_data: dict[str, Any],
        cache_key: str,
        summary_result_id: str,
        manifest_result_id: str,
        updated_at: datetime,
    ) -> tuple[list[WorkflowResultReference], list[str], dict[str, Any]]:
        return self._progress_tracker.complete_follow_up_task(
            run_id=run_id,
            result_refs=result_refs,
            task_data=task_data,
            cache_key=cache_key,
            summary_result_id=summary_result_id,
            manifest_result_id=manifest_result_id,
            updated_at=updated_at,
        )


# Module-level singleton preserved for backward compatibility with
# ``from app.services.download_service import download_service``.
download_service = DownloadService()
