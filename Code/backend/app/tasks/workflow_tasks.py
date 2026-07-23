from __future__ import annotations

from typing import Any, Callable

from app.core.celery_app import celery_app, celery_available
from app.core.config import settings
from app.services.gee_bridge_service import gee_bridge_service
from app.services.provider_workflow_service import provider_workflow_service
from app.services.python_provider_bridge_service import python_provider_bridge_service
from app.services.weather_bridge_service import weather_bridge_service
from app.services.workflow_execution import WorkflowExecutionResult
from app.weatherengine.service import weather_engine_service
from shared.contracts.api_contracts import (
    WorkflowPriority,
    WorkflowResourceProfile,
    WorkflowSubmitRequest,
)

_NO_BRIDGE_MESSAGE = (
    "No workflow bridge matched this payload. "
    "Provide gee_request, weather_request, algorithm_request, or provider_request."
)

# m22 修复：统一的 bridge-channel 映射表
# 顺序即优先级，与 resolve_workflow_channel 共享同一数据源
_BRIDGE_CHAIN: list[tuple[Any, str]] = [
    (gee_bridge_service, "gee"),
    (weather_bridge_service, "weather"),
    (python_provider_bridge_service, "algorithm"),
    (provider_workflow_service, "analysis"),
    # C2 修复：旧 monolithic weather service 作为 layer-based fallback
    # 必须放在 weather_bridge_service 之后
    (weather_engine_service, "weather"),
]


def _explain_no_bridge(payload: WorkflowSubmitRequest) -> str:
    """给无 bridge 匹配的请求补充可读原因（图层无引擎 / 引擎字段未组装）。"""
    layer_id = payload.layer_id or getattr(payload.map_context, "active_layer_id", None)
    if not layer_id:
        return _NO_BRIDGE_MESSAGE

    try:
        from app.services.layer_catalog import get_layer_descriptor

        descriptor = get_layer_descriptor(str(layer_id))
    except Exception:
        descriptor = None

    if descriptor is None:
        return (
            f"Unknown layer '{layer_id}' — no workflow bridge matched. "
            f"{_NO_BRIDGE_MESSAGE}"
        )
    if not descriptor.engine:
        display = descriptor.display_name or layer_id
        return (
            f"Layer '{display}' ({layer_id}) has no workflow engine. "
            "Static overlays load directly; weather layers use the tile service. "
            f"{_NO_BRIDGE_MESSAGE}"
        )
    return (
        f"Layer '{descriptor.display_name or layer_id}' (engine={descriptor.engine}) "
        f"did not match any workflow bridge. {_NO_BRIDGE_MESSAGE}"
    )


def _find_bridge_handler(
    payload: WorkflowSubmitRequest,
) -> tuple[Callable[..., WorkflowExecutionResult], str] | None:
    for bridge, channel in _BRIDGE_CHAIN:
        if bridge.supports(payload):
            return bridge.execute, channel
    return None


def _resolve_workflow_handler(
    payload: WorkflowSubmitRequest,
) -> Callable[..., WorkflowExecutionResult]:
    bridge_match = _find_bridge_handler(payload)
    if bridge_match is not None:
        handler, _channel = bridge_match
        return handler
    raise ValueError(_explain_no_bridge(payload))


def execute_workflow_task(
    *, run_id: str, payload: WorkflowSubmitRequest, requested_at, event_factory
) -> WorkflowExecutionResult:
    handler = _resolve_workflow_handler(payload)
    return handler(
        run_id=run_id,
        payload=payload,
        requested_at=requested_at,
        event_factory=event_factory,
    )


def resolve_workflow_channel(payload: WorkflowSubmitRequest) -> str:
    # C1 修复：通道判定通过 _BRIDGE_CHAIN 遍历，与 execute_workflow_task 调度顺序一致
    bridge_match = _find_bridge_handler(payload)
    if bridge_match is not None:
        _handler, channel = bridge_match
        return channel
    raise ValueError(_explain_no_bridge(payload))


# M14 修复：队列查表化，避免 18 个 if/elif 分支
# (channel, resource_profile) → queue_setting_attr
_CHANNEL_PROFILE_QUEUE_MAP: dict[tuple[str, str], str] = {
    ("gee", "batch"): "workflow_queue_gee_batch",
    ("gee", "heavy"): "workflow_queue_gee_heavy",
    ("gee", "realtime"): "workflow_queue_gee_realtime",
    ("gee", "standard"): "workflow_queue_gee_standard",
    ("weather", "batch"): "workflow_queue_weather_batch",
    ("weather", "heavy"): "workflow_queue_weather_heavy",
    ("weather", "realtime"): "workflow_queue_weather_realtime",
    ("weather", "standard"): "workflow_queue_weather_standard",
    ("algorithm", "batch"): "workflow_queue_algorithm_batch",
    ("algorithm", "heavy"): "workflow_queue_algorithm_heavy",
    ("algorithm", "realtime"): "workflow_queue_algorithm_realtime",
    ("algorithm", "standard"): "workflow_queue_algorithm_standard",
    ("analysis", "batch"): "workflow_queue_analysis_batch",
    ("analysis", "heavy"): "workflow_queue_analysis_heavy",
    ("analysis", "realtime"): "workflow_queue_realtime",
    ("analysis", "standard"): "workflow_queue_analysis_standard",
    ("download", "realtime"): "workflow_queue_download_realtime",
    ("download", "standard"): "workflow_queue_download_standard",
}


