from __future__ import annotations

import logging
from threading import RLock
from typing import Any, Optional

import ee


logger = logging.getLogger(__name__)


class GeeContext:
    """串行化全局 ee 初始化，避免多账号并发时串用同一运行时状态。"""

    _runtime_lock = RLock()

    def __init__(
        self,
        account_id: str,
        credentials: Optional[Any] = None,
        ee_module: Any | None = None,
        project_id: Optional[str] = None,
    ) -> None:
        self.account_id = account_id
        self._credentials = credentials
        self._project_id = project_id
        self._initialized = False
        self._lock_acquired = False
        self._ee = ee_module or ee

    def initialize(self) -> None:
        """初始化当前上下文的GEE客户端。"""
        if self._initialized:
            logger.warning("GEE context already initialized: %s", self.account_id)
            return
        self._runtime_lock.acquire()
        self._lock_acquired = True
        try:
            if self._credentials and self._project_id:
                self._ee.Initialize(
                    credentials=self._credentials, project=self._project_id
                )
            elif self._credentials:
                self._ee.Initialize(credentials=self._credentials)
            else:
                self._ee.Initialize()
            self._initialized = True
            logger.info("GEE context initialized: %s", self.account_id)
        except Exception as e:
            if self._lock_acquired:
                self._runtime_lock.release()
                self._lock_acquired = False
            logger.error(
                "GEE context initialization failed for %s: %s", self.account_id, str(e)
            )
            raise

    @property
    def ee(self) -> Any:
        """返回当前上下文的EE模块对象，用于后续操作。"""
        if not self._initialized:
            self.initialize()
        return self._ee

    def close(self) -> None:
        """释放上下文资源（如果需要的话）。"""
        self._initialized = False
        if self._lock_acquired:
            self._runtime_lock.release()
            self._lock_acquired = False
        logger.info("GEE context closed: %s", self.account_id)
