"""
GEE 并行配置服务

提供 GEE 任务的并行控制、账户池管理、导出任务调度等功能
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from app.core.config import settings


logger = logging.getLogger(__name__)


class TaskType(Enum):
    """GEE 任务类型"""

    EXPORT_IMAGE = "export_image"
    EXPORT_TABLE = "export_table"
    UPLOAD_ASSET = "upload_asset"
    DOWNLOAD = "download"


@dataclass
class GEEParallelConfig:
    """GEE 并行配置"""

    # 最大并行导出任务数
    max_parallel_exports: int = 2
    # 最大并行上传任务数
    max_parallel_uploads: int = 4
    # 最大并行下载任务数
    max_parallel_downloads: int = 4
    # 账户冷却时间（秒）
    account_cooldown_seconds: int = 300
    # 单个账户最大并发任务数
    max_tasks_per_account: int = 1
    # 账户池预热数量
    account_pool_warm_size: int = 1


@dataclass
class GEEAccountInfo:
    """GEE 账户信息"""

    email: str
    is_active: bool = True
    is_available: bool = True
    current_tasks: int = 0
    last_used: Optional[datetime] = None
    error_count: int = 0


@dataclass
class GEEConcurrencyStats:
    """GEE 并发统计"""

    active_exports: int = 0
    active_uploads: int = 0
    active_downloads: int = 0
    active_accounts: int = 0
    queued_tasks: int = 0


class GEETaskQueue:
    """GEE 任务队列（内存实现）"""

    def __init__(self, config: GEEParallelConfig):
        self.config = config
        self._export_semaphore: asyncio.Semaphore = asyncio.Semaphore(
            config.max_parallel_exports
        )
        self._upload_semaphore: asyncio.Semaphore = asyncio.Semaphore(
            config.max_parallel_uploads
        )
        self._download_semaphore: asyncio.Semaphore = asyncio.Semaphore(
            config.max_parallel_downloads
        )
        self._stats = GEEConcurrencyStats()
        self._locks = {
            TaskType.EXPORT_IMAGE: asyncio.Lock(),
            TaskType.EXPORT_TABLE: asyncio.Lock(),
            TaskType.UPLOAD_ASSET: asyncio.Lock(),
            TaskType.DOWNLOAD: asyncio.Lock(),
        }

    def get_semaphore(self, task_type: TaskType) -> asyncio.Semaphore:
        """获取任务类型的信号量"""
        if task_type == TaskType.EXPORT_IMAGE or task_type == TaskType.EXPORT_TABLE:
            return self._export_semaphore
        elif task_type == TaskType.UPLOAD_ASSET:
            return self._upload_semaphore
        else:
            return self._download_semaphore

    def get_lock(self, task_type: TaskType) -> asyncio.Lock:
        """获取任务类型的锁"""
        return self._locks.get(task_type, asyncio.Lock())

    @property
    def stats(self) -> GEEConcurrencyStats:
        return self._stats

    def can_submit_task(self, task_type: TaskType) -> bool:
        """检查是否可以提交任务"""
        if task_type == TaskType.EXPORT_IMAGE or task_type == TaskType.EXPORT_TABLE:
            return self._stats.active_exports < self.config.max_parallel_exports
        elif task_type == TaskType.UPLOAD_ASSET:
            return self._stats.active_uploads < self.config.max_parallel_uploads
        else:
            return self._stats.active_downloads < self.config.max_parallel_downloads

    def get_waiting_count(self, task_type: TaskType) -> int:
        """获取任务类型的等待任务数"""
        if task_type == TaskType.EXPORT_IMAGE or task_type == TaskType.EXPORT_TABLE:
            return max(
                0,
                self._export_semaphore._value
                - self.config.max_parallel_exports
                + self._stats.active_exports,
            )
        elif task_type == TaskType.UPLOAD_ASSET:
            return max(
                0,
                self._upload_semaphore._value
                - self.config.max_parallel_uploads
                + self._stats.active_uploads,
            )
        else:
            return max(
                0,
                self._download_semaphore._value
                - self.config.max_parallel_downloads
                + self._stats.active_downloads,
            )


class GEEConfigService:
    """GEE 配置服务"""

    def __init__(self):
        self._parallel_config = GEEParallelConfig(
            max_parallel_exports=settings.gee_max_parallel_exports,
            max_parallel_uploads=settings.gee_max_parallel_uploads,
            max_parallel_downloads=settings.gee_max_parallel_downloads,
            account_cooldown_seconds=settings.gee_account_cooldown_seconds,
        )
        self._task_queue = GEETaskQueue(self._parallel_config)
        self._accounts: dict[str, GEEAccountInfo] = {}

    @property
    def parallel_config(self) -> GEEParallelConfig:
        return self._parallel_config

    @property
    def task_queue(self) -> GEETaskQueue:
        return self._task_queue

    def get_config_summary(self) -> dict:
        """获取配置摘要"""
        return {
            "enabled": settings.gee_enabled,
            "parallel_config": {
                "max_parallel_exports": self._parallel_config.max_parallel_exports,
                "max_parallel_uploads": self._parallel_config.max_parallel_uploads,
                "max_parallel_downloads": self._parallel_config.max_parallel_downloads,
                "account_cooldown_seconds": self._parallel_config.account_cooldown_seconds,
                "max_tasks_per_account": self._parallel_config.max_tasks_per_account,
            },
            "storage_backend": settings.gee_storage_backend,
            "local_storage_root": settings.gee_local_storage_root,
            "credentials_encryption_enabled": bool(
                settings.gee_credentials_encryption_key
            ),
            "api_account_management_enabled": settings.gee_api_account_management_enabled,
        }

    def get_task_limits(self, task_type: TaskType) -> dict:
        """获取任务类型的限制"""
        if task_type == TaskType.EXPORT_IMAGE or task_type == TaskType.EXPORT_TABLE:
            return {
                "max_concurrent": self._parallel_config.max_parallel_exports,
                "active": self._task_queue.stats.active_exports,
                "available": self._parallel_config.max_parallel_exports
                - self._task_queue.stats.active_exports,
            }
        elif task_type == TaskType.UPLOAD_ASSET:
            return {
                "max_concurrent": self._parallel_config.max_parallel_uploads,
                "active": self._task_queue.stats.active_uploads,
                "available": self._parallel_config.max_parallel_uploads
                - self._task_queue.stats.active_uploads,
            }
        else:
            return {
                "max_concurrent": self._parallel_config.max_parallel_downloads,
                "active": self._task_queue.stats.active_downloads,
                "available": self._parallel_config.max_parallel_downloads
                - self._task_queue.stats.active_downloads,
            }

    async def acquire_task_slot(self, task_type: TaskType) -> bool:
        """获取任务槽位（等待可用）"""
        semaphore = self._task_queue.get_semaphore(task_type)
        lock = self._task_queue.get_lock(task_type)

        async with lock:
            if task_type == TaskType.EXPORT_IMAGE or task_type == TaskType.EXPORT_TABLE:
                self._task_queue.stats.active_exports += 1
            elif task_type == TaskType.UPLOAD_ASSET:
                self._task_queue.stats.active_uploads += 1
            else:
                self._task_queue.stats.active_downloads += 1

        try:
            await semaphore.acquire()
            return True
        except Exception as e:
            # 释放已增加的任务计数
            async with lock:
                if (
                    task_type == TaskType.EXPORT_IMAGE
                    or task_type == TaskType.EXPORT_TABLE
                ):
                    self._task_queue.stats.active_exports = max(
                        0, self._task_queue.stats.active_exports - 1
                    )
                elif task_type == TaskType.UPLOAD_ASSET:
                    self._task_queue.stats.active_uploads = max(
                        0, self._task_queue.stats.active_uploads - 1
                    )
                else:
                    self._task_queue.stats.active_downloads = max(
                        0, self._task_queue.stats.active_downloads - 1
                    )
            raise e

    async def release_task_slot(self, task_type: TaskType):
        """释放任务槽位"""
        semaphore = self._task_queue.get_semaphore(task_type)
        lock = self._task_queue.get_lock(task_type)

        semaphore.release()

        async with lock:
            if task_type == TaskType.EXPORT_IMAGE or task_type == TaskType.EXPORT_TABLE:
                self._task_queue.stats.active_exports = max(
                    0, self._task_queue.stats.active_exports - 1
                )
            elif task_type == TaskType.UPLOAD_ASSET:
                self._task_queue.stats.active_uploads = max(
                    0, self._task_queue.stats.active_uploads - 1
                )
            else:
                self._task_queue.stats.active_downloads = max(
                    0, self._task_queue.stats.active_downloads - 1
                )


# 全局实例
gee_config_service = GEEConfigService()
