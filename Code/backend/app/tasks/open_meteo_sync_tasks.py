"""
Phase 2: Open-Meteo 本地数据自动同步任务（Celery 封装薄层）。

通过 Celery Beat 定时调用 `docker compose run --rm open-meteo-sync` 触发同步。
- 同步期间旧数据继续可用（sync 是追加/覆盖文件，不删除）
- 同步失败不影响线上服务，下次 beat 触发时重试
- 支持多模型同步（通过 OPEN_METEO_SYNC_DOMAINS 配置）

P3 分层重构（2026-08-23）：锁原语/命令构建/容器管理/同步执行等纯逻辑已
下沉至 ``app/services/open_meteo_sync_executor``（消除 services→tasks 侧向
导入与 tasks→router 反向导入）；本模块只留 Celery 任务封装，并 re-export
全部执行器符号——既有调用方（weather_sync_service 经 executor 正向导入）
与测试（patch/mutate ``open_meteo_sync_tasks.X``，可变对象 re-export 后
mutate 语义不变）零改动。
"""

from __future__ import annotations

from typing import Any

from app.core.celery_app import celery_app, celery_available
from app.core.config import settings
from app.services.open_meteo_sync_executor import (  # noqa: F401 — 兼容 re-export
    _build_sync_command,
    _ensure_sync_volume,
    _sync_domain_key,
    _sync_domains,
    _sync_local_holders,
    _sync_local_lock,
    acquire_open_meteo_sync_lock,
    execute_open_meteo_sync,
    is_open_meteo_sync_locked,
    kill_orphan_sync_containers,
    release_open_meteo_sync_lock,
)

if celery_available and celery_app is not None:

    @celery_app.task(
        name="app.tasks.open_meteo_sync_tasks.sync_open_meteo_data",
        queue=settings.workflow_queue_weather_batch,
        soft_time_limit=3600,
        time_limit=3900,
    )
    def sync_open_meteo_data(domains: str | None = None) -> dict[str, Any]:
        """Celery 任务入口：定时同步本地 Open-Meteo 数据（weather-batch 队列）。

        ``domains`` 可选；Beat 定时调用不传，沿用环境默认。
        """
        return execute_open_meteo_sync(domains=domains)

else:

    def sync_open_meteo_data(domains: str | None = None) -> dict[str, Any]:
        raise RuntimeError(
            "Celery is not installed. Install backend dependencies before using Open-Meteo sync tasks."
        )
