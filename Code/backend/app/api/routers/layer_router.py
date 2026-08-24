from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
    TimeoutError as FuturesTimeoutError,
)
import logging
import time
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import check_resource_access, get_request_user
from app.core.config import settings
from app.api.error_codes import AUTH_ERROR, ApiError
from app.services.crs import crs_transformer
from app.services.crs.crs_registry import normalize_crs_code
from app.services.layer_catalog import (
    get_layer_catalog,
    get_layer_category_response,
    get_layer_descriptor,
)
from app.services.overlay_registry import (
    get_overlay_spec,
    list_overlay_ids,
    read_bounds,
)
from app.services.workflow_request_resolver import describe_layer_run_readiness
from shared.contracts.api_contracts import (
    LayerAssetStateResponse,
    LayerCatalogResponse,
    LayerCategoryResponse,
    LayerLifecycleResponse,
    LayerLifecycleRunSummary,
    LayerOnlineSyncRequest,
    LayerOnlineSyncResponse,
    WorkflowTemplateListResponse,
    WorkflowTemplateRunRequest,
    WorkflowTemplateRunResponse,
    WorkflowTemplateSummary,
)

_logger = logging.getLogger(__name__)

router = APIRouter()

_READINESS_TIMEOUT = 8.0  # 单图层就绪检查最大耗时（秒）

# G1-06: 模块级共享 executor + 就绪结果短缓存，避免每请求新建线程池
_readiness_executor = ThreadPoolExecutor(max_workers=8)
_READINESS_CACHE_TTL = 30.0  # 秒
_readiness_cache: dict[str, tuple[dict, float]] = {}
_readiness_cache_lock = Lock()


