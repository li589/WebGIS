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


def _asset_state_zh(state: str | None) -> str:
    mapping = {
        "fresh": "已就绪",
        "stale": "版本陈旧",
        "missing": "缺失",
        "unversioned": "无版本元数据",
        "updating": "更新中",
    }
    key = (state or "").strip()
    return mapping.get(key, key or "未知")


def _summarize_bake_tool_output(stdout: str, stderr: str) -> tuple[str | None, list[str]]:
    """从烘焙工具输出提取用户可读原因与短要点（不含整段日志）。"""
    text = f"{stdout or ''}\n{stderr or ''}"
    notes: list[str] = []
    skip_missing = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "[SKIP]" in line and ("File not found" in line or "未找到" in line):
            skip_missing = True
            # 「=== CMFD Precipitation === [SKIP] File not found」
            label = line
            for token in ("===", "[SKIP]", "File not found"):
                label = label.replace(token, " ")
            label = " ".join(label.split()).strip(" -:")
            notes.append(
                f"源数据文件未找到，已跳过烘焙"
                + (f"（{label}）" if label else "")
            )
        elif line.startswith("Summary:") and "FAIL" in line.upper():
            notes.append(f"烘焙汇总：{line[len('Summary:'):].strip()}")
    reason: str | None = None
    if skip_missing:
        reason = "源数据文件缺失，未能生成叠加图资产"
    return reason, notes[:4]


def _format_bake_failure_message(
    *,
    asset_state: dict[str, Any],
    returncode: int,
    stdout: str,
    stderr: str,
    remaining_stale: list[str],
) -> tuple[str, list[str]]:
    """返回 (主消息, UI 诊断要点)。完整日志单独放入 bake_log= 键。"""
    state_key = str(asset_state.get("asset_state") or "unknown")
    state_zh = _asset_state_zh(state_key)
    tool_reason, tool_notes = _summarize_bake_tool_output(stdout, stderr)

    if returncode != 0:
        message = tool_reason or f"图层资产烘焙进程失败（退出码 {returncode}）"
    elif tool_reason:
        message = f"{tool_reason}（当前资产：{state_zh}）"
    elif remaining_stale:
        message = (
            f"烘焙后仍有陈旧任务：{', '.join(remaining_stale[:5])}"
            f"（当前资产：{state_zh}）"
        )
    elif state_key == "missing":
        message = "图层叠加图资产仍缺失，请检查数据源路径与烘焙配置。"
    elif state_key == "stale":
        message = (
            f"图层资产版本仍陈旧"
            f"（bake_version={asset_state.get('bake_version')}，"
            f"需要≥{asset_state.get('current_bake_version')}）。"
        )
    elif state_key == "unversioned":
        message = "叠加图存在但缺少 bake_version 元数据，请重新烘焙。"
    else:
        message = f"图层资产未就绪（当前状态：{state_zh}）。"

    diagnostics: list[str] = [
        f"asset_state={state_key}",
        f"reason={message}",
        *tool_notes,
    ]
    if remaining_stale:
        diagnostics.append(f"remaining_stale={remaining_stale}")
    if returncode != 0:
        diagnostics.append(f"returncode={returncode}")
    # 完整工具输出仅作排障附件，前端默认折叠/过滤
    log_tail = ((stdout or "") + ("\n" + stderr if stderr else ""))[-1200:].strip()
    if log_tail:
        diagnostics.append(f"bake_log={log_tail}")
    return message, diagnostics


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

    def get_asset_state(self, layer_id: str) -> dict[str, Any]:
        """公开资产状态查询（图层平台子系统：GET /layer-assets/{layer_id}）。

        Raises:
            ValueError: 图层未注册（404 语义）。
        """
        from app.services.overlay_registry import get_overlay_spec

        if get_overlay_spec(layer_id) is None:
            raise ValueError(f"Unknown overlay layer: {layer_id}")
        return _read_asset_state(layer_id)

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
                workflow_kind="asset_bake",
                layer_id=layer_id,
                progress=100,
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
        # 图层平台子系统 v5：走 layer_id 索引查询，替代全表 list_runs() 内存过滤。
        for existing in self._repository.list_runs_by_layer(
            layer_id, limit=10, workflow_kind="asset_bake"
        ):
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
            workflow_kind="asset_bake",
            layer_id=layer_id,
            progress=5,
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
            # 无烘焙任务的图层（如柯本/土壤容重/SHDI 等科研参考层，
            # 资产由数据导入流程管理）：PNG/bounds 文件存在即按现状显示，
            # 不算运行失败——否则用户看到「图层正常显示却报运行失败」
            # （2026-08-25 反馈）。仅资产文件缺失时才真正失败。
            state = _read_asset_state(layer_id)
            if state.get("png_exists") and state.get("bounds_exists"):
                message = f"图层 {layer_id} 无自动烘焙任务，现有资产按现状显示。"
                ok_run = _status_payload(
                    run_id=run_id,
                    layer_id=layer_id,
                    status=ExecutionStatus.succeeded,
                    progress=100,
                    message=message,
                    created_at=run.created_at,
                    updated_at=_utc_now(),
                    asset_state=state,
                )
                self._repository.save_run(
                    ok_run,
                    run_class="asset",
                    workflow_kind="asset_bake",
                    layer_id=layer_id,
                    progress=100,
                )
                return {"status": "succeeded", "run_id": run_id}
            message = f"图层 {layer_id} 未配置资产烘焙任务且资产文件缺失。"
            failed = _status_payload(
                run_id=run_id,
                layer_id=layer_id,
                status=ExecutionStatus.failed,
                progress=100,
                message=message,
                created_at=run.created_at,
                updated_at=_utc_now(),
                asset_state=state,
            )
            self._repository.save_run(
                failed,
                run_class="asset",
                workflow_kind="asset_bake",
                layer_id=layer_id,
                progress=100,
            )
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
            workflow_kind="asset_bake",
            layer_id=layer_id,
            progress=25,
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
            self._repository.save_run(
                failed,
                run_class="asset",
                workflow_kind="asset_bake",
                layer_id=layer_id,
                progress=100,
            )
            return {"status": "failed", "run_id": run_id, "error": str(exc)}

        completed = _utc_now()
        state = _read_asset_state(layer_id)
        stale = sorted(_find_stale_bake_tasks())
        ok = result.returncode == 0 and state["asset_state"] == "fresh"
        if ok:
            message = f"图层资产已更新（bake_version={state['bake_version']}）。"
            diagnostics = [
                f"asset_state={state['asset_state']}",
                f"bake_version={state['bake_version']}",
            ]
        else:
            message, diagnostics = _format_bake_failure_message(
                asset_state=state,
                returncode=int(result.returncode),
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                remaining_stale=list(stale),
            )
        final_status = ExecutionStatus.succeeded if ok else ExecutionStatus.failed
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
            workflow_kind="asset_bake",
            layer_id=layer_id,
            progress=100 if ok else 92,
        )
        return {"status": final_status.value, "run_id": run_id, "asset_state": state}


overlay_asset_workflow_service = OverlayAssetWorkflowService()
