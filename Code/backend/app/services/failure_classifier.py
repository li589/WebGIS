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

import errno

from shared.contracts.api_contracts import FailureCategory

# Disk / resource OSError errno values → terminal (not transient network).
_DISK_ERRNOS = {
    errno.ENOSPC,
    errno.EIO,
    getattr(errno, "EDQUOT", 122),  # Windows may lack EDQUOT
}


class FailureClassifier:
    """异常 → FailureCategory 映射器。"""

    # 可重试的内置异常类型（网络向；磁盘 OSError 单独处理）
    _TRANSIENT_EXCEPTION_TYPES = {
        ConnectionError,
        TimeoutError,
        ConnectionRefusedError,
        ConnectionResetError,
        BrokenPipeError,
    }

    # 不可重试的内置异常类型
    _TERMINAL_EXCEPTION_TYPES = {
        KeyError,
        TypeError,
        AttributeError,
        NotImplementedError,
        MemoryError,
    }

    @classmethod
    def classify(cls, exc: Exception) -> FailureCategory:
        """把异常分类为 FailureCategory。"""
        # 已经是 BridgeExecutionError：直接取其 category
        from app.services.bridge_protocol import BridgeExecutionError

        if isinstance(exc, BridgeExecutionError):
            return exc.category

        # Stub / GIS raster ops（算法包）—— 优先于泛化 ValueError
        exc_name = type(exc).__name__
        if exc_name == "RasterOpsValidationError":
            return FailureCategory.validation_error
        if exc_name == "RasterOpsDataError":
            return FailureCategory.not_found
        if exc_name in {"SoftTimeLimitExceeded", "TimeLimitExceeded"}:
            return FailureCategory.timeout

        if isinstance(exc, FileNotFoundError):
            # 本地目录缺数（如 No FY HDF files found in …）→ coverage_gap，
            # 供前端源路由 / 计划框升级；泛化路径缺失仍用 not_found。
            if cls._is_coverage_gap_message(str(exc).lower()):
                return FailureCategory.coverage_gap
            return FailureCategory.not_found
        if isinstance(exc, MemoryError):
            return FailureCategory.terminal_failure

        # 按 HTTP 状态码分类前：先看消息是否已能判定缺数/校验等终态，
        # 避免 job HTTP 500 把「本地无 HDF」/「缺 start_date」误标为
        # transient_upstream 空转重试。
        message_early = str(exc).lower()
        if cls._is_coverage_gap_message(message_early):
            return FailureCategory.coverage_gap
        if any(
            kw in message_early
            for kw in (
                "validation",
                "invalid",
                "参数错误",
                "校验失败",
                "requires start_date",
                "需要时间范围",
            )
        ):
            return FailureCategory.validation_error

        # 按 HTTP 状态码分类（若异常带 status_code 属性）
        status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if isinstance(status_code, int):
            return cls._classify_http_status(status_code)

        # 按异常消息关键词分类（须先于泛化 ValueError → validation_error，
        # 以便 coverage_gap / 缺数类 ValueError 能被正确归类）
        message = message_early
        if cls._is_coverage_gap_message(message):
            return FailureCategory.coverage_gap
        if any(
            kw in message for kw in ("timeout", "timed out", "超时", "soft time limit")
        ):
            return FailureCategory.timeout
        # 数据拉取节点部分失败（ssh_sync/nsidc/gldas 下载）：
        # 增量跳过 + 断点续传使重跑只补失败文件，归 partial_success 可重试
        if (
            "completed with" in message
            and "failures" in message
            and any(
                node in message
                for node in ("ssh_sync", "nsidc_smap_download", "gldas_download")
            )
        ):
            return FailureCategory.partial_success
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
            kw in message
            for kw in (
                "validation",
                "invalid",
                "参数错误",
                "校验失败",
                "requires start_date",
                "需要时间范围",
            )
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

        if isinstance(exc, ValueError):
            # 参数 / 契约类 ValueError → 校验失败（不可重试）
            return FailureCategory.validation_error

        # 磁盘耗尽等 OSError：终态；其余网络向 OSError 仍可重试
        if isinstance(exc, OSError):
            err_no = getattr(exc, "errno", None)
            if err_no in _DISK_ERRNOS:
                return FailureCategory.terminal_failure
            message_os = str(exc).lower()
            if any(kw in message_os for kw in ("no space", "disk", "quota", "磁盘")):
                return FailureCategory.terminal_failure

        # 按异常类型分类
        for exc_type in cls._TRANSIENT_EXCEPTION_TYPES:
            if isinstance(exc, exc_type):
                return FailureCategory.transient_network
        if isinstance(exc, OSError):
            return FailureCategory.transient_network
        for exc_type in cls._TERMINAL_EXCEPTION_TYPES:
            if isinstance(exc, exc_type):
                return FailureCategory.terminal_failure

        # 默认：不可重试（保守策略，避免无限重试未知错误）
        return FailureCategory.terminal_failure

    @staticmethod
    def _is_coverage_gap_message(message: str) -> bool:
        """本地/请求窗缺数（零交集、无可用日期、目录无产品文件等）→ coverage_gap。"""
        return any(
            kw in message
            for kw in (
                "error_code=coverage_gap",
                "coverage_gap",
                "零交集",
                "本地无数据",
                "无可用日期",
                "no overlapping dates",
                "zero intersection",
                "requested date/file may not be available",
                "requested date is not available",
                "日期数据不可用",
                "目标日期无数据",
                # FY / 本地目录扫空（ingest/fy.py FileNotFoundError）
                "no fy hdf",
                "hdf files found",
                "files found in",
                "no matching files",
                "no files found",
            )
        )

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
