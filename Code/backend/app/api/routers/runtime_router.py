from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.api.deps import require_write_access
from app.services.api_config import ApiProvider, DataType, api_config_manager
from app.services.workflow.service_container import runtime_status_service
from shared.contracts.api_contracts import (
    FrontendCommandRequest,
    FrontendCommandResponse,
    RuntimeConfigUpdateRequest,
    RuntimeConfigUpdateResponse,
    RuntimeStatusResponse,
)

router = APIRouter()


@router.patch(
    "/runtime/config",
    tags=["runtime"],
    response_model=RuntimeConfigUpdateResponse,
    dependencies=[Depends(require_write_access)],
)
def update_runtime_config(payload: RuntimeConfigUpdateRequest) -> RuntimeConfigUpdateResponse:
    try:
        return runtime_status_service.update_runtime_config(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/runtime/config", tags=["runtime"])
def get_runtime_config() -> dict:
    """Return the current runtime configuration snapshot (defaults + DB overrides)."""
    return runtime_status_service.get_runtime_config()


@router.get("/runtime/status", tags=["runtime"], response_model=RuntimeStatusResponse)
def get_runtime_status() -> RuntimeStatusResponse:
    return runtime_status_service.get_runtime_status()


@router.get("/runtime/metrics", tags=["runtime"])
def get_runtime_metrics(date: str | None = None) -> dict:
    """返回各端点的 P50/P95 请求耗时统计（按天聚合，从 Redis 读取）。

    Query params:
        date: YYYY-MM-DD 格式日期，默认当天（UTC）。
    """
    from app.core.redis_client import get_metrics_summary
    return get_metrics_summary(date)


@router.post(
    "/frontend/commands",
    tags=["frontend"],
    response_model=FrontendCommandResponse,
    dependencies=[Depends(require_write_access)],
)
def submit_frontend_command(payload: FrontendCommandRequest) -> FrontendCommandResponse:
    return runtime_status_service.submit_frontend_command(payload)


# ---------------- API 配置管理接口 ----------------


@router.get("/runtime/api-config", tags=["runtime"])
def get_api_config_status() -> JSONResponse:
    """返回所有 API 配置状态，供前端判断可用数据源。"""
    configs = api_config_manager.get_all_configs()
    serializable_configs = api_config_manager.get_all_configs_serializable()
    return JSONResponse(content=serializable_configs)


@router.get("/runtime/api-config/{provider}", tags=["runtime"])
def get_provider_api_config(provider: str) -> JSONResponse:
    """返回指定 Provider 的 API 配置状态。"""
    try:
        api_provider = ApiProvider(provider)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown provider: {provider}")
    config = api_config_manager.get_config(api_provider)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Config not found for provider: {provider}")
    serializable_config = api_config_manager.get_config_serializable(api_provider)
    return JSONResponse(content=serializable_config)


@router.post(
    "/runtime/api-config/{provider}",
    tags=["runtime"],
    dependencies=[Depends(require_write_access)],
)
def update_provider_api_config(provider: str, config_update: dict) -> JSONResponse:
    """更新指定 Provider 的 API 配置（如 API Key）。"""
    try:
        api_provider = ApiProvider(provider)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown provider: {provider}")
    success = api_config_manager.update_config(api_provider, config_update)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to update config for provider: {provider}")
    return JSONResponse(content={"status": "updated", "provider": provider})


@router.get("/runtime/api-config/{provider}/best", tags=["runtime"])
def get_best_available_api(provider: str) -> JSONResponse:
    """返回指定数据类型中最佳可用的 API Provider。"""
    try:
        data_type = DataType(provider)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown data type: {provider}")
    best = api_config_manager.get_best_available(required_capabilities={data_type})
    if best is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"No available API provider for data type: {provider}")
    return JSONResponse(content={
        "provider": best.provider.value,
        "name": best.name,
        "endpoint_url": best.endpoint.url,
        "capabilities": [c.value for c in best.endpoint.capabilities],
        "priority": best.priority,
    })
