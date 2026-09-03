"""Celery 派发结果分类：投递是否已确定未入 broker。"""

from __future__ import annotations

import concurrent.futures


def is_celery_dispatch_uncertain(exc: BaseException) -> bool:
    """判断 Celery ``apply_async`` 失败时，消息是否可能已投递到 broker。

    - **uncertain=True**：超时或模糊错误——限时放弃等待时消息可能已写入 Redis，
      不可当作「确定未投递」去立即二次派发（需依赖 watchdog / 启动清理交叉校验）。
    - **uncertain=False**：连接拒绝等——确定未投递，可安全由 queue_dispatch 重派。

    参见 submission_service._dispatch_async_workflow C4 注释。
    """
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, concurrent.futures.TimeoutError):
        return True

    text = f"{type(exc).__name__}: {exc}".lower()
    if (
        "timeout" in text
        or "timed out" in text
        or "apply_async >" in text
        or "broker timeout" in text
    ):
        return True

    # 半途断开：可能已投递
    if "reset by peer" in text or "broken pipe" in text:
        return True

    unreachable_markers = (
        "connection refused",
        "10061",  # WinError connection refused
        "errno 61",
        "errno 111",  # Linux connection refused
        "nodename nor servname",
        "name or service not known",
        "getaddrinfo failed",
        "broker unreachable",
        "error 10061",
        "积极拒绝",
        "无法连接",
    )
    if any(marker in text for marker in unreachable_markers):
        return False

    if isinstance(exc, ConnectionRefusedError):
        return False

    if isinstance(exc, (ConnectionError, OSError)):
        errno = getattr(exc, "errno", None)
        if errno in {61, 111, 10061}:
            return False
        # 无 errno 的 ConnectionError：多数表示连不上，视为未投递
        return False

    # 未知错误：保守视为 uncertain，避免盲目重派造成双投
    return True
