import logging
import threading
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    algorithm_router,
    analysis_router,
    artifact_router,
    data_io_router,
    feedback_router,
    health_router,
    import_router,
    layer_router,
    provider_router,
    runtime_router,
    weather_router,
    workflow_router,
    workspace_router,
    zonal_stats_router,
)
from app.api.routers.unified_tile_router import router as unified_tile_router
from app.api.weather_tile_routes import router as weather_tile_router
from app.api.gee_config_routes import router as gee_config_router
from app.api.config_routes import router as config_router
from app.api.routers.workflow_definition_router import (
    router as workflow_definition_router,
)
from app.api.routers.workflow_timer_router import router as workflow_timer_router
from app.api.routers.cleanup_router import router as cleanup_router
from app.api.routers.auth_router import router as auth_router
from app.core.config import settings
from app.core.logging import ensure_logging_configured, log_context, set_request_id
from app.core.redis_client import record_request_metric
from app.gee.core.src.webgis_gee.api.routes import (
    create_api_router as create_gee_router,
)
from app.services.providers import register_default_providers
from app.services.workflow.service_container import follow_up_dispatch_service

logger = logging.getLogger(__name__)

ensure_logging_configured()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时清理上一会话遗留的僵尸工作流（accepted/queued/running/retry_pending）
    # 这些工作流在进程重启后不会再被 Celery worker 消费，会永久卡住
    try:
        cleaned = follow_up_dispatch_service.cleanup_stale_workflow_runs()
        if cleaned > 0:
            logger.info(
                "Startup cleanup: marked %d stale workflow run(s) as failed", cleaned
            )
    except Exception:  # noqa: BLE001 — 启动清理失败不应阻断服务启动
        logger.exception("Failed to cleanup stale workflow runs on startup")

    # 后台预热 provider dataset helpers 缓存，避免首次 /layers 请求阻塞
    # 在后台线程运行，不阻塞服务启动
    def _warmup():
        try:
            from app.services.workflow_request_resolver import warm_provider_helpers

            if warm_provider_helpers():
                logger.info("Provider dataset helpers warmed up successfully")
            else:
                logger.warning(
                    "Provider dataset helpers warmup returned None — /layers may be slow on first call"
                )
        except Exception:  # noqa: BLE001 — 后台预热失败不应影响服务可用性
            logger.exception("Failed to warm up provider dataset helpers")

    threading.Thread(target=_warmup, daemon=True, name="provider-warmup").start()

    # 可用数据集注册表：从算法包 DATASET_REGISTRY 同步内置条目（失败仅告警）
    try:
        from app.services.dataset_registry_service import sync_algorithm_datasets

        synced = sync_algorithm_datasets()
        if synced:
            logger.info(
                "Dataset registry: synced %d entrie(s) from algorithm package",
                synced,
            )
    except Exception:  # noqa: BLE001 — 同步失败不应阻断启动
        logger.exception("Failed to sync dataset registry on startup")

    # 预热 psutil CPU 采样：cpu_percent(interval=None) 首次调用返回 0.0（psutil 语义），
    # 提前调用一次使后续 get_resource_usage() 能拿到真实值
    try:
        import psutil

        psutil.cpu_percent(interval=None)
        logger.debug("psutil cpu_percent warmup done")
    except (ImportError, OSError, RuntimeError):
        logger.debug("psutil warmup skipped (import or call failed)")

    # 注册默认天气源 Provider 到全局注册表
    # 使 /config/weather/providers 端点能查询到已注册的天气源
    try:
        from app.weatherengine.provider_registry import register_default_providers

        register_default_providers()
        # 应用 DB 中持久化的覆盖配置（enabled/priority/config）
        from app.services.config_service import apply_persisted_provider_overrides

        apply_persisted_provider_overrides()
    except Exception:  # noqa: BLE001 — 天气源注册失败不应阻断启动
        logger.exception("Failed to register default weather providers")

    # 单一配置投影：env + DB api keys + runtime overrides
    try:
        from app.services.effective_config import (
            assert_data_root_policy,
            assert_deployment_config_policy,
            assert_dev_bypass_policy,
            hydrate_effective_config,
        )

        hydrate_effective_config()
        assert_data_root_policy()
        assert_deployment_config_policy()
        assert_dev_bypass_policy()
    except Exception:  # noqa: BLE001 — 配置初始化失败须记录后终止启动
        logger.exception("Failed to hydrate effective config on startup")
        raise

    try:
        from app.services.auth_bootstrap import bootstrap_auth

        bootstrap_auth()
    except Exception:  # noqa: BLE001 — 鉴权初始化失败须记录后终止启动
        logger.exception("Failed to bootstrap user auth on startup")
        raise

    # 清理过期导入 staging（TTL 见 STAGING_TTL_SECONDS）
    try:
        from app.data_io.services.upload import cleanup_expired_staging

        removed = cleanup_expired_staging()
        if removed:
            logger.info(
                "Startup cleanup: removed %d expired import staging dir(s)", removed
            )
    except Exception:  # noqa: BLE001 — 过期 staging 清理失败不应阻断启动
        logger.exception("Failed to cleanup expired import staging")

    yield


