import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    algorithm_router,
    artifact_router,
    data_io_router,
    health_router,
    import_router,
    layer_router,
    provider_router,
    remote_browser_router,
    runtime_router,
    weather_router,
    workflow_router,
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
from app.core.config import settings
from app.core.logging import ensure_logging_configured, log_context, set_request_id
from app.core.redis_client import record_request_metric
from app.gee.core.src.webgis_gee.api.routes import (
    create_api_router as create_gee_router,
)
from app.services.providers import register_default_providers
from app.services.workflow.service_container import follow_up_dispatch_service

# 注册统一瓦片提供者（BaseMap + Weather）
register_default_providers()

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
    except Exception:
        logger.exception("Failed to cleanup stale workflow runs on startup")

    # 后台预热 provider dataset helpers 缓存，避免首次 /layers 请求阻塞
    # 在后台线程运行，不阻塞服务启动
    import threading

    def _warmup():
        try:
            from app.services.workflow_request_resolver import warm_provider_helpers

            if warm_provider_helpers():
                logger.info("Provider dataset helpers warmed up successfully")
            else:
                logger.warning(
                    "Provider dataset helpers warmup returned None — /layers may be slow on first call"
                )
        except Exception:
            logger.exception("Failed to warm up provider dataset helpers")

    threading.Thread(target=_warmup, daemon=True, name="provider-warmup").start()

    # 注册默认天气源 Provider 到全局注册表
    # 使 /config/weather/providers 端点能查询到已注册的天气源
    try:
        from app.weatherengine.provider_registry import register_default_providers

        register_default_providers()
        # 应用 DB 中持久化的覆盖配置（enabled/priority/config）
        from app.services.config_service import apply_persisted_provider_overrides

        apply_persisted_provider_overrides()
    except Exception:
        logger.exception("Failed to register default weather providers")

    # 单一配置投影：env + DB api keys + runtime overrides
    try:
        from app.services.effective_config import (
            assert_data_root_policy,
            hydrate_effective_config,
        )

        hydrate_effective_config()
        assert_data_root_policy()
    except Exception:
        logger.exception("Failed to hydrate effective config on startup")
        raise

    # 清理过期导入 staging（TTL 见 STAGING_TTL_SECONDS）
    try:
        from app.data_io.services.upload import cleanup_expired_staging

        removed = cleanup_expired_staging()
        if removed:
            logger.info(
                "Startup cleanup: removed %d expired import staging dir(s)", removed
            )
    except Exception:
        logger.exception("Failed to cleanup expired import staging")

    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.service_name,
        version="0.1.0",
        description="Minimal backend service for the geographic analysis platform.",
        lifespan=lifespan,
    )
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
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 发布就绪修复（P1-2）：/config 与 /import 写接口的 IP 级限流（超阈 429）。
    # P0-10 产品定位决策：目标用户为课题组/研究院（访问量小），限流宽松化，
    # 且 development/test 环境旁路（开发、调试时关闭 IP 限制），仅 production 生效。
    @app.middleware("http")
    async def write_rate_limit_middleware(request: Request, call_next):
        if (settings.environment or "").lower() not in (
            "test",
            "testing",
            "development",
        ):
            from app.api.rate_limit import (
                check_write_rate_limit,
                client_ip,
                should_rate_limit_write,
            )

            if should_rate_limit_write(request.url.path, request.method):
                if not check_write_rate_limit(client_ip(request)):
                    from fastapi.responses import JSONResponse

                    return JSONResponse(
                        status_code=429,
                        content={"detail": "写请求过于频繁，请稍后再试。"},
                    )
        return await call_next(request)

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id", f"req-{uuid4().hex[:12]}")
        request.state.request_id = request_id
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
                except Exception:
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
    app.include_router(layer_router)
    app.include_router(workflow_router)
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
    app.include_router(remote_browser_router)

    # 挂载 GEE engine router，使 /gee/* 路由正式接入 FastAPI
    # 路由前缀已在 create_gee_router 内部定义为 /gee
    try:
        gee_router = create_gee_router()
        app.include_router(gee_router)
    except Exception:
        logger.warning(
            "GEE router failed to mount — GEE backend may not be installed or configured."
        )

    return app


app = create_app()
