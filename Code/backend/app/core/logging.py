from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator

from app.core.config import settings

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)
_task_id_var: ContextVar[str | None] = ContextVar("task_id", default=None)
_logging_configured = False


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": _request_id_var.get(),
            "run_id": _run_id_var.get(),
            "task_id": _task_id_var.get(),
            "module": record.module,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    global _logging_configured
    if _logging_configured:
        return
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = StructuredJsonFormatter()

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        log_dir / "backend.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    _logging_configured = True


def ensure_logging_configured() -> None:
    configure_logging()


def set_request_id(request_id: str | None) -> None:
    _request_id_var.set(request_id)


def get_request_id() -> str | None:
    return _request_id_var.get()


@contextmanager
def log_context(*, request_id: str | None = None, run_id: str | None = None, task_id: str | None = None) -> Iterator[None]:
    request_token = _request_id_var.set(request_id if request_id is not None else _request_id_var.get())
    run_token = _run_id_var.set(run_id if run_id is not None else _run_id_var.get())
    task_token = _task_id_var.set(task_id if task_id is not None else _task_id_var.get())
    try:
        yield
    finally:
        _task_id_var.reset(task_token)
        _run_id_var.reset(run_token)
        _request_id_var.reset(request_token)
