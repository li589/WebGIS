"""
GEE 配置 API 路由

提供以下端点：
- GET /gee/config - 获取 GEE 配置信息
- GET /gee/config/limits - 获取任务并发限制
- GET /gee/config/status - 获取 GEE 运行状态
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.services.gee_parallel_config import gee_config_service, TaskType


router = APIRouter(prefix="/gee/config", tags=["gee-config"])


class ParallelConfig(BaseModel):
    """并行配置"""

    max_parallel_exports: int
    max_parallel_uploads: int
    max_parallel_downloads: int
    account_cooldown_seconds: int
    max_tasks_per_account: int


class GEEConfigResponse(BaseModel):
    """GEE 配置响应"""

    enabled: bool
    parallel_config: ParallelConfig
    storage_backend: str
    local_storage_root: str
    credentials_encryption_enabled: bool
    api_account_management_enabled: bool


class TaskLimit(BaseModel):
    """任务限制"""

    max_concurrent: int
    active: int
    available: int


class GEEConfigLimitsResponse(BaseModel):
    """GEE 任务限制响应"""

    export: TaskLimit
    upload: TaskLimit
    download: TaskLimit


class GEEConcurrencyStats(BaseModel):
    """GEE 并发统计"""

    active_exports: int
    active_uploads: int
    active_downloads: int
    active_accounts: int
    queued_tasks: int


class GEEStatusResponse(BaseModel):
    """GEE 状态响应"""

    enabled: bool
    gee_available: bool
    concurrency_stats: GEEConcurrencyStats
    task_limits: GEEConfigLimitsResponse


@router.get("", response_model=GEEConfigResponse)
async def get_gee_config():
    """
    获取 GEE 配置信息

    Returns:
        GEE 配置详情，包括并行配置、存储配置等
    """
    return GEEConfigResponse(**gee_config_service.get_config_summary())


@router.get("/limits", response_model=GEEConfigLimitsResponse)
async def get_task_limits():
    """
    获取任务并发限制

    Returns:
        各类任务的最大并发数、当前活动数、可用槽位数
    """
    return GEEConfigLimitsResponse(
        export=TaskLimit(**gee_config_service.get_task_limits(TaskType.EXPORT_IMAGE)),
        upload=TaskLimit(**gee_config_service.get_task_limits(TaskType.UPLOAD_ASSET)),
        download=TaskLimit(**gee_config_service.get_task_limits(TaskType.DOWNLOAD)),
    )


@router.get("/status", response_model=GEEStatusResponse)
async def get_gee_status():
    """
    获取 GEE 运行状态

    Returns:
        GEE 启用状态、可用性、并发统计、任务限制
    """
    try:
        # 尝试检查 GEE 是否可用
        gee_available = True
        try:
            import ee

            if not ee.Initialize.__doc__:
                gee_available = False
        except Exception:
            gee_available = False

        stats = gee_config_service.task_queue.stats
        return GEEStatusResponse(
            enabled=settings.gee_enabled,
            gee_available=gee_available,
            concurrency_stats=GEEConcurrencyStats(
                active_exports=stats.active_exports,
                active_uploads=stats.active_uploads,
                active_downloads=stats.active_downloads,
                active_accounts=0,  # 需要从账户池获取
                queued_tasks=0,  # 需要从任务队列获取
            ),
            task_limits=GEEConfigLimitsResponse(
                export=TaskLimit(
                    **gee_config_service.get_task_limits(TaskType.EXPORT_IMAGE)
                ),
                upload=TaskLimit(
                    **gee_config_service.get_task_limits(TaskType.UPLOAD_ASSET)
                ),
                download=TaskLimit(
                    **gee_config_service.get_task_limits(TaskType.DOWNLOAD)
                ),
            ),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get GEE status: {str(e)}"
        )


@router.get("/environment")
async def get_gee_environment():
    """
    获取 GEE 环境变量配置（脱敏）

    Returns:
        GEE 相关环境变量配置（不包含敏感信息）
    """
    return {
        "gee_enabled": settings.gee_enabled,
        "gee_module_root": settings.gee_module_root,
        "gee_storage_backend": settings.gee_storage_backend,
        "gee_local_storage_root": settings.gee_local_storage_root,
        "gee_credentials_encryption_key_set": bool(
            settings.gee_credentials_encryption_key
        ),
        "gee_credentials_db_path": settings.gee_credentials_db_path,
        "gee_api_account_management_enabled": settings.gee_api_account_management_enabled,
    }
