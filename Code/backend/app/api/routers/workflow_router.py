import os
from datetime import datetime, timedelta, UTC
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.deps import require_write_access
from app.services.result_view_service import result_view_service
from app.services.workflow.service_container import (
    lifecycle_service,
    retry_dispatcher,
    submission_service,
)
from app.services.workflow.submission_service import WorkflowValidationError
from shared.contracts.api_contracts import (
    WorkflowAcceptedResponse,
    WorkflowEventsResponse,
    WorkflowRunStatusResponse,
    WorkflowRunViewResponse,
    WorkflowSubmitRequest,
)

router = APIRouter()

# JSON 事件轮询限流：按「每 IP / 每分钟请求数」（非 SSE 连接数）
_EVENTS_POLL_RATE_LIMIT = int(
    os.getenv("BACKEND_EVENTS_POLL_RATE_LIMIT_PER_MINUTE", "120")
)
_EVENTS_POLL_WINDOW = timedelta(minutes=1)


class EventsPollRateLimiter:
    def __init__(self, limit: int, window: timedelta) -> None:
        self._limit = limit
        self._window = window
        self._lock = Lock()
        self._requests: dict[str, list[datetime]] = {}

    def check(self, ip: str) -> bool:
        now = datetime.now(UTC)
        cutoff = now - self._window
        with self._lock:
            timestamps = self._requests.pop(ip, None)
            if timestamps is None:
                timestamps = []
            timestamps[:] = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self._limit:
                return False
            timestamps.append(now)
            self._requests[ip] = timestamps
            return True


_events_poll_limiter = EventsPollRateLimiter(
    _EVENTS_POLL_RATE_LIMIT, _EVENTS_POLL_WINDOW
)


def _get_client_ip(request: Request) -> str:
    """Reuse write-limiter IP policy (honor BACKEND_TRUST_PROXY only)."""
    from app.api.rate_limit import client_ip

    return client_ip(request)


@router.post(
    "/workflow-runs",
    tags=["workflow"],
    response_model=WorkflowAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_write_access)],
)
def submit_workflow(payload: WorkflowSubmitRequest) -> WorkflowAcceptedResponse:
    try:
        accepted = submission_service.submit_workflow(payload)
        return accepted
    except WorkflowValidationError as exc:
        # 提交期参数预校验失败：返回 422 + 结构化字段级错误，
        # 供前端定位具体表单字段。必须在 ValueError 之前捕获
        # （WorkflowValidationError 继承 ValueError）。
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_type": "validation",
                "user_message": "请求参数未通过业务校验，请检查表单字段。",
                "issues": exc.issues,
            },
        ) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if "capacity" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception:
        raise


@router.get(
    "/workflow-runs", tags=["workflow"], response_model=list[WorkflowRunStatusResponse]
)
def list_workflow_runs(
    active_only: bool = True,
    status: str | None = Query(
        default=None, description="按状态过滤，如 succeeded / failed / cancelled"
    ),
    limit: int | None = Query(
        default=None, ge=1, le=200, description="取最近 N 条（按创建时间倒序）"
    ),
) -> list[WorkflowRunStatusResponse]:
    """列出工作流 run。active_only=true（默认）仅返回非终态 run。

    可选 status 过滤与 limit 取最近 N 条（按创建时间倒序），
    供前端启动恢复（含"最近成功 run 产物自动恢复"）与跨会话状态同步使用。
    """
    from app.services.workflow_repository import SQLiteWorkflowRepository
    from shared.contracts.api_contracts import ExecutionStatus

    repo = SQLiteWorkflowRepository()
    all_runs = repo.list_runs()
    if status is not None:
        all_runs = [r for r in all_runs if r.status.value == status]
    if not active_only:
        if limit is not None:
            all_runs = sorted(all_runs, key=lambda r: r.created_at, reverse=True)[
                :limit
            ]
        return all_runs
    active_statuses = {
        ExecutionStatus.accepted,
        ExecutionStatus.queued,
        ExecutionStatus.running,
    }
    active = [r for r in all_runs if r.status in active_statuses]
    if limit is not None:
        active = sorted(active, key=lambda r: r.created_at, reverse=True)[:limit]
    return active