def _resolve_profile_slot(profile: WorkflowResourceProfile, is_realtime: bool) -> str:
    """将 resource_profile + realtime 标志解析为队列槽位名（realtime/heavy/batch/standard）。"""
    if profile == WorkflowResourceProfile.batch:
        return "batch"
    if profile == WorkflowResourceProfile.heavy:
        return "heavy"
    if is_realtime:
        return "realtime"
    return "standard"


def resolve_workflow_queue(payload: WorkflowSubmitRequest) -> str:
    if payload.queue_tag:
        # m21 修复：queue_tag 白名单校验，避免任意字符串注入
        queue_tag = payload.queue_tag
        if not _is_valid_queue_tag(queue_tag):
            raise ValueError(
                f"Invalid queue_tag: {queue_tag}. "
                f"Must match a registered queue name or pattern '<channel>-<slot>'. "
                f"Allowed channels: gee, weather, algorithm, analysis, download."
            )
        return queue_tag
    channel = resolve_workflow_channel(payload)
    is_realtime = payload.realtime_preferred or payload.priority in {
        WorkflowPriority.high,
        WorkflowPriority.critical,
    }
    slot = _resolve_profile_slot(payload.resource_profile, is_realtime)
    queue_attr = _CHANNEL_PROFILE_QUEUE_MAP.get((channel, slot))
    if queue_attr is None:
        # 未知组合 fallback 到 analysis standard
        queue_attr = "workflow_queue_analysis_standard"
    return getattr(settings, queue_attr)


# m21 修复：queue_tag 白名单校验
# 允许已注册的队列名，或符合 <channel>-<slot> 模式的自定义队列名
_VALID_QUEUE_CHANNELS = {"gee", "weather", "algorithm", "analysis", "download"}
_VALID_QUEUE_SLOTS = {"realtime", "standard", "heavy", "batch"}


def _is_valid_queue_tag(queue_tag: str) -> bool:
    """校验 queue_tag 是否符合白名单。

    允许两种形式：
    1. settings 中已注册的队列名（如 workflow_queue_gee_standard 对应的值）
    2. 符合 <channel>-<slot> 模式的自定义队列名（如 gee-realtime）
    """
    # 形式 2：channel-slot 模式
    parts = queue_tag.split("-", 1)
    if (
        len(parts) == 2
        and parts[0] in _VALID_QUEUE_CHANNELS
        and parts[1] in _VALID_QUEUE_SLOTS
    ):
        return True
    # 形式 1：settings 中已注册的队列值
    for attr_name in dir(settings):
        if attr_name.startswith("workflow_queue_"):
            attr_value = getattr(settings, attr_name, None)
            if isinstance(attr_value, str) and attr_value == queue_tag:
                return True
    return False


if celery_available and celery_app is not None:

    @celery_app.task(name="app.tasks.workflow_tasks.process_workflow_run")
    def process_workflow_run_task(run_id: str, payload_data: dict[str, Any]) -> None:
        from app.services.workflow.service_container import submission_service

        payload = WorkflowSubmitRequest.model_validate(payload_data)
        submission_service.process_workflow_run(run_id, payload)

else:

    def process_workflow_run_task(run_id: str, payload_data: dict[str, Any]) -> None:
        raise RuntimeError(
            "Celery is not installed. Install backend dependencies before using celery executor."
        )


def dispatch_workflow_task(
    run_id: str, payload: WorkflowSubmitRequest, *, countdown: float | None = None
) -> str:
    if not celery_available or celery_app is None:
        raise RuntimeError(
            "Celery is not installed. Install backend dependencies before using celery executor."
        )

    apply_async_kwargs: dict[str, Any] = {
        "kwargs": {"run_id": run_id, "payload_data": payload.model_dump(mode="json")},
        "queue": resolve_workflow_queue(payload),
        "priority": {
            WorkflowPriority.low: 1,
            WorkflowPriority.normal: 5,
            WorkflowPriority.high: 8,
            WorkflowPriority.critical: 9,
        }[payload.priority],
    }
    if countdown is not None:
        apply_async_kwargs["countdown"] = countdown

    async_result = process_workflow_run_task.apply_async(**apply_async_kwargs)
    return async_result.id
