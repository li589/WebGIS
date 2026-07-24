"""工作流定时器管理 API 路由

提供 CompyUI 工作流编辑器集成所需的后端接口：
- GET    /workflow-timers                   列出全部定时器（可选 ?workflow_id= 过滤）
- POST   /workflow-timers                   创建定时器
- GET    /workflow-timers/{id}              获取单个定时器
- PUT    /workflow-timers/{id}              更新定时器
- DELETE /workflow-timers/{id}              删除定时器
- POST   /workflow-timers/{id}/run          手动触发一次
- POST   /workflow-timers/events            发射事件（触发匹配的 event 定时器）
- POST   /workflow-timers/tick              手动触发一次扫描（调试用）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_write_access
from app.services import workflow_timer_service as wts
from app.services.workflow_timer_service import (
    TimerNotFoundError,
    TimerValidationError,
)

router = APIRouter()


# ─── 列表 / 详情 ────────────────────────────────────────────────────────────
@router.get("/workflow-timers", tags=["workflow-timer"])
def list_timers(workflow_id: str | None = Query(default=None)) -> dict[str, Any]:
    """列出全部定时器，可选按 workflow_id 过滤。"""
    timers = wts.get_timer_store().list_timers(workflow_id=workflow_id)
    return {
        "items": [wts.timer_to_dict(t) for t in timers],
        "count": len(timers),
    }


@router.get("/workflow-timers/{timer_id}", tags=["workflow-timer"])
def get_timer(timer_id: str) -> dict[str, Any]:
    """获取单个定时器详情。"""
    timer = wts.get_timer_store().get_timer(timer_id)
    if timer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"workflow timer not found: {timer_id}",
        )
    return wts.timer_to_dict(timer)


# ─── 创建 / 更新 / 删除 ─────────────────────────────────────────────────────
@router.post(
    "/workflow-timers",
    tags=["workflow-timer"],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_access)],
)
def create_timer(payload: dict[str, Any]) -> dict[str, Any]:
    """创建定时器。

    请求体字段：
    - workflow_id (str, 必填)
    - name (str, 必填)
    - trigger_type ('cron' | 'interval' | 'event', 必填)
    - trigger_config (dict, 必填, 格式依 trigger_type 而定)
    - payload_overrides (dict, 可选)
    - enabled (bool, 可选, 默认 true)
    """
    workflow_id = payload.get("workflow_id")
    name = payload.get("name")
    trigger_type = payload.get("trigger_type")
    trigger_config = payload.get("trigger_config")
    if not workflow_id or not isinstance(workflow_id, str):
        raise HTTPException(status_code=400, detail="workflow_id is required")
    if not name or not isinstance(name, str):
        raise HTTPException(status_code=400, detail="name is required")
    if trigger_type not in ("cron", "interval", "event"):
        raise HTTPException(
            status_code=400,
            detail=f"trigger_type must be one of: cron, interval, event (got {trigger_type!r})",
        )
    if not isinstance(trigger_config, dict):
        raise HTTPException(status_code=400, detail="trigger_config must be an object")

    payload_overrides = payload.get("payload_overrides") or {}
    if not isinstance(payload_overrides, dict):
        raise HTTPException(
            status_code=400, detail="payload_overrides must be an object"
        )
    enabled = bool(payload.get("enabled", True))

    try:
        timer = wts.create_timer(
            workflow_id=workflow_id,
            name=name,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            payload_overrides=payload_overrides,
            enabled=enabled,
        )
    except TimerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return wts.timer_to_dict(timer)


@router.put(
    "/workflow-timers/{timer_id}",
    tags=["workflow-timer"],
    dependencies=[Depends(require_write_access)],
)
def update_timer(timer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """更新定时器。允许字段：name / enabled / trigger_type / trigger_config / payload_overrides。"""
    # 校验 trigger_type 若提供则合法
    if "trigger_type" in payload and payload["trigger_type"] not in (
        "cron",
        "interval",
        "event",
    ):
        raise HTTPException(
            status_code=400,
            detail=f"trigger_type must be one of: cron, interval, event (got {payload['trigger_type']!r})",
        )
    if "trigger_config" in payload and not isinstance(payload["trigger_config"], dict):
        raise HTTPException(status_code=400, detail="trigger_config must be an object")
    if "payload_overrides" in payload and not isinstance(
        payload["payload_overrides"], dict
    ):
        raise HTTPException(
            status_code=400, detail="payload_overrides must be an object"
        )

    # 仅传递支持的字段
    updates = {
        k: payload[k]
        for k in (
            "name",
            "enabled",
            "trigger_type",
            "trigger_config",
            "payload_overrides",
        )
        if k in payload
    }
    try:
        timer = wts.get_timer_store().update_timer(timer_id, updates)
    except TimerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return wts.timer_to_dict(timer)


@router.delete(
    "/workflow-timers/{timer_id}",
    tags=["workflow-timer"],
    dependencies=[Depends(require_write_access)],
)
def delete_timer(timer_id: str) -> dict[str, Any]:
    """删除定时器。"""
    try:
        deleted = wts.get_timer_store().delete_timer(timer_id)
    except TimerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"workflow timer not found: {timer_id}"
        )
    return {"deleted": timer_id}


# ─── 手动触发 / 事件 / 调试 ─────────────────────────────────────────────────
@router.post(
    "/workflow-timers/{timer_id}/run",
    tags=["workflow-timer"],
    dependencies=[Depends(require_write_access)],
)
def run_timer(timer_id: str) -> dict[str, Any]:
    """手动触发一次定时器对应的工作流（不影响 next_fire_at）。"""
    try:
        return wts.trigger_manually(timer_id)
    except TimerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"trigger failed: {exc}") from exc


@router.post(
    "/workflow-timers/events",
    tags=["workflow-timer"],
    dependencies=[Depends(require_write_access)],
)
def emit_event(payload: dict[str, Any]) -> dict[str, Any]:
    """发射外部事件，触发匹配的 event 类型定时器。

    请求体：
    - event_type (str, 必填)
    - payload (dict, 可选)
    """
    event_type = payload.get("event_type")
    if not event_type or not isinstance(event_type, str):
        raise HTTPException(status_code=400, detail="event_type is required")
    event_payload = payload.get("payload")
    if event_payload is not None and not isinstance(event_payload, dict):
        raise HTTPException(
            status_code=400, detail="payload must be an object if provided"
        )
    return wts.emit_event(event_type, event_payload)


@router.post(
    "/workflow-timers/tick",
    tags=["workflow-timer"],
    dependencies=[Depends(require_write_access)],
)
def manual_tick() -> dict[str, Any]:
    """手动触发一次扫描（调试用，正常情况下由 Celery Beat 每分钟调用）。"""
    return wts.tick()
