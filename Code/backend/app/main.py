import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.tile_routes import router as tile_router
from app.api.gee_config_routes import router as gee_config_router
from app.core.config import settings
from app.core.logging import ensure_logging_configured, log_context, set_request_id
from app.gee.core.src.webgis_gee.api.routes import create_api_router as create_gee_router

logger = logging.getLogger(__name__)

ensure_logging_configured()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.service_name,
        version="0.1.0",
        description="Minimal backend service for the geographic analysis platform.",
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

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id", f"req-{uuid4().hex[:12]}")
        request.state.request_id = request_id
        set_request_id(request_id)
        with log_context(request_id=request_id):
            try:
                response = await call_next(request)
                response.headers["x-request-id"] = request_id
                logger.info(
                    "HTTP request completed",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
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

    app.include_router(router)
    app.include_router(tile_router)
    app.include_router(gee_config_router)

    # 挂载 GEE engine router，使 /gee/* 路由正式接入 FastAPI
    # 路由前缀已在 create_gee_router 内部定义为 /gee
    try:
        gee_router = create_gee_router()
        app.include_router(gee_router)
    except Exception:
        logger.warning("GEE router failed to mount — GEE backend may not be installed or configured.")

    return app


app = create_app()