def create_app() -> FastAPI:
    # 安全审计 2026-08-20：交互式文档（/docs /redoc）按环境默认禁用
    # （production/test 默认 404，BACKEND_DOCS_ENABLED 可覆盖）。
    # /openapi.json 保持开放（供工具调用）；export_openapi.py /
    # check_openapi_drift.py 直接调用 app.openapi()，与路由无关，不受影响。
    _docs_enabled = settings.docs_enabled
    app = FastAPI(
        title=settings.service_name,
        version="0.1.0",
        description="Minimal backend service for the geographic analysis platform.",
        lifespan=lifespan,
        docs_url="/docs" if _docs_enabled else None,
        redoc_url="/redoc" if _docs_enabled else None,
    )

    # P2-11: 注册统一瓦片提供者（BaseMap + Weather）—— 从模块级移入 create_app()
    register_default_providers()
    _origins = settings.cors_origins
    if not _origins:
        raise ValueError(
            "CORS origins must be explicitly configured. "
            "Do not set BACKEND_CORS_ORIGINS to empty — list specific origins instead of '*'."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-API-Key",
            "X-Request-ID",
        ],
    )

    # ── 安全响应头中间件 ──────────────────────────────────────────
    # P0 修复：注入 X-Frame-Options / X-Content-Type-Options / HSTS / Referrer-Policy
    # / Permissions-Policy / Content-Security-Policy（仅生产环境）。
    # 开发环境不设 CSP 与 HSTS，避免阻断 Vite HMR 的 inline script。
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        env = (settings.environment or "").lower()
        is_prod = env not in {"development", "dev", "test", "testing"}

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-same-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )

        if is_prod:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob: https:; "
                "connect-src 'self' https:; "
                "font-src 'self' data:; "
                "frame-ancestors 'none'"
            )

        return response

    # 发布就绪修复（P1-2）：写接口/登录/天气瓦片的 IP 级限流（超阈 429 + C429001）。
    # P0-10 产品定位决策：目标用户为课题组/研究院（访问量小），限流宽松化，
    # 且 development/test 环境旁路（开发、调试时关闭 IP 限制），仅 production 生效。
    # 限流计数走 Redis 集中计数（多进程共享阈值），Redis 不可用时降级进程内计数。
    @app.middleware("http")
    async def write_rate_limit_middleware(request: Request, call_next):
        from app.api.rate_limit import (
            check_feedback_upload_rate_limit,
            check_login_rate_limit,
            check_weather_tile_rate_limit,
            check_write_rate_limit,
            client_ip,
            rate_limited_response,
            should_rate_limit_feedback_upload,
            should_rate_limit_login,
            should_rate_limit_weather_tile,
            should_rate_limit_write,
        )

        path = request.url.path
        method = request.method
        env = (settings.environment or "").lower()
        request_id = getattr(request.state, "request_id", None)

        # /health 为存活探测：不进限流检查，保证高负载时仍可即时应答
        if path == "/health":
            return await call_next(request)

        if env not in ("test", "testing", "development"):
            if should_rate_limit_login(path, method):
                result = check_login_rate_limit(client_ip(request))
                if not result.allowed:
                    return rate_limited_response(
                        result.retry_after_seconds,
                        message="登录尝试过于频繁，请稍后再试。",
                        request_id=request_id,
                    )
            if should_rate_limit_write(path, method):
                result = check_write_rate_limit(client_ip(request))
                if not result.allowed:
                    return rate_limited_response(
                        result.retry_after_seconds,
                        message="写请求过于频繁，请稍后再试。",
                        request_id=request_id,
                    )
            if should_rate_limit_weather_tile(path, method):
                result = check_weather_tile_rate_limit(client_ip(request))
                if not result.allowed:
                    return rate_limited_response(
                        result.retry_after_seconds,
                        message="天气瓦片请求过于频繁，请稍后再试。",
                        request_id=request_id,
                    )
            # 问题反馈匿名上传（公开写面，无鉴权）：更严阈值，防灌盘
            if should_rate_limit_feedback_upload(path, method):
                result = check_feedback_upload_rate_limit(client_ip(request))
                if not result.allowed:
                    return rate_limited_response(
                        result.retry_after_seconds,
                        message="反馈上传过于频繁，请稍后再试。",
                        request_id=request_id,
                    )
        return await call_next(request)

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id", f"req-{uuid4().hex[:12]}")
        request.state.request_id = request_id

        # /health 为存活探测：跳过 Redis 指标记录与访问日志，
        # 避免高负载（Redis 抖动/线程池排队）时健康检查被拖慢导致前端误报断联
        if request.url.path == "/health":
            return await call_next(request)

        set_request_id(request_id)
        start_time = time.monotonic()
        with log_context(request_id=request_id):
            try:
                response = await call_next(request)
                response.headers["x-request-id"] = request_id
                duration_ms = (time.monotonic() - start_time) * 1000
                # 记录请求耗时指标到 Redis（按端点+日期分桶）
                try:
                    route = request.scope.get("route")
                    path_pattern = getattr(route, "path", None) or request.url.path
                    record_request_metric(
                        method=request.method,
                        path_pattern=path_pattern,
                        status_code=response.status_code,
                        duration_ms=duration_ms,
                    )
                except Exception:  # noqa: BLE001 — Redis 指标记录（含 RedisError）失败不应影响请求热路径
                    pass  # 指标记录不应影响正常请求
                logger.info(
                    "HTTP request completed",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": round(duration_ms, 1),
                    },
                )
                return response
            finally:
                set_request_id(None)

    # P2-4: Service 层领域异常 → HTTP 响应（在 StarletteHTTPException 之前注册）
    from app.services.errors import ServiceError

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": request_id},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        request_id = getattr(request.state, "request_id", None)
        content: dict = {"detail": exc.detail, "request_id": request_id}
        # 业务错误码（ApiError）：统一输出 error_code，见 app/api/error_codes.py
        error_code = getattr(exc, "error_code", None)
        if error_code:
            content["error_code"] = error_code
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        request_id = getattr(request.state, "request_id", None)
        # exc.errors() 的 ctx 可能携带 model_validator 抛出的原始 ValueError 对象，
        # 直接进 JSONResponse 会 TypeError → 500；jsonable_encoder 递归降级为可序列化值
        return JSONResponse(
            status_code=422,
            content={
                "detail": jsonable_encoder(exc.errors()),
                "request_id": request_id,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", None)
        with log_context(request_id=request_id):
            logger.exception("Unhandled API exception")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(feedback_router)
    app.include_router(layer_router)
    app.include_router(workflow_router)
    app.include_router(analysis_router)
    app.include_router(runtime_router)
    app.include_router(algorithm_router)
    app.include_router(weather_router)
    app.include_router(provider_router)
    app.include_router(artifact_router)
    app.include_router(import_router)
    app.include_router(data_io_router)
    app.include_router(unified_tile_router)
    app.include_router(weather_tile_router)
    app.include_router(gee_config_router)
    app.include_router(config_router)
    app.include_router(workflow_definition_router)
    app.include_router(workflow_timer_router)
    app.include_router(cleanup_router)
    app.include_router(zonal_stats_router)
    app.include_router(workspace_router)

    # 挂载 GEE engine router，使 /gee/* 路由正式接入 FastAPI
    # 路由前缀已在 create_gee_router 内部定义为 /gee
    try:
        gee_router = create_gee_router()
        app.include_router(gee_router)
    except Exception:  # noqa: BLE001 — GEE 为可选后端，挂载失败仅告警
        logger.warning(
            "GEE router failed to mount — GEE backend may not be installed or configured."
        )

    return app


app = create_app()
