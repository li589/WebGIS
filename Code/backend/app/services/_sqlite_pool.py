"""SQLite 连接池（基于 queue.Queue，WAL 模式）。

提供线程安全的连接复用，避免每次操作都新建/销毁连接。WAL 模式允许并发读，
写操作通过 busy_timeout 等待。适用于 FastAPI 异步线程池 + Celery 同步工作进程场景。

量纲: max_size 无量纲（连接数），busy_timeout_ms 单位毫秒。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager, suppress
from pathlib import Path
from queue import Queue
from collections.abc import Iterator

from app.services import spatialite_loader

logger = logging.getLogger(__name__)


class SQLiteConnectionPool:
    """SQLite 连接池，WAL 模式 + busy_timeout。

    连接按需创建（最多 max_size 个），使用完毕归还池中复用。
    线程安全：同一时刻每个连接仅被一个线程使用（由 Queue 保证）。
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        max_size: int = 8,
        row_factory: type | None = sqlite3.Row,
        busy_timeout_ms: int = 30000,
    ) -> None:
        self.db_path = str(db_path)
        self._max_size = max(1, int(max_size))
        self._row_factory = row_factory
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._pool: Queue[sqlite3.Connection | None] = Queue(maxsize=self._max_size)
        self._lock = threading.Lock()
        self._created = 0
        self._closed = False

    def _create_connection(self) -> sqlite3.Connection:
        """创建新连接并配置 WAL + busy_timeout。

        若 PRAGMA 配置失败（如磁盘满、DB 损坏），已建立的连接会被关闭以避免泄漏。
        """
        conn = sqlite3.connect(
            self.db_path,
            timeout=self._busy_timeout_ms / 1000.0,
            check_same_thread=False,
        )
        try:
            if self._row_factory is not None:
                conn.row_factory = self._row_factory
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            # SpatiaLite 扩展加载（统一/幂等/降级/不抛；失败仅 warn，不阻断 state DB）。
            # 高风险区（workflow/api_keys/gee_credentials）连接也走这里：扩展不可用时 PRAGMA 已成功，
            # DB 仍可正常读写，只是没有空间 SQL 函数。
            try:
                spatialite_loader.load_into(conn)
            except Exception:
                logger.warning(
                    "spatialite_loader.load_into failed for %s",
                    self.db_path,
                    exc_info=True,
                )
            return conn
        except Exception:
            # PRAGMA 失败时关闭已建立的连接，避免文件句柄泄漏
            conn.close()
            raise

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """获取连接上下文管理器。

        用法: `with pool.connection() as conn: ...`
        正常退出时 commit，异常时 rollback，最终归还连接到池中。
        行为与 sqlite3.Connection 的上下文管理器一致，确保调用方代码无需改动。
        """
        conn = self._acquire()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            self._release(conn)

    def _acquire(self) -> sqlite3.Connection:
        # 1. 尝试非阻塞获取池中空闲连接
        try:
            return self._pool.get_nowait()
        except Exception:
            pass  # 队列空

        # 2. 队列空 — 若未达上限则创建新连接。
        #    仅在锁内读取/递增计数器，连接创建在锁外执行（避免阻塞其他线程）。
        with self._lock:
            if self._created < self._max_size:
                self._created += 1
                should_create = True
            else:
                should_create = False

        if should_create:
            try:
                conn = self._create_connection()
                # close_all 后拒绝再借出：直接关闭丢弃，避免向已关闭池续命
                with self._lock:
                    if self._closed:
                        with suppress(Exception):
                            conn.close()
                        self._created -= 1
                        raise RuntimeError("SQLiteConnectionPool already closed")
                return conn
            except Exception:
                # 创建失败时回退计数器，避免 _created 虚高导致池永久阻塞
                with self._lock:
                    self._created -= 1
                raise

        # 3. 已达上限 — 阻塞等待归还
        return self._pool.get()

    def _release(self, conn: sqlite3.Connection) -> None:
        # 安审 2026-08-21 C-3：close_all 清空队列并归零 _created 后，借出中的
        # 旧连接归还时 put 可能使队列超 maxsize → 归还线程永久阻塞（线程泄漏）。
        # 改 put_nowait：队列满（或已关闭）时直接关闭连接丢弃。
        try:
            self._pool.put_nowait(conn)
        except Exception:
            with suppress(Exception):
                conn.close()

    def close_all(self, *, quiet: bool = False) -> None:
        """关闭池中所有空闲连接（用于优雅关闭）。

        quiet=True 时跳过日志记录（用于 __del__ 期间，避免解释器关闭时
        logging 模块的 stream 已关闭导致 I/O 错误输出到 stderr）。
        """
        with self._lock:
            self._closed = True
        closed = 0
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                if conn is not None:
                    conn.close()
                    closed += 1
            except Exception:
                break
        with self._lock:
            self._created = 0
        if not quiet:
            logger.info(
                "SQLiteConnectionPool closed %d idle connections for %s",
                closed,
                self.db_path,
            )

    def __del__(self) -> None:
        """析构时尝试关闭空闲连接（best-effort，避免资源泄漏）。"""
        with suppress(Exception):
            self.close_all(quiet=True)