@router.get(
    "/workflow-runs/{run_id}",
    tags=["workflow"],
    response_model=WorkflowRunStatusResponse,
)
def get_workflow_run(run_id: str) -> WorkflowRunStatusResponse:
    run_status = submission_service.get_workflow_run(run_id)
    if run_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
    return run_status


@router.get(
    "/workflow-runs/{run_id}/view",
    tags=["workflow"],
    response_model=WorkflowRunViewResponse,
)
def get_workflow_run_view(run_id: str) -> WorkflowRunViewResponse:
    run_view = result_view_service.get_workflow_run_view(run_id)
    if run_view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
    return run_view


@router.get(
    "/workflow-runs/{run_id}/events",
    tags=["workflow"],
    response_model=WorkflowEventsResponse,
)
def list_workflow_events(
    request: Request,
    run_id: str,
    after_event_id: str | None = None,
    limit: int | None = None,
) -> WorkflowEventsResponse:
    client_ip = _get_client_ip(request)
    if not _events_poll_limiter.check(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many workflow event poll requests from {client_ip}. "
                f"Limit: {_EVENTS_POLL_RATE_LIMIT} per minute."
            ),
        )
    events = submission_service.list_workflow_events(
        run_id, after_event_id=after_event_id, limit=limit
    )
    if events is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
    return events


