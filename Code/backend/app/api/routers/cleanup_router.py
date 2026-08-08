"""长期运行清理任务管理 API 路由

提供后端维护接口，避免长期运行后 SQLite / 缓存文件无限增长：
- POST /cleanup/workflow-runs   手动清理过期 workflow runs
- POST /cleanup/cache           手动清理过期缓存文件
- POST /cleanup/vacuum          VACUUM workflow_state 数据库回收磁盘空间
- GET  /cleanup/stats           返回当前清理统计（不执行清理）
- GET  /cleanup/node-caches     列出工作流节点产物缓存（路径/大小/文件数）
- POST /cleanup/node-caches     清理工作流节点产物缓存（可指定模块）
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.api.deps import require_config_read_access, require_write_access
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
def cleanup_workflow_runs(
    request: WorkflowRunsCleanupRequest,
) -> WorkflowRunsCleanupResponse:
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
    dependencies=[Depends(require_config_read_access)],
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


# ─── 工作流节点产物缓存（omega 分块反演等算法模块输出） ─────────────────────


class NodeCacheEntry(BaseModel):
    """单个算法模块的产物缓存条目。"""

    name: str
    path: str
    size_bytes: int
    file_count: int
    modified_at: str | None


class NodeCacheListResponse(BaseModel):
    """节点缓存清单（不执行清理）。"""

    entries: list[NodeCacheEntry]
    total_bytes: int


class NodeCacheCleanupRequest(BaseModel):
    """节点缓存清理请求；names 为空表示全部清理。"""

    names: list[str] | None = Field(
        default=None, description="要清理的模块名列表；空=全部"
    )


class NodeCacheCleanupResponse(BaseModel):
    """节点缓存清理响应。"""

    deleted: list[str]
    failed: list[str]
    freed_bytes: int


def _node_cache_root() -> Path:
    from app.core.config import settings

    return Path(getattr(settings, "python_provider_workspace", "") or "") / "products"


def _scan_node_caches() -> list[NodeCacheEntry]:
    """扫描产物目录下的模块缓存（仅一层子目录）。"""
    root = _node_cache_root()
    entries: list[NodeCacheEntry] = []
    if not root.is_dir():
        return entries
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        files = [f for f in child.rglob("*") if f.is_file()]
        size = sum(f.stat().st_size for f in files)
        mtime = max((f.stat().st_mtime for f in files), default=0)
        modified = (
            datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            if mtime
            else None
        )
        entries.append(
            NodeCacheEntry(
                name=child.name,
                path=str(child),
                size_bytes=size,
                file_count=len(files),
                modified_at=modified,
            )
        )
    return entries


@router.get(
    "/node-caches",
    response_model=NodeCacheListResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_config_read_access)],
)
def list_node_caches() -> NodeCacheListResponse:
    """列出工作流节点产物缓存（每个算法模块的目录/大小/文件数/最近修改）。"""
    entries = _scan_node_caches()
    return NodeCacheListResponse(
        entries=entries,
        total_bytes=sum(e.size_bytes for e in entries),
    )


@router.post(
    "/node-caches",
    response_model=NodeCacheCleanupResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_write_access)],
)
def cleanup_node_caches(
    request: NodeCacheCleanupRequest,
) -> NodeCacheCleanupResponse:
    """清理工作流节点产物缓存（默认全部；可指定模块名）。

    安全约束：仅删除 products/ 下的直接子目录，路径白名单校验，
    绝不触碰目录外的任何文件。
    """
    import shutil

    root = _node_cache_root()
    if not root.is_dir():
        return NodeCacheCleanupResponse(deleted=[], failed=[], freed_bytes=0)

    existing = {e.name: e for e in _scan_node_caches()}
    targets = list(request.names or []) if request.names else list(existing.keys())

    deleted: list[str] = []
    failed: list[str] = []
    freed = 0
    for name in targets:
        entry = existing.get(name)
        if entry is None:
            failed.append(name)
            continue
        target = Path(entry.path)
        # 白名单：必须是 products 的直接子目录
        if target.parent.resolve() != root.resolve():
            failed.append(name)
            continue
        try:
            shutil.rmtree(target)
            freed += entry.size_bytes
            deleted.append(name)
        except OSError:
            failed.append(name)

    return NodeCacheCleanupResponse(
        deleted=deleted,
        failed=failed,
        freed_bytes=freed,
    )