def _filter_accessible_layer_ids(layer_ids: list[str], cred: Any) -> list[str]:
    """Apply resource ACL to overlay/layer id lists (fail-closed when auth on)."""
    _cred = cred if hasattr(cred, "role") else None
    if _cred is None:
        if settings.user_auth_enabled:
            raise ApiError(
                AUTH_ERROR,
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        return list(layer_ids)
    if _cred.role == "admin":
        return list(layer_ids)
    if _cred.user_id is None:
        if getattr(_cred, "source", None) in {"service_key", "dev_bypass"}:
            return list(layer_ids)
        return []
    from app.services.permission_repository import get_permission_repository

    return get_permission_repository().batch_filter_accessible(
        int(_cred.user_id), "layer", layer_ids
    )


def _catalog_items_for_environment(items: list[Any]) -> list[Any]:
    """非 development/test 隐藏 status=placeholder（实验室占位层，机构包可剔除）。"""
    env = (settings.environment or "").strip().lower()
    if env in {"development", "dev", "test", "testing"}:
        return list(items)
    return [item for item in items if getattr(item, "status", None) != "placeholder"]


@router.get("/layers", tags=["catalog"], response_model=LayerCatalogResponse)
def list_layers(cred=Depends(get_request_user)) -> LayerCatalogResponse:
    catalog = get_layer_catalog()
    visible_items = _catalog_items_for_environment(catalog.items)

    # Phase B: 资源访问控制——鉴权开启时匿名 fail-closed；非 admin 按 ACL 过滤
    accessible_ids = set(
        _filter_accessible_layer_ids([desc.layer_id for desc in visible_items], cred)
    )
    visible_items = [d for d in visible_items if d.layer_id in accessible_ids]

    def _check_readiness(item) -> tuple[str, dict]:
        readiness = describe_layer_run_readiness(item.layer_id) or {}
        return item.layer_id, readiness

    layer_readiness: dict[str, dict[str, Any]] = {}
    now = time.time()

    # G1-06: 先查缓存，只对未命中/过期的图层执行就绪检查
    items_to_check = []
    for desc in visible_items:
        cached = _readiness_cache.get(desc.layer_id)
        if cached and now - cached[1] < _READINESS_CACHE_TTL:
            layer_readiness[desc.layer_id] = cached[0]
        else:
            items_to_check.append(desc)

    if items_to_check:
        futures = {
            _readiness_executor.submit(_check_readiness, desc): desc
            for desc in items_to_check
        }
        try:
            for future in as_completed(futures, timeout=_READINESS_TIMEOUT):
                try:
                    layer_id, readiness = future.result(timeout=_READINESS_TIMEOUT)
                    layer_readiness[layer_id] = readiness
                    with _readiness_cache_lock:
                        _readiness_cache[layer_id] = (readiness, time.time())
                except FuturesTimeoutError:
                    _logger.warning("Layer readiness check timed out")
                except Exception:
                    _logger.warning("Layer readiness check failed", exc_info=True)
        except FuturesTimeoutError:
            # as_completed 整体超时：未完成的 future 直接跳过
            _logger.warning(
                "Layer readiness batch timed out after %.1fs", _READINESS_TIMEOUT
            )

    items = []
    for descriptor in visible_items:
        readiness = layer_readiness.get(descriptor.layer_id, {})
        items.append(
            descriptor.model_copy(
                update={
                    "run_readiness": readiness.get(
                        "run_readiness", descriptor.run_readiness
                    ),
                    "run_readiness_summary": readiness.get(
                        "run_readiness_summary", descriptor.run_readiness_summary
                    ),
                    "run_readiness_notes": readiness.get(
                        "run_readiness_notes", descriptor.run_readiness_notes
                    ),
                }
            )
        )
    return LayerCatalogResponse(items=items)


@router.get(
    "/layers/categories", tags=["catalog"], response_model=LayerCategoryResponse
)
def list_layer_categories() -> LayerCategoryResponse:
    """X1: 后端下发图层分类定义（id / name / icon / accent_color / chip_tone）。

    前端运行时消费此端点获取分类样式，消除前后端分类定义双写。
    前端 ``LAYER_CATEGORIES`` 静态表仅在 API 不可用时作离线兜底。
    """
    return get_layer_category_response()


# ── 图层平台子系统 P0：资产状态与生命周期聚合接口（2026-08-24） ───────────────


def _layer_asset_state_response(layer_id: str, state: dict[str, Any]) -> LayerAssetStateResponse:
    from app.services.overlay_asset_workflow_service import _layer_to_task

    return LayerAssetStateResponse(
        layer_id=layer_id,
        asset_state=str(state.get("asset_state") or "missing"),
        bake_version=state.get("bake_version"),
        current_bake_version=int(state.get("current_bake_version") or 0),
        png_exists=bool(state.get("png_exists")),
        bounds_exists=bool(state.get("bounds_exists")),
        category=str(state.get("category") or "static"),
        time_list=[str(t) for t in (state.get("time_list") or [])],
        default_time=state.get("default_time"),
        asset_task=_layer_to_task().get(layer_id),
    )


def _compute_lifecycle_state(
    asset_state: str, recent_runs: list[Any]
) -> tuple[str, str | None]:
    """由资产状态 + 最近 run 推导统一生命周期状态与提示文案。"""
    active_statuses = {"accepted", "queued", "running", "retry_pending"}
    if any(r.status in active_statuses for r in recent_runs):
        return "updating", "图层资产正在检查或更新。"
    if asset_state == "fresh":
        return "fresh", "图层资产已就绪。"
    if asset_state == "stale":
        return "stale", "图层资产陈旧，可触发重新烘焙。"
    if asset_state == "missing":
        return "missing", "图层资产缺失，需要烘焙后显示。"
    if any(r.status == "failed" for r in recent_runs[:3]):
        return "failed", "最近一次资产/工作流运行失败。"
    return asset_state, None


@router.get(
    "/layer-assets/{layer_id}", tags=["layer-platform"], response_model=LayerAssetStateResponse
)
def get_layer_asset_state(
    layer_id: str,
    cred=Depends(get_request_user),
) -> LayerAssetStateResponse:
    """图层烘焙资产状态查询（图层平台子系统 P0）。

    返回 asset_state（missing/unversioned/stale/fresh）、bake_version、
    时间轴元数据与可用烘焙任务 key。前端 lifecycle 域以本接口为真源。
    """
    check_resource_access(cred, "layer", layer_id)
    from app.services.overlay_asset_workflow_service import (
        overlay_asset_workflow_service,
    )

    try:
        state = overlay_asset_workflow_service.get_asset_state(layer_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _layer_asset_state_response(layer_id, state)


@router.get(
    "/layers/{layer_id}/lifecycle",
    tags=["layer-platform"],
    response_model=LayerLifecycleResponse,
)
def get_layer_lifecycle(
    layer_id: str,
    limit: int = Query(default=5, ge=1, le=20),
    cred=Depends(get_request_user),
) -> LayerLifecycleResponse:
    """图层生命周期聚合视图（图层平台子系统 P0）。

    聚合资产状态 + 最近 run（workflow_kind/layer_id 索引查询）+ 时间轴元数据，
    前端不再自行拼接 jobLayer / overlayTimeStates / asset_state。
    """
    check_resource_access(cred, "layer", layer_id)
    from app.services.overlay_asset_workflow_service import (
        overlay_asset_workflow_service,
    )

    try:
        state = overlay_asset_workflow_service.get_asset_state(layer_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    asset = _layer_asset_state_response(layer_id, state)
    from app.services.workflow_repository import SQLiteWorkflowRepository

    repository = SQLiteWorkflowRepository()
    runs = repository.list_runs_by_layer(layer_id, limit=limit)
    recent = [
        LayerLifecycleRunSummary(
            run_id=r.run_id,
            workflow_kind=(r.executor_metadata or {}).get("workflow_kind"),
            status=r.status.value,
            progress=r.progress,
            message=r.message,
            updated_at=r.updated_at,
        )
        for r in runs
    ]
    lifecycle_state, message = _compute_lifecycle_state(asset.asset_state, runs)
    from datetime import UTC, datetime as _dt

    return LayerLifecycleResponse(
        layer_id=layer_id,
        asset=asset,
        recent_runs=recent,
        lifecycle_state=lifecycle_state,
        message=message,
        updated_at=runs[0].updated_at if runs else _dt.now(UTC),
    )


@router.get("/layers/{layer_id}/online-temporal", tags=["catalog"])
def get_layer_online_temporal(
    layer_id: str,
    cred=Depends(get_request_user),
) -> dict[str, Any]:
    """返回图层的在线时间获取能力与可获取范围。

    前端时间轴据此判断哪些时间点可在线获取（标 'fetchable' 段），
    以及获取参数（步长、预取深度、队列标签）。
    """
    check_resource_access(cred, "layer", layer_id)
    descriptor = get_layer_descriptor(layer_id)
    cap = descriptor.online_temporal if descriptor else None
    if cap is None or not cap.enabled:
        return {"layer_id": layer_id, "available": False}
    return {"layer_id": layer_id, "available": True, **cap.model_dump()}


def _submit_online_sync_workflow(
    payload: Any, cred: Any = None
) -> Any:
    """online_sync 的 workflow 提交封装（可 mock）。

    模块级独立函数便于测试隔离路由编排逻辑与真实 workflow 提交。
    """
    from app.api.routers.workflow_router import submit_workflow

    return submit_workflow(
        payload,
        cred=cred if hasattr(cred, "role") else None,
    )


@router.post(
    "/layer-assets/{layer_id}/sync",
    tags=["layer-platform"],
    response_model=LayerOnlineSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def sync_layer_asset_online(
    layer_id: str,
    body: LayerOnlineSyncRequest | None = None,
    cred=Depends(get_request_user),
) -> LayerOnlineSyncResponse:
    """在线源同步统一入口（图层平台子系统 P1）。

    前端不再自行拼 workflow 提交参数；服务端创建 ``workflow_kind=online_sync``
    的 run 并复用 workflow-runs 状态/事件/取消契约。

    语义：
    - 图层未启用 online_temporal → ``skipped-unsupported``（200，不报错）
    - 已有同图层同时间的活跃 online_sync run → ``in-flight``（复用）
    - 其他情况 → 提交 workflow run，返回 ``submitted``

    失败时保留旧资产显示（run 失败不影响已有烘焙资产）。
    """
    check_resource_access(cred, "layer", layer_id)
    descriptor = get_layer_descriptor(layer_id)
    cap = descriptor.online_temporal if descriptor else None
    if cap is None or not cap.enabled:
        return LayerOnlineSyncResponse(
            status="skipped-unsupported",
            message=f"图层 {layer_id} 未启用在线时间获取。",
            layer_id=layer_id,
            time_key=body.time_key if body else None,
        )

    from shared.contracts.api_contracts import ExecutionStatus

    from app.services.workflow_repository import SQLiteWorkflowRepository

    body = body or LayerOnlineSyncRequest()
    repository = SQLiteWorkflowRepository()

    # 复用同图层活跃 online_sync run（避免重复拉取）
    for existing in repository.list_runs_by_layer(
        layer_id, limit=10, workflow_kind="online_sync"
    ):
        if existing.status in {
            ExecutionStatus.accepted,
            ExecutionStatus.queued,
            ExecutionStatus.running,
            ExecutionStatus.retry_pending,
        }:
            return LayerOnlineSyncResponse(
                run_id=existing.run_id,
                status="in-flight",
                message=f"图层 {layer_id} 的在线同步已在执行中。",
                layer_id=layer_id,
                time_key=body.time_key,
                status_url=existing.status_url or f"/workflow-runs/{existing.run_id}",
                events_url=existing.events_url or f"/workflow-runs/{existing.run_id}/events",
            )

    # 构建 workflow 提交请求
    from shared.contracts.api_contracts import (
        TimeRange,
        WorkflowCommandType,
        WorkflowPriority,
        WorkflowResourceProfile,
        WorkflowSubmitRequest,
    )

    time_range = body.time_range
    if time_range is None and body.time_key:
        # time_key 简单解析：YYYY-MM → 当月范围；YYYY-MM-DD → 当天
        key = body.time_key
        try:
            if len(key) == 7:  # YYYY-MM
                from datetime import date
                y, m = int(key[:4]), int(key[5:7])
                start = date(y, m, 1)
                if m == 12:
                    end = date(y + 1, 1, 1)
                else:
                    end = date(y, m + 1, 1)
                time_range = TimeRange(
                    start_at=start.isoformat(), end_at=end.isoformat()
                )
            elif len(key) == 10:  # YYYY-MM-DD
                from datetime import date as _date, timedelta as _td
                d = _date.fromisoformat(key)
                time_range = TimeRange(
                    start_at=d.isoformat(), end_at=(d + _td(days=1)).isoformat()
                )
        except (ValueError, TypeError):
            pass

    priority = (
        WorkflowPriority.low
        if body.priority == "low" or body.is_prefetch
        else WorkflowPriority.normal
    )
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.custom,
        command_label=f"在线同步 {layer_id}" + (f" @ {body.time_key}" if body.time_key else ""),
        layer_id=layer_id,
        priority=priority,
        resource_profile=(
            WorkflowResourceProfile.batch
            if body.is_prefetch or body.priority == "low"
            else WorkflowResourceProfile.standard
        ),
        time_range=time_range,
        parameters={
            "workflow_kind": "online_sync",
            "time_key": body.time_key,
            "is_prefetch": body.is_prefetch,
        },
        queue_tag=cap.queue_tag,
    )

    accepted = _submit_online_sync_workflow(payload, cred=cred)
    return LayerOnlineSyncResponse(
        run_id=accepted.run_id,
        status="submitted",
        message=accepted.message,
        layer_id=layer_id,
        time_key=body.time_key,
        status_url=accepted.status_url,
        events_url=accepted.events_url,
    )


# ── 图层平台子系统 P1：课题组工作流模板一键显示 ─────────────────────────────


@router.get(
    "/workflows/templates",
    tags=["layer-platform"],
    response_model=WorkflowTemplateListResponse,
)
def list_workflow_templates(
    cred=Depends(get_request_user),
) -> WorkflowTemplateListResponse:
    """课题组工作流模板列表（图层平台子系统 P1）。

    聚合 workflow_seeds/system + workflow_definitions/user 中
    ``is_template=true`` 或 tags 含 "template"/"lab" 的定义；
    前端课题组入口据此渲染「一键运行」面板。
    """
    from app.services.workflow_definition_service import list_definitions

    items: list[WorkflowTemplateSummary] = []
    for item in list_definitions():
        meta = item if isinstance(item, dict) else {}
        tags = [str(t) for t in (meta.get("tags") or [])]
        is_template = bool(meta.get("is_template", False)) or any(
            t in {"template", "lab", "课题组"} for t in tags
        )
        if not is_template:
            continue
        items.append(
            WorkflowTemplateSummary(
                workflow_id=str(meta.get("workflow_id") or ""),
                name=str(meta.get("name") or meta.get("workflow_id") or ""),
                description=meta.get("description"),
                engine=str(meta.get("engine") or "unknown"),
                linked_layer_id=meta.get("linked_layer_id"),
                auto_display=bool(meta.get("auto_display", True)),
                resource_profile=str(meta.get("resource_profile") or "standard"),
                is_template=bool(meta.get("is_template", True)),
                readonly=bool(meta.get("readonly", False)),
                kind=str(meta.get("kind") or "system"),
                node_count=int(meta.get("node_count") or 0),
                tags=tags,
                updated_at=meta.get("updated_at"),
            )
        )
    return WorkflowTemplateListResponse(items=items, count=len(items))


@router.post(
    "/workflows/templates/{workflow_id}/runs",
    tags=["layer-platform"],
    response_model=WorkflowTemplateRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_workflow_template(
    workflow_id: str,
    body: WorkflowTemplateRunRequest | None = None,
    cred=Depends(get_request_user),
) -> WorkflowTemplateRunResponse:
    """课题组工作流模板一键运行（图层平台子系统 P1）。

    按模板定义构建 WorkflowSubmitRequest 并提交；
    完成后若 auto_display=true 且 linked_layer_id 非空，
    由 workflow-runs 轮询链自动 materialize-map-layers 上图。
    """
    check_resource_access(cred, "workflow", workflow_id)
    from app.services.workflow_definition_service import get_definition

    definition = get_definition(workflow_id)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow template not found: {workflow_id}",
        )

    meta = definition.get("_meta", {}) if isinstance(definition, dict) else {}
    linked_layer_id = meta.get("linked_layer_id")
    auto_display = bool(meta.get("auto_display", True))
    resource_profile_str = str(meta.get("resource_profile") or "standard")

    body = body or WorkflowTemplateRunRequest()
    if body.resource_profile is not None:
        resource_profile_str = body.resource_profile
    if body.auto_display is not None:
        auto_display = body.auto_display

    # 构建提交请求
    from shared.contracts.api_contracts import (
        WorkflowCommandType,
        WorkflowPriority,
        WorkflowResourceProfile,
        WorkflowSubmitRequest,
    )

    resource_profile = {
        "light": WorkflowResourceProfile.light,
        "realtime": WorkflowResourceProfile.light,  # realtime 别名映射到 light
        "standard": WorkflowResourceProfile.standard,
        "heavy": WorkflowResourceProfile.heavy,
        "batch": WorkflowResourceProfile.batch,
    }.get(resource_profile_str, WorkflowResourceProfile.standard)

    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.custom,
        command_label=f"课题组模板 {meta.get('name', workflow_id)}",
        layer_id=linked_layer_id,
        priority=WorkflowPriority.normal,
        resource_profile=resource_profile,
        time_range=body.time_range,
        parameters={
            "workflow_kind": "lab_template",
            "workflow_template_id": workflow_id,
            "auto_display": auto_display,
            **body.parameters,
        },
    )

    accepted = _submit_online_sync_workflow(payload, cred=cred)
    return WorkflowTemplateRunResponse(
        run_id=accepted.run_id,
        status="submitted",
        message=accepted.message,
        workflow_id=workflow_id,
        linked_layer_id=linked_layer_id,
        auto_display=auto_display,
        status_url=accepted.status_url,
        events_url=accepted.events_url,
    )


@router.get("/geo/transform", tags=["geo"])
def transform_geo_point(
    lng: float, lat: float, source: str, target: str = "EPSG:3857"
) -> dict[str, float | str]:
    try:
        # 归一化旧码连字符写法（'GCJ-02' → 'GCJ02'，'BD-09' → 'BD09'），
        # 保持与旧垫片 transform_point 相同的向后兼容行为
        src = normalize_crs_code(source)
        tgt = normalize_crs_code(target)
        point = crs_transformer.transform_point(lng, lat, src, tgt)
        return {"lng": point.lng, "lat": point.lat, "source": source, "target": target}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/overlay-preview/{layer_id}", tags=["overlay"])
def get_overlay_preview(
    layer_id: str,
    time: str | None = Query(default=None),
    palette: str | None = Query(default=None),
    min_value: float | None = Query(default=None),
    max_value: float | None = Query(default=None),
    nodata_mode: str | None = Query(default=None),
    nodata_color: str | None = Query(default=None),
    cred=Depends(get_request_user),
) -> Response:
    """返回图层的 PNG 预览图（地理配准），供前端 MapLibre image source 使用。

    对于时间序列图层，可通过 `?time=YYYYMMDD` 指定时间标签；
    未指定时使用 default_time。

    有可读源且传入 palette/min/max/nodata 时动态重着色；否则返回烘焙 PNG。
    """
    check_resource_access(cred, "layer", layer_id)
    from app.services.overlay_recolor import render_overlay_preview_styled

    styled = bool(
        (palette and palette.strip())
        or min_value is not None
        or max_value is not None
        or (nodata_mode and nodata_mode.strip())
        or (nodata_color and nodata_color.strip())
    )
    content = render_overlay_preview_styled(
        layer_id,
        time=time,
        palette=palette,
        min_value=min_value,
        max_value=max_value,
        nodata_mode=nodata_mode,
        nodata_color=nodata_color,
    )
    # ACL-gated assets must not be shared via public caches.
    cache = "no-cache, must-revalidate" if styled else "private, max-age=60"
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": cache, "Vary": "Accept-Encoding"},
    )


@router.get("/overlay-tiles/{layer_id}/{z}/{x}/{y}.png", tags=["overlay"])
def get_overlay_tile(
    layer_id: str,
    z: int,
    x: int,
    y: int,
    time: str | None = Query(default=None),
    palette: str | None = Query(default=None),
    min_value: float | None = Query(default=None),
    max_value: float | None = Query(default=None),
    nodata_mode: str | None = Query(default=None),
    nodata_color: str | None = Query(default=None),
    cred=Depends(get_request_user),
) -> Response:
    """Web Mercator XYZ PNG tile for imported / geotiff-backed overlays."""
    check_resource_access(cred, "layer", layer_id)
    from app.services.overlay_tile_service import render_overlay_tile

    spec = get_overlay_spec(layer_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No overlay for layer: {layer_id}")
    source = spec.resolve_source_path(time)
    if source is None or source.suffix.lower() not in {
        ".tif",
        ".tiff",
        ".geotiff",
        ".cog",
    }:
        raise HTTPException(
            status_code=404,
            detail=f"Overlay has no GeoTIFF source for XYZ tiles: {layer_id}",
        )
    try:
        png = render_overlay_tile(
            str(source),
            z,
            x,
            y,
            band=spec.source_band,
            palette=palette or spec.palette or "viridis",
            min_value=min_value if min_value is not None else spec.vmin,
            max_value=max_value if max_value is not None else spec.vmax,
            nodata_mode=nodata_mode,
            nodata_color=nodata_color,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _logger.warning(
            "overlay tile render failed %s z=%s", layer_id, z, exc_info=True
        )
        # B-7：500 固定文案（不回显 exc，防内部信息泄露；真因走日志 exc_info）
        raise HTTPException(status_code=500, detail="Tile render failed") from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=120", "Vary": "Accept-Encoding"},
    )


@router.get("/overlay-bounds/{layer_id}", tags=["overlay"])
def get_overlay_bounds(
    layer_id: str,
    time: str | None = Query(default=None),
    cred=Depends(get_request_user),
) -> dict[str, Any]:
    """返回图层的地理边界信息 + 元数据，供前端 MapLibre image source 定位与时间控制使用。"""
    check_resource_access(cred, "layer", layer_id)
    return read_bounds(layer_id, time)


@router.get("/overlays", tags=["overlay"])
def list_overlays(cred=Depends(get_request_user)) -> dict[str, Any]:
    """列出当前用户可访问的叠加图层 ID（供前端发现可用 overlay 图层）。"""
    ids = _filter_accessible_layer_ids(list_overlay_ids(), cred)
    return {"overlay_layer_ids": ids}


@router.get("/overlays/intersect", tags=["overlay"])
def get_overlays_in_viewport(
    west: float = Query(..., ge=-180, le=360),  # 容许 >180（跨日界线 unwrap）
    south: float = Query(..., ge=-90, le=90),
    east: float = Query(..., ge=-180, le=360),
    north: float = Query(..., ge=-90, le=90),
    zoom: int | None = Query(default=None, ge=0, le=24),
    cred=Depends(get_request_user),
) -> dict[str, Any]:
    """返回与视口相交且当前用户可访问的 overlay layer_ids。

    优先用 spatial.sqlite + R*Tree（``ST_Intersects``）；扩展不可用或表空时
    回退到逐层读 ``bounds.json`` 做 AABB 相交（与原前端 O(N) 过滤等价）。
    空间库就绪时即使零命中也信任结果，不再误扫 bounds.json。

    跨日界线约定：前端对跨日界线视口传 ``east > 180``（unwrap），与
    ``overlay_safe_wgs84_bounds`` 一致。

    回退路径无 zoom 元资料时不过滤（bounds.json / registry 目前无 min/maxzoom）。
    """
    from app.services.spatial_repository import get_spatial_repository

    repo = get_spatial_repository()
    if repo.is_spatial_ready():
        hits = repo.query_intersects(west, south, east, north, zoom=zoom)
        raw_ids = [h["layer_id"] for h in hits]
        return {
            "layer_ids": _filter_accessible_layer_ids(raw_ids, cred),
            "source": "spatialite",
        }

    # 回退：扫所有 overlay 的 bounds.json 做 AABB 相交（未导入 / 扩展不可用）
    from app.services.geo_math import overlay_safe_wgs84_bounds

    matched: list[str] = []
    # 视口也按同一日界线展开约定归一化，与空间路径（BuildMBR 用展开后视口）保持同一空间
    vw, vs_, ve, vn = overlay_safe_wgs84_bounds(west, south, east, north)
    for lid in list_overlay_ids():
        try:
            b = read_bounds(lid).get("bounds")
            if not b or len(b) < 4:
                continue
            ow, os_, oe, on = b
            ow, os_, oe, on = overlay_safe_wgs84_bounds(ow, os_, oe, on)
            # AABB 相交（视口与 bounds 都已 unwrap 到同一空间）
            if vw <= oe and ve >= ow and vs_ <= on and vn >= os_:
                matched.append(lid)
        except Exception:
            _logger.debug(
                "overlay %s bounds read failed in fallback", lid, exc_info=True
            )
            continue
    return {
        "layer_ids": _filter_accessible_layer_ids(matched, cred),
        "source": "fallback_bounds_json",
    }


@router.get("/overlay-value/{layer_id}", tags=["overlay"])
def get_overlay_value(
    layer_id: str,
    lng: float = Query(...),
    lat: float = Query(...),
    time: str | None = Query(default=None),
    cred=Depends(get_request_user),
) -> dict[str, Any]:
    """查询 overlay 图层在指定点 (lng, lat) 的像素值。

    对于时间序列图层，可通过 ?time=YYYYMMDD 指定时间标签。
    返回 {"value": float | null, "unit": str, "layer_id": str, ...}。
    """
    check_resource_access(cred, "layer", layer_id)
    spec = get_overlay_spec(layer_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No overlay for layer: {layer_id}")
    return spec.resolve_value(lng, lat, time)
