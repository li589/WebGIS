"""失败分类器。

把各类异常（ValueError / RuntimeError / ConnectionError / TimeoutError / HTTP 状态码等）
映射到统一的 FailureCategory，供 hub 层判断是否重试。

使用方式：
    try:
        bridge.execute(...)
    except Exception as exc:
        category = FailureClassifier.classify(exc)
        raise BridgeExecutionError(category=category, message=str(exc), cause=exc) from exc
"""

from __future__ import annotations


from shared.contracts.api_contracts import FailureCategory


class FailureClassifier:
    """异常 → FailureCategory 映射器。"""

    # 可重试的内置异常类型
    _TRANSIENT_EXCEPTION_TYPES = {
        ConnectionError,
        TimeoutError,
        OSError,  # 网络层 OSError 子类（如 ConnectionRefusedError）通常可重试
    }

    # 不可重试的内置异常类型
    _TERMINAL_EXCEPTION_TYPES = {
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        NotImplementedError,
    }

    @classmethod
    def classify(cls, exc: Exception) -> FailureCategory:
        """把异常分类为 FailureCategory。"""
        # 已经是 BridgeExecutionError：直接取其 category
        from app.services.bridge_protocol import BridgeExecutionError

        if isinstance(exc, BridgeExecutionError):
            return exc.category

        # 按 HTTP 状态码分类（若异常带 status_code 属性）
        status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if isinstance(status_code, int):
            return cls._classify_http_status(status_code)

        # 按异常消息关键词分类
        message = str(exc).lower()
        if any(kw in message for kw in ("timeout", "timed out", "超时")):
            return FailureCategory.timeout
        if any(
            kw in message for kw in ("rate limit", "429", "too many requests", "限流")
        ):
            return FailureCategory.rate_limited
        if any(kw in message for kw in ("not found", "404", "不存在")):
            return FailureCategory.not_found
        if any(
            kw in message
            for kw in ("permission", "forbidden", "403", "unauthorized", "401", "权限")
        ):
            return FailureCategory.permission_denied
        if any(
            kw in message for kw in ("validation", "invalid", "参数错误", "校验失败")
        ):
            return FailureCategory.validation_error
        if any(kw in message for kw in ("contract", "decode", "协议", "schema")):
            return FailureCategory.contract_violation
        if any(
            kw in message
            for kw in ("connection", "network", "unreachable", "网络", "连接")
        ):
            return FailureCategory.transient_network
        if any(kw in message for kw in ("upstream", "502", "503", "504", "上游")):
            return FailureCategory.transient_upstream

        # 按异常类型分类
        for exc_type in cls._TRANSIENT_EXCEPTION_TYPES:
            if isinstance(exc, exc_type):
                return FailureCategory.transient_network
        for exc_type in cls._TERMINAL_EXCEPTION_TYPES:
            if isinstance(exc, exc_type):
                return FailureCategory.terminal_failure

        # 默认：不可重试（保守策略，避免无限重试未知错误）
        return FailureCategory.terminal_failure

    @classmethod
    def _classify_http_status(cls, status_code: int) -> FailureCategory:
        """按 HTTP 状态码分类。"""
        if status_code == 429:
            return FailureCategory.rate_limited
        if status_code in (401, 403):
            return FailureCategory.permission_denied
        if status_code == 404:
            return FailureCategory.not_found
        if 400 <= status_code < 500:
            return FailureCategory.validation_error
        if status_code in (502, 503, 504):
            return FailureCategory.transient_upstream
        if status_code >= 500:
            return FailureCategory.transient_upstream
        return FailureCategory.terminal_failure

    @classmethod
    def is_retryable(cls, exc: Exception) -> bool:
        """判断异常是否可重试。"""
        return cls.classify(exc).retryable
