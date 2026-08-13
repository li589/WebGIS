"""Service-layer domain exceptions.

P2-4: Service 层不应直接依赖 FastAPI 的 HTTPException。
定义领域异常，由 Router 层或全局异常处理器转换为 HTTP 响应。

用法：
    # service 层
    from app.services.errors import OverlayNotFoundError
    raise OverlayNotFoundError(f"No overlay for layer: {layer_id}")

    # main.py 全局异常处理器（已注册）
    # 自动将 ServiceError 子类转换为对应 status_code 的 JSONResponse
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for service-layer domain errors.

    Each subclass sets a default ``status_code`` that the global
    exception handler uses to produce the HTTP response.
    """

    status_code: int = 500
    detail: str = "Service error"

    def __init__(
        self, detail: str | None = None, status_code: int | None = None
    ) -> None:
        self.detail = detail or self.__class__.__doc__ or self.detail
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.detail)


# ── Overlay 域 ───────────────────────────────────────────────────────────────


class OverlayNotFoundError(ServiceError):
    """Overlay 层或关联文件未找到。"""

    status_code = 404


class OverlayValidationError(ServiceError):
    """Overlay 请求参数校验失败（如缺少 time 参数）。"""

    status_code = 400


class OverlayConfigError(ServiceError):
    """Overlay 配置缺失或无效（内部错误）。"""

    status_code = 500


# ── TileProxy 域 ─────────────────────────────────────────────────────────────


class TileProxyError(ServiceError):
    """瓦片代理请求参数错误（如未知 provider）。"""

    status_code = 400


class TileProxyConfigError(ServiceError):
    """瓦片代理配置缺失（如未配置 API Key）。"""

    status_code = 503


class TileProxyUpstreamError(ServiceError):
    """瓦片上游源暂时不可用。"""

    status_code = 502
