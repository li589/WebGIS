"""长期运行清理任务管理 API 路由

提供后端维护接口，避免长期运行后 SQLite / 缓存文件无限增长：
- POST /cleanup/workflow-runs   手动清理过期 workflow runs
- POST /cleanup/cache           手动清理过期缓存文件
- POST /cleanup/vacuum          VACUUM workflow_state 数据库回收磁盘空间
- GET  /cleanup/stats           返回当前清理统计（不执行清理）
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.api.deps import require_write_access
from app.services.cache_service import cache_service
from app.services.workflow_repository import SQLiteWorkflowRepository
from app.tasks.cleanup_tasks import (
    execute_cache_cleanup,
    execute_workflow_runs_cleanup,
)

router = APIRouter(prefix="/cleanup", tags=["cleanup"])


class WorkflowRunsCleanupRequest(BaseModel):
    """workflow runs 清理请求。"""

    retention_days: int = Field(default=30, ge=1, le=365, description="保留天数")
    vacuum: bool = Field(default=False, description="是否执行 VACUUM 回收磁盘空间")


class WorkflowRunsCleanupResponse(BaseModel):
    """workflow runs 清理响应。"""

    retention_days: int
    runs_deleted: int
    events_deleted: int
    vacuumed: int


class CacheCleanupResponse(BaseModel):
    """缓存清理响应。"""

    deleted: int
    skipped: int
    errors: int


class CleanupStatsResponse(BaseModel):
    """当前清理统计（不执行清理）。"""

    cache_stats: dict[str, Any]
    workflow_runs_stats: dict[str, int]


@router.post(
    "/workflow-runs",
    response_model=WorkflowRunsCleanupResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_write_access)],
)
def cleanup_workflow_runs(request: WorkflowRunsCleanupRequest) -> WorkflowRunsCleanupResponse:
    """手动清理过期的 workflow runs 及其 events。

    清理逻辑：删除 status 为 completed/failed/cancelled 且 updated_at 早于
    retention_days 天前的 run，对应 events 一并删除。

    可选执行 VACUUM 回收磁盘空间（耗时，数据库越大耗时越长）。
    """
    stats = execute_workflow_runs_cleanup(
        retention_days=request.retention_days,
        vacuum=request.vacuum,
    )
    return WorkflowRunsCleanupResponse(
        retention_days=stats["retention_days"],
        runs_deleted=stats["runs_deleted"],
        events_deleted=stats["events_deleted"],
        vacuumed=stats["vacuumed"],
    )


@router.post(
    "/cache",
    response_model=CacheCleanupResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_write_access)],
)
def cleanup_cache() -> CacheCleanupResponse:
    """手动清理已过期的缓存文件。

    扫描 cache_service 的 cache_dir，删除所有 expires_at 已过期的 JSON 文件。
    损坏的缓存文件也会被删除以避免持续报错。
    """
    stats = execute_cache_cleanup()
    return CacheCleanupResponse(
        deleted=stats["deleted"],
        skipped=stats["skipped"],
        errors=stats["errors"],
    )


@router.post(
    "/vacuum",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_write_access)],
)
def vacuum_workflow_state() -> dict[str, Any]:
    """VACUUM workflow_state.sqlite3 回收磁盘空间。

    在清理 workflow runs 后执行可回收磁盘空间。耗时较长，建议低峰期执行。
    """
    import logging

    logger = logging.getLogger(__name__)
    try:
        repository = SQLiteWorkflowRepository()
        with repository._connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("VACUUM")
        logger.info("vacuum_workflow_state: VACUUM completed")
        return {"vacuumed": True}
    except Exception as exc:
        logger.exception("vacuum_workflow_state failed")
        return {"vacuumed": False, "error": str(exc)}


@router.get(
    "/stats",
    response_model=CleanupStatsResponse,
    status_code=status.HTTP_200_OK,
)
def get_cleanup_stats() -> CleanupStatsResponse:
    """返回当前清理统计（不执行清理）。

    包含：
    - cache_stats：缓存命中率、过期数、总数、各 scope 分布
    - workflow_runs_stats：active / completed / failed 数量
    """
    cache_stats_obj = cache_service.get_stats()
    cache_stats = {
        "hits": cache_stats_obj.hits,
        "misses": cache_stats_obj.misses,
        "upserts": cache_stats_obj.upserts,
        "evictions": cache_stats_obj.evictions,
        "total_entries": cache_stats_obj.total_entries,
        "fresh_entries": cache_stats_obj.fresh_entries,
        "expired_entries": cache_stats_obj.expired_entries,
        "scopes": cache_stats_obj.scopes,
        "hit_rate": cache_stats_obj.hit_rate,
    }

    repository = SQLiteWorkflowRepository()
    active_count = repository.count_active_runs()

    # 统计终态数量
    from app.services.workflow_repository import _TERMINAL_STATUSES
    terminal_counts: dict[str, int] = {}
    try:
        with repository._connect() as connection:
            for terminal_status in _TERMINAL_STATUSES:
                cursor = connection.execute(
                    "SELECT COUNT(*) FROM workflow_runs WHERE status = ?",
                    (terminal_status,),
                )
                row = cursor.fetchone()
                terminal_counts[terminal_status] = int(row[0]) if row else 0
    except Exception:
        pass

    return CleanupStatsResponse(
        cache_stats=cache_stats,
        workflow_runs_stats={
            "active": active_count,
            **terminal_counts,
        },
    )