@router.post(
    "/workflow-runs/{run_id}/cancel",
    tags=["workflow"],
    response_model=WorkflowRunStatusResponse,
    dependencies=[Depends(require_write_access)],
)
def cancel_workflow_run(run_id: str) -> WorkflowRunStatusResponse:
    try:
        return lifecycle_service.cancel_workflow_run(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post(
    "/workflow-runs/{run_id}/retry",
    tags=["workflow"],
    response_model=WorkflowAcceptedResponse,
    dependencies=[Depends(require_write_access)],
)
def retry_workflow_run(run_id: str) -> WorkflowAcceptedResponse:
    try:
        return retry_dispatcher.retry_workflow_run(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post(
    "/workflow-runs/{run_id}/materialize-map-layers",
    tags=["workflow"],
    dependencies=[Depends(require_write_access)],
)
def materialize_workflow_map_layers(run_id: str) -> dict:
    """Publish algorithm science products as imported overlays for map display.

    Used when a run completed with file-only product refs (no map_layer), or to
    re-publish after code updates without re-running the inversion.
    Also allowed while ``running`` so block mats can progressively appear.
    """
    from datetime import datetime
    from pathlib import Path

    from app.core.config import settings
    from app.data_io.services.raster_timeseries import upsert_block_dir_timeseries
    from app.services.python_provider_result_builder import (
        python_provider_result_builder,
    )
    from shared.contracts.api_contracts import WorkflowSubmitRequest

    run_status = submission_service.get_workflow_run(run_id)
    if run_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
    if run_status.status not in {"succeeded", "running", "accepted", "queued"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workflow run cannot materialize overlays: {run_status.status}",
        )

    result_dto: dict = {}
    if run_status.result_dto is not None:
        raw = run_status.result_dto
        result_dto = (
            raw.model_dump(mode="json") if hasattr(raw, "model_dump") else dict(raw)
        )

    if not result_dto.get("products"):
        for ref in run_status.result_refs or []:
            if ref.result_kind.value != "json":
                continue
            inline = ref.inline_data or {}
            nested = inline.get("result_dto")
            if isinstance(nested, dict) and nested.get("products"):
                result_dto = nested
                break

    layers: list[dict] = []
    time_start: str | None = None
    time_end: str | None = None
    tr = run_status.time_range
    if tr is not None:
        start_at = getattr(tr, "start_at", None) or (
            tr.get("start_at") if isinstance(tr, dict) else None
        )
        end_at = getattr(tr, "end_at", None) or (
            tr.get("end_at") if isinstance(tr, dict) else None
        )
        if start_at is not None:
            time_start = str(start_at).replace("-", "")[:8]
        if end_at is not None:
            time_end = str(end_at).replace("-", "")[:8]

    # Prefer explicit products when present
    if result_dto.get("products"):
        payload = WorkflowSubmitRequest(
            command_type=run_status.command_type,
            command_label=f"materialize map layers {run_id}",
            layer_id=run_status.layer_id,
            requested_outputs=["map_layer"],
        )
        refs = python_provider_result_builder._build_product_map_layer_refs(
            run_id=run_id,
            requested_at=datetime.now(UTC),
            payload=payload,
            result_dto=result_dto,
            time_start=time_start,
            time_end=time_end,
            canonical_viirs8_only=(
                run_status.status == "succeeded"
                and "omega-sf-fenkuai" in str(run_status.layer_id or "")
            ),
        )
        for ref in refs:
            assets = (ref.inline_data or {}).get("layer_assets") or {}
            overlay_id = assets.get("overlay_layer_id")
            if not overlay_id:
                continue
            bbox = assets.get("cog_bbox") or {}
            layers.append(
                {
                    "overlay_layer_id": overlay_id,
                    "title": ref.title,
                    "product_tag": assets.get("product_tag"),
                    "bounds": [
                        bbox.get("west"),
                        bbox.get("south"),
                        bbox.get("east"),
                        bbox.get("north"),
                    ]
                    if isinstance(bbox, dict) and bbox.get("west") is not None
                    else None,
                    "source_crs": bbox.get("crs") if isinstance(bbox, dict) else None,
                    "cog_preview_url": assets.get("cog_preview_url"),
                    "time_list": assets.get("time_list") or [],
                    "default_time": assets.get("default_time"),
                    "native_step": assets.get("native_step"),
                }
            )

    # Running / partial: sync block dir on disk even without result_dto products
    if not layers or run_status.status == "running":
        candidates: list[Path] = []
        for product in result_dto.get("products") or []:
            if not isinstance(product, dict):
                continue
            if "block" not in str(product.get("type") or "").lower():
                continue
            uri = str(product.get("uri") or product.get("download_url") or "").strip()
            if uri:
                candidates.append(
                    Path(uri.replace("file:///", "").replace("file://", ""))
                )
        data_root = Path(getattr(settings, "data_root", "") or "")
        workspace = Path(getattr(settings, "python_provider_workspace", "") or "")
        runtime_candidates: list[Path] = []
        if workspace.parts:
            runtime_candidates.append(workspace / "products" / "omega_sf_fenkuai")
        if data_root.parts:
            runtime_candidates.append(
                data_root
                / "_runtime"
                / "python_provider"
                / "products"
                / "omega_sf_fenkuai"
            )
        for path in [*candidates, *runtime_candidates]:
            if path.is_dir() and any(path.glob("????????_????????.mat")):
                for variable, label, palette in (
                    ("SM", "SM", "ylgnbu"),
                    ("VOD", "VOD", "viridis"),
                    ("OMEGA", "OMEGA", "cividis"),
                ):
                    try:
                        synced = upsert_block_dir_timeseries(
                            path,
                            variable_id=variable,
                            label=label,
                            run_id=run_id,
                            palette=palette,
                            native_step="8d",
                            time_start=time_start,
                            time_end=time_end,
                            canonical_viirs8_only=(
                                run_status.status == "succeeded"
                                and "omega-sf-fenkuai" in str(run_status.layer_id or "")
                            ),
                        )
                    except Exception:
                        continue
                    # de-dupe by overlay id
                    if any(
                        layer.get("overlay_layer_id") == synced["layer_id"]
                        for layer in layers
                    ):
                        for layer in layers:
                            if layer.get("overlay_layer_id") == synced["layer_id"]:
                                layer["time_list"] = synced.get("time_list") or []
                                layer["default_time"] = synced.get("default_time")
                        continue
                    layers.append(
                        {
                            "overlay_layer_id": synced["layer_id"],
                            "title": synced.get("title"),
                            "product_tag": synced.get("product_tag"),
                            "bounds": synced.get("bounds"),
                            "source_crs": synced.get("source_crs"),
                            "cog_preview_url": synced.get("cog_preview_url"),
                            "time_list": synced.get("time_list") or [],
                            "default_time": synced.get("default_time"),
                            "native_step": synced.get("native_step"),
                        }
                    )
                break

    return {"run_id": run_id, "layers": layers, "count": len(layers)}
