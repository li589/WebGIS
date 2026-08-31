"""工作流定时器管理 API 路由

提供 CompyUI 工作流编辑器集成所需的后端接口：
- GET    /workflow-timers                   列出定时器（多用户：非 admin 仅本人）
- POST   /workflow-timers                   创建定时器（记录归属 user_id）
- GET    /workflow-timers/{id}              获取单个定时器
- PUT    /workflow-timers/{id}              更新定时器
- DELETE /workflow-timers/{id}              删除定时器
- POST   /workflow-timers/{id}/run          手动触发一次
- POST   /workflow-timers/events            发射事件（触发匹配的 event 定时器）
- POST   /workflow-timers/tick              手动触发一次扫描（调试用）

多用户隔离（2026-08-20）：定时器记录 ``owner_user_id``；非 admin 用户仅
可见/可管本人创建的定时器（与 workflow run 的 owner 策略一致：旧共享
数据 owner=NULL 仅 admin / service_key / dev_bypass 可见；越权访问统一
404 防枚举）。调度路径（Celery Beat tick）不经路由层，不受影响。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    CredentialContext,
    get_request_user,
    require_workflow_run_access,
    require_write_access,
)
from app.api.error_codes import AUTH_ERROR, ApiError
from app.core import config
from app.services import workflow_timer_service as wts
from app.services.workflow_timer_service import (
    TimerNotFoundError,
    TimerValidationError,
    WorkflowTimer,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _timer_owner_filter(cred: CredentialContext | None) -> int | None:
    """列表过滤用的 owner_user_id；None 表示不过滤（全量）。

    *admin* / 基础设施凭据（service_key、dev_bypass）与 legacy 开放模式
    （``user_auth_enabled=False``）不过滤；普通登录用户仅看本人。
    """
    if not config.settings.user_auth_enabled:
        return None
    if cred is None:
        return None  # 匿名仅出现在 legacy 开放模式（require_write_access 已拦截）
    if cred.role == "admin":
        return None
    if cred.user_id is None:
        return None  # service_key / dev_bypass 基础设施凭据
    return cred.user_id


def _deny_if_not_timer_owner(
    timer: WorkflowTimer, cred: CredentialContext | None
) -> None:
    """单定时器归属校验：非 owner 统一 404 防枚举（对齐 run owner 策略）。"""
    if not config.settings.user_auth_enabled:
        return
    if cred is None:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    if cred.role == "admin":
        return
    if cred.user_id is None:
        if cred.source in {"service_key", "dev_bypass"}:
            return
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"workflow timer not found: {timer.timer_id}",
        )
    if timer.owner_user_id is None or timer.owner_user_id != cred.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"workflow timer not found: {timer.timer_id}",
        )


# ─── Cron 预览（只读计算，但需鉴权防滥用） ─────────────────────────────────
@router.post(
    "/workflow-timers/cron-preview",
    tags=["workflow-timer"],
    dependencies=[Depends(require_write_access)],
)
def preview_cron(payload: dict[str, Any]) -> dict[str, Any]:
    """预览 cron 表达式的接下来 N 次触发时间。

    请求体：
    - cron_expr (str, 必填): 5 字段 cron 表达式
    - count (int, 可选, 默认 5): 返回次数（1-20）
    """
    cron_expr = payload.get("cron_expr")
    if not isinstance(cron_expr, str) or not cron_expr.strip():
        raise HTTPException(status_code=400, detail="cron_expr is required")
    count = payload.get("count", 5)
    if not isinstance(count, int) or count < 1 or count > 20:
        count = 5
    try:
        next_times = wts.preview_cron(cron_expr.strip(), count)
    except TimerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"cron_expr": cron_expr.strip(), "next_times": next_times}


# ─── 列表 / 详情 ────────────────────────────────────────────────────────────
@router.get(
    "/workflow-timers",
    tags=["workflow-timer"],
    dependencies=[Depends(require_write_access)],
)
def list_timers(
    workflow_id: str | None = Query(default=None),
    cred: CredentialContext | None = Depends(get_request_user),
) -> dict[str, Any]:
    """列出定时器（非 admin 登录用户仅见本人创建的）。"""
    timers = wts.get_timer_store().list_timers(
        workflow_id=workflow_id,
        owner_user_id=_timer_owner_filter(cred),
    )
    return {
        "items": [wts.timer_to_dict(t) for t in timers],
        "count": len(timers),
    }


@router.get(
    "/workflow-timers/{timer_id}",
    tags=["workflow-timer"],
    dependencies=[Depends(require_write_access)],
)
def get_timer(
    timer_id: str,
    cred: CredentialContext | None = Depends(get_request_user),
) -> dict[str, Any]:
    """获取单个定时器详情。"""
    timer = wts.get_timer_store().get_timer(timer_id)
    if timer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"workflow timer not found: {timer_id}",
        )
    _deny_if_not_timer_owner(timer, cred)
    return wts.timer_to_dict(timer)


# ─── 创建 / 更新 / 删除 ─────────────────────────────────────────────────────
@router.post(
    "/workflow-timers",
    tags=["workflow-timer"],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_access)],
)
def create_timer(
    payload: dict[str, Any],
    cred: CredentialContext | None = Depends(get_request_user),
) -> dict[str, Any]:
    """创建定时器（记录归属 owner_user_id）。

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
            owner_user_id=cred.user_id if cred is not None else None,
        )
    except TimerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return wts.timer_to_dict(timer)


@router.put(
    "/workflow-timers/{timer_id}",
    tags=["workflow-timer"],
    dependencies=[Depends(require_write_access)],
)
def update_timer(
    timer_id: str,
    payload: dict[str, Any],
    cred: CredentialContext | None = Depends(get_request_user),
) -> dict[str, Any]:
    """更新定时器。允许字段：name / enabled / trigger_type / trigger_config / payload_overrides。"""
    existing = wts.get_timer_store().get_timer(timer_id)
    if existing is not None:
        _deny_if_not_timer_owner(existing, cred)
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
    # 安全：字段类型校验
    if "name" in updates and (
        not isinstance(updates["name"], str) or not updates["name"].strip()
    ):
        raise HTTPException(status_code=400, detail="name must be a non-empty string")
    if "enabled" in updates and not isinstance(updates["enabled"], bool):
        raise HTTPException(status_code=400, detail="enabled must be a boolean")
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
def delete_timer(
    timer_id: str,
    cred: CredentialContext | None = Depends(get_request_user),
) -> dict[str, Any]:
    """删除定时器。"""
    existing = wts.get_timer_store().get_timer(timer_id)
    if existing is not None:
        _deny_if_not_timer_owner(existing, cred)
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
    dependencies=[Depends(require_workflow_run_access)],
)
def run_timer(
    timer_id: str,
    cred: CredentialContext | None = Depends(get_request_user),
) -> dict[str, Any]:
    """手动触发一次定时器对应的工作流（不影响 next_fire_at）。"""
    existing = wts.get_timer_store().get_timer(timer_id)
    if existing is not None:
        _deny_if_not_timer_owner(existing, cred)
    try:
        return wts.trigger_manually(timer_id)
    except TimerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Timer trigger failed: timer_id=%s err=%s", timer_id, exc)
        raise HTTPException(status_code=500, detail="Timer trigger failed.") from exc


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
