"""Launcher logging: coloured console + rotating file handler.

Extracted from the original ``launch.py``. The :class:`Log` class writes
timestamped, category-tagged lines to both stdout (with ANSI colours when
a TTY is detected) and a rotating file handler (5 MB × 3 backups).

The module-level ``log`` singleton is imported by every ``launch/``
submodule; instantiating it here ensures the file handler is attached
exactly once on first import.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from launch.constants import (
    LAUNCHER_LOG,
    _LAUNCHER_LOG_BACKUP_COUNT,
    _LAUNCHER_LOG_MAX_BYTES,
    _SUBPROCESS_LOG_ROTATE_THRESHOLD,
)


class Log:
    """规范的彩色日志输出器，同时写入控制台和文件（带轮转）。"""

    _COLORS = {
        "DEBUG": "\033[90m",  # 灰
        "INFO": "\033[36m",  # 青
        "OK": "\033[32m",  # 绿
        "WARN": "\033[33m",  # 黄
        "ERROR": "\033[31m",  # 红
        "RESET": "\033[0m",
    }
    _BOLD = "\033[1m"

    def __init__(self, log_file: Path):
        self._log_file = log_file
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        self._file_handler = RotatingFileHandler(
            log_file,
            maxBytes=_LAUNCHER_LOG_MAX_BYTES,
            backupCount=_LAUNCHER_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        self._file_handler.setLevel(logging.DEBUG)
        # 关闭 logging 模块在 emit 失败时打印调用栈到 stderr 的行为
        logging.raiseExceptions = False
        self._logger = logging.getLogger("launcher")
        self._logger.setLevel(logging.DEBUG)
        for h in self._logger.handlers:
            if isinstance(h, RotatingFileHandler) and getattr(
                h, "baseFilename", ""
            ) == str(log_file):
                self._logger.removeHandler(h)
        self._logger.addHandler(self._file_handler)
        self._logger.propagate = False
        self._is_tty = sys.stdout.isatty()
        if sys.platform == "win32" and self._is_tty:
            os.system("")  # 激活 VT100

    def _write(self, level: str, category: str, message: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cat_padded = category.ljust(10)
        line = f"[{ts}] [{level:5s}] [{cat_padded}] {message}"
        log_level = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "OK": logging.INFO,
            "WARN": logging.WARNING,
            "ERROR": logging.ERROR,
        }.get(level, logging.INFO)
        self._logger.log(log_level, line)
        if self._is_tty:
            color = self._COLORS.get(level, "")
            bold = self._BOLD if level in ("ERROR", "OK") else ""
            print(f"{bold}{color}{line}{self._COLORS['RESET']}")
        else:
            print(line)

    def info(self, category: str, msg: str) -> None:
        self._write("INFO", category, msg)

    def ok(self, category: str, msg: str) -> None:
        self._write("OK", category, msg)

    def warn(self, category: str, msg: str) -> None:
        self._write("WARN", category, msg)

    def error(self, category: str, msg: str) -> None:
        self._write("ERROR", category, msg)

    def debug(self, category: str, msg: str) -> None:
        self._write("DEBUG", category, msg)

    def banner(self, title: str) -> None:
        line = "═" * 60
        self.info("Launcher", line)
        self.info("Launcher", f"  {title}")
        self.info("Launcher", line)

    def close(self) -> None:
        self._file_handler.close()


# Module-level singleton — instantiated on first import.
log = Log(LAUNCHER_LOG)


def rotate_subprocess_log_if_needed(log_file: Path) -> None:
    """启动前检查子进程日志文件大小，超过阈值则轮转。

    Windows 下 subprocess.Popen 的 stdout 文件描述符固定，无法在运行中轮转。
    此函数在每次启动子进程前调用，若上次日志超过 50 MB 则重命名为 .old，
    让子进程从空文件开始写。.old 文件保留供查阅，下次轮转时被覆盖。
    """
    try:
        if not log_file.exists():
            return
        size = log_file.stat().st_size
        if size < _SUBPROCESS_LOG_ROTATE_THRESHOLD:
            return
        old_file = log_file.with_suffix(log_file.suffix + ".old")
        if old_file.exists():
            old_file.unlink()
        log_file.rename(old_file)
        log.info(
            "Log", f"轮转 {log_file.name} ({size // 1024 // 1024} MB → {old_file.name})"
        )
    except OSError as exc:
        log.warn("Log", f"轮转 {log_file.name} 失败: {exc}")
