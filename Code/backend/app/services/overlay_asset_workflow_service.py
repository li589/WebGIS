"""Overlay asset workflow service.

Unifies map layer assets under the workflow run model:

1. Every overlay add can submit an ``asset_bake`` workflow run.
2. The run first checks baked PNG/bounds metadata and ``bake_version``.
3. Fresh assets complete immediately; stale assets dispatch the existing
   Celery rebake task, then poll for the versioned asset becoming available.
4. The run's ``result_dto`` carries asset state/time information so the UI can
   show queued/running/updating/fresh and synchronize time blocks.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from shared.contracts.api_contracts import (
    ExecutionStatus,
    WorkflowAcceptedResponse,
    WorkflowCommandType,
    WorkflowRunStatusResponse,
)

from app.services.overlay_registry import get_overlay_spec
from app.services.workflow_repository import SQLiteWorkflowRepository

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BAKE_TOOL = _REPO_ROOT / "Tools" / "export_overlay_assets.py"

_ASSET_WORKFLOW_COMMAND_LABEL = "图层资产工作流"
_POLL_SECONDS = 2.0
_TIMEOUT_SECONDS = 3600


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _current_bake_version() -> int:
    from app.tasks.asset_bake_tasks import CURRENT_BAKE_VERSION

    return CURRENT_BAKE_VERSION


def _layer_to_task() -> dict[str, str]:
    from app.tasks.asset_bake_tasks import _LAYER_TO_TASK

    return _LAYER_TO_TASK


def _find_stale_bake_tasks() -> set[str]:
    from app.tasks.asset_bake_tasks import find_stale_bake_tasks

    return find_stale_bake_tasks()


def _read_asset_state(layer_id: str) -> dict[str, Any]:
    """Read current baked asset state for one overlay layer."""
    spec = get_overlay_spec(layer_id)
    if spec is None:
        raise ValueError(f"Unknown overlay layer: {layer_id}")

    png_path = spec.resolve_png(None)
    bounds_path = spec.resolve_bounds(None)
    state: dict[str, Any] = {
        "layer_id": layer_id,
        "asset_state": "missing",
        "bake_version": None,
        "current_bake_version": _current_bake_version(),
        "png_exists": png_path.exists(),
        "bounds_exists": bounds_path.exists(),
        "png_mtime": None,
        "bounds_mtime": None,
        "default_time": spec.default_time,
        "time_list": list(spec.time_list),
        "category": spec.category,
    }

    if bounds_path.exists():
        stat = bounds_path.stat()
        state["bounds_mtime"] = stat.st_mtime
        try:
            payload = json.loads(bounds_path.read_text(encoding="utf-8"))
            version = payload.get("bake_version")
            state["bake_version"] = version if isinstance(version, int) else None
        except (OSError, json.JSONDecodeError):
            state["bake_version"] = None

    if png_path.exists():
        state["png_mtime"] = png_path.stat().st_mtime

    if state["png_exists"] and state["bounds_exists"]:
        version = state["bake_version"]
        state["asset_state"] = (
            "fresh"
            if isinstance(version, int) and version >= _current_bake_version()
            else "stale"
        )
    elif state["png_exists"]:
        state["asset_state"] = "unversioned"

    return state


def _new_run_id(layer_id: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in layer_id.lower())[:24]
    return f"asset-bake-{safe}-{uuid.uuid4().hex[:8]}"


def _status_payload(
    *,
    run_id: str,
    layer_id: str,
    status: ExecutionStatus,
    progress: int,
    message: str,
    created_at: datetime,
    updated_at: datetime,
    asset_state: dict[str, Any],
    diagnostics: list[str] | None = None,
) -> WorkflowRunStatusResponse:
    result_dto = {
        "result_category": "asset_bake",
        "layer_id": layer_id,
        "workflow_entry_name": _ASSET_WORKFLOW_COMMAND_LABEL,
        "summary": message,
        "status_label": status.value,
        "data_state_mode": asset_state.get("asset_state"),
        "metadata": {
            "asset": asset_state,
            "updated_at": _iso(updated_at),
        },
    }
    return WorkflowRunStatusResponse(
        run_id=run_id,
        status_url=f"/workflow-runs/{run_id}",
        events_url=f"/workflow-runs/{run_id}/events",
        command_type=WorkflowCommandType.custom,
        command_label=_ASSET_WORKFLOW_COMMAND_LABEL,
        layer_id=layer_id,
        status=status,
        progress=max(0, min(100, int(progress))),
        message=message,
        created_at=created_at,
        updated_at=updated_at,
        result_dto=result_dto,
        diagnostics=diagnostics or [],
        executor_metadata={
            "workflow_kind": "asset_bake",
            "asset_task": _layer_to_task().get(layer_id),
        },
    )


class OverlayAssetWorkflowService:
    """Creates and executes asset-check/bake runs for overlay layers."""

    def __init__(self, repository: SQLiteWorkflowRepository | None = None) -> None:
        self._repository = repository or SQLiteWorkflowRepository()

    def create_or_reuse_run(
        self,
        layer_id: str,
        *,
        user_id: int | None = None,
        role: str | None = None,
        force_rebake: bool = False,
    ) -> WorkflowAcceptedResponse:
        """Create an asset workflow run, or return a recent successful/fresh run.

        The returned object is the standard workflow accepted contract so the
        existing frontend runner can poll/cancel/restore it like any other run.
        """
        state = _read_asset_state(layer_id)
        run_id = _new_run_id(layer_id)
        now = _utc_now()
        request_json = json.dumps(
            {
                "workflow_kind": "asset_bake",
                "layer_id": layer_id,
                "force_rebake": force_rebake,
                "requested_bake_version": _current_bake_version(),
            },
            ensure_ascii=False,
        )
        if state["asset_state"] == "fresh" and not force_rebake:
            status = _status_payload(
                run_id=run_id,
                layer_id=layer_id,
                status=ExecutionStatus.succeeded,
                progress=100,
                message=f"图层资产已就绪（bake_version={state['bake_version']}）。",
                created_at=now,
                updated_at=now,
                asset_state=state,
            )
            self._repository.save_run(
                status,
                request_json=request_json,
                run_class="asset",
                user_id=user_id,
            )
            return WorkflowAcceptedResponse(
                run_id=run_id,
                status=ExecutionStatus.succeeded,
                status_url=f"/workflow-runs/{run_id}",
                events_url=f"/workflow-runs/{run_id}/events",
                created_at=now,
                message="图层资产已就绪。",
            )

        # Reuse an active run for the same layer/task to avoid duplicate bakes.
        for existing in self._repository.list_runs():
            if existing.layer_id != layer_id:
                continue
            if existing.command_label != _ASSET_WORKFLOW_COMMAND_LABEL:
                continue
            if existing.status in {
                ExecutionStatus.accepted,
                ExecutionStatus.queued,
                ExecutionStatus.running,
                ExecutionStatus.retry_pending,
            }:
                return WorkflowAcceptedResponse(
                    run_id=existing.run_id,
                    status=existing.status,
                    status_url=existing.status_url or f"/workflow-runs/{existing.run_id}",
                    events_url=existing.events_url
                    or f"/workflow-runs/{existing.run_id}/events",
                    created_at=existing.created_at,
                    message="相同图层资产更新已在执行中。",
                )

        status = _status_payload(
            run_id=run_id,
            layer_id=layer_id,
            status=ExecutionStatus.accepted,
            progress=5,
            message=(
                "图层资产陈旧，开始检查并重新烘焙。"
                if state["asset_state"] != "missing"
                else "图层资产缺失，开始烘焙。"
            ),
            created_at=now,
            updated_at=now,
            asset_state=state,
            diagnostics=[
                f"asset_state={state['asset_state']}",
                f"role={role or 'anonymous'}",
                f"force_rebake={force_rebake}",
            ],
        )
        self._repository.save_run(
            status,
            request_json=request_json,
            run_class="asset",
            user_id=user_id,
        )
        return WorkflowAcceptedResponse(
            run_id=run_id,
            status=ExecutionStatus.accepted,
            status_url=f"/workflow-runs/{run_id}",
            events_url=f"/workflow-runs/{run_id}/events",
            created_at=now,
            message="图层资产工作流已创建。",
        )

    def get_run(self, run_id: str) -> WorkflowRunStatusResponse | None:
        return self._repository.get_run(run_id)

    def run_asset_workflow(self, run_id: str) -> dict[str, Any]:
        """Execute the bake for an accepted asset run.

        Runs synchronously inside the Celery worker task; the API only creates
        the accepted run. Uses the existing bake tool as the single geometry
        source and then re-scans stale tasks so version drift cannot be hidden.
        """
        run = self._repository.get_run(run_id)
        if run is None:
            raise ValueError(f"Asset workflow run not found: {run_id}")
        if run.status in {
            ExecutionStatus.succeeded,
            ExecutionStatus.failed,
            ExecutionStatus.cancelled,
        }:
            return {"status": run.status.value, "run_id": run_id}

        layer_id = str(run.layer_id or "")
        task_key = _layer_to_task().get(layer_id)
        if not task_key:
            message = f"图层 {layer_id} 未配置资产烘焙任务。"
            failed = _status_payload(
                run_id=run_id,
                layer_id=layer_id,
                status=ExecutionStatus.failed,
                progress=100,
                message=message,
                created_at=run.created_at,
                updated_at=_utc_now(),
                asset_state=_read_asset_state(layer_id),
            )
            self._repository.save_run(failed, run_class="asset")
            return {"status": "failed", "run_id": run_id, "error": message}

        started = _utc_now()
        self._repository.save_run(
            _status_payload(
                run_id=run_id,
                layer_id=layer_id,
                status=ExecutionStatus.running,
                progress=25,
                message=f"开始烘焙图层资产（task={task_key}）。",
                created_at=run.created_at,
                updated_at=started,
                asset_state=_read_asset_state(layer_id),
            ),
            run_class="asset",
        )

        cmd = [sys.executable, str(_BAKE_TOOL), "--tasks", task_key]
        try:
            result = subprocess.run(  # noqa: S603 - fixed repo tool and task key
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_TIMEOUT_SECONDS,
                cwd=str(_REPO_ROOT),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            failed = _status_payload(
                run_id=run_id,
                layer_id=layer_id,
                status=ExecutionStatus.failed,
                progress=100,
                message=f"图层资产烘焙失败：{exc}",
                created_at=run.created_at,
                updated_at=_utc_now(),
                asset_state=_read_asset_state(layer_id),
                diagnostics=[str(exc)],
            )
            self._repository.save_run(failed, run_class="asset")
            return {"status": "failed", "run_id": run_id, "error": str(exc)}

        completed = _utc_now()
        state = _read_asset_state(layer_id)
        stale = sorted(_find_stale_bake_tasks())
        ok = result.returncode == 0 and state["asset_state"] == "fresh"
        message = (
            f"图层资产已更新（bake_version={state['bake_version']}）。"
            if ok
            else "图层资产烘焙未完成或仍被标记为陈旧。"
        )
        final_status = ExecutionStatus.succeeded if ok else ExecutionStatus.failed
        diagnostics = [
            f"returncode={result.returncode}",
            f"remaining_stale={stale}",
            (result.stdout or "")[-1200:],
            (result.stderr or "")[-1200:],
        ]
        self._repository.save_run(
            _status_payload(
                run_id=run_id,
                layer_id=layer_id,
                status=final_status,
                progress=100 if ok else 92,
                message=message,
                created_at=run.created_at,
                updated_at=completed,
                asset_state=state,
                diagnostics=diagnostics,
            ),
            run_class="asset",
        )
        return {"status": final_status.value, "run_id": run_id, "asset_state": state}


overlay_asset_workflow_service = OverlayAssetWorkflowService()
