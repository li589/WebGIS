"""导入任务状态（磁盘 JSON；大文件可走 Celery）。"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from collections.abc import Callable

from app.data_io.services.paths import JOBS_DIR, ensure_imports_root, safe_import_child

logger = logging.getLogger(__name__)

JobHandler = Callable[[dict[str, Any]], dict[str, Any]]


def _job_path(job_id: str) -> Path:
    ensure_imports_root()
    # 安审 2026-08-22（B-3）：job_id 纯名称校验，防越界读任意 JSON 文件
    safe = safe_import_child(job_id, root=JOBS_DIR)
    return safe.with_name(safe.name + ".json")


def create_job(
    *, kind: str, payload: dict[str, Any], owner_user_id: int | None = None
) -> str:
    """创建导入任务。

    ``owner_user_id`` **必须由调用方显式传入**（通常来自端点的凭据）。
    本模块不接受任何隐式上下文（ContextVar 等）——2026-08-29 审查 C-1：
    曾由同步依赖用 ContextVar 传递属主，因 FastAPI 在线程池执行同步依赖，
    ``set()`` 不回传事件循环，导致属主恒为 ``None``、提交者被自己的任务 403。

    ``owner_user_id=None`` 表示无主任务：会被 ``list_jobs`` 过滤、
    被 ``_deny_job_if_not_owner`` 拒绝（fail-closed，仅管理员可见）。
    """
    ensure_imports_root()
    job_id = f"job-{uuid.uuid4().hex[:16]}"
    record = {
        "job_id": job_id,
        "kind": kind,
        "status": "queued",
        "progress": 0.0,
        "message": "queued",
        "payload": payload,
        "result": None,
        "error": None,
        "owner_user_id": owner_user_id,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _job_path(job_id).write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )
    return job_id


def update_job(job_id: str, **fields: Any) -> dict[str, Any]:
    path = _job_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"任务不存在: {job_id}")
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(fields)
    record["updated_at"] = time.time()
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


def get_job(job_id: str) -> dict[str, Any]:
    path = _job_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"任务不存在: {job_id}")
    record = json.loads(path.read_text(encoding="utf-8"))
    result = record.get("result") or {}
    if isinstance(result, dict) and result.get("download_path"):
        record = {
            **record,
            "download_url": f"/import/jobs/{job_id}/download",
        }
    return record


def list_jobs(
    *, limit: int = 20, owner_user_id: int | None = None, include_all: bool = False
) -> list[dict[str, Any]]:
    """List recent jobs.

    When ``include_all`` is False and ``owner_user_id`` is set, only jobs owned
    by that user are returned. Admin callers should pass ``include_all=True``.

    **无主任务一律不返回**（fail-closed）：此前本 docstring 误称"legacy 无主任务
    也会返回"，与实现相反。实现是对的——无主任务可能属于任何调用者（例如
    service key / dev bypass 提交的任务），暴露给非管理员即越权。
    **请勿按旧文档把这段改成返回无主任务。**
    """
    ensure_imports_root()
    items: list[dict[str, Any]] = []
    for path in sorted(
        JOBS_DIR.glob("job-*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not include_all and owner_user_id is not None:
            job_owner = record.get("owner_user_id")
            # Legacy jobs without owner: hide from non-owner lists (fail-closed)
            if job_owner is None or int(job_owner) != int(owner_user_id):
                continue
        items.append(
            {
                "job_id": record.get("job_id"),
                "kind": record.get("kind"),
                "status": record.get("status"),
                "progress": record.get("progress") or 0,
                "message": record.get("message"),
                "error": record.get("error"),
                "created_at": record.get("created_at"),
                "owner_user_id": record.get("owner_user_id"),
            }
        )
        if len(items) >= max(1, min(limit, 100)):
            break
    return items


def cancel_job(job_id: str) -> dict[str, Any]:
    """尽力取消：queued 立即可取消；running 标记 cancelled，handler 起点检查。"""
    record = get_job(job_id)
    status = str(record.get("status") or "")
    if status in {"succeeded", "failed", "cancelled"}:
        return {"job_id": job_id, "status": status}
    return update_job(job_id, status="cancelled", message="cancelled", progress=1.0)


def run_job_sync(job_id: str, handler: JobHandler) -> dict[str, Any]:
    record = get_job(job_id)
    if str(record.get("status") or "") == "cancelled":
        return record
    update_job(job_id, status="running", progress=0.05, message="running")
    try:
        record = get_job(job_id)
        if str(record.get("status") or "") == "cancelled":
            return record
        result = handler(record.get("payload") or {})
        # 若运行中被取消，保留 cancelled，不覆盖为 succeeded
        current = get_job(job_id)
        if str(current.get("status") or "") == "cancelled":
            return current
        return update_job(
            job_id,
            status="succeeded",
            progress=1.0,
            message="done",
            result=result,
            error=None,
        )
    except Exception as exc:
        logger.exception("import job failed: %s", job_id)
        current = get_job(job_id)
        if str(current.get("status") or "") == "cancelled":
            return current
        update_job(
            job_id,
            status="failed",
            progress=1.0,
            message="failed",
            error=str(exc),
        )
        raise


def enqueue_job(
    kind: str,
    payload: dict[str, Any],
    handler: JobHandler | None = None,
    *,
    force_async: bool = False,
    owner_user_id: int | None = None,
) -> dict[str, Any]:
    """创建任务：优先 Celery；不可用则线程或同步执行。

    ``handler`` 仅同步路径需要；异步走 Celery ``_dispatch(kind, payload)``。
    """
    job_id = create_job(kind=kind, payload=payload, owner_user_id=owner_user_id)

    def _run() -> None:
        if handler is None:
            from app.data_io.tasks.import_jobs import _dispatch

            run_job_sync(job_id, lambda p: _dispatch(kind, p))
        else:
            run_job_sync(job_id, handler)

    # 尝试 Celery（按名派发，不 import task 模块）
    try:
        from app.core.celery_app import celery_app, celery_available
        from app.core.config import settings

        if force_async and celery_available and celery_app is not None:
            celery_app.send_task(
                "app.tasks.import_tasks.run_import_job",
                args=[job_id, kind],
                queue=getattr(settings, "workflow_queue_batch", "celery"),
            )
            return get_job(job_id)
    except Exception:
        logger.debug("celery enqueue unavailable, fallback thread", exc_info=True)

    if force_async:
        threading.Thread(target=_run, name=f"import-{job_id}", daemon=True).start()
        return get_job(job_id)

    if handler is None:
        from app.data_io.tasks.import_jobs import _dispatch

        return run_job_sync(job_id, lambda p: _dispatch(kind, p))
    return run_job_sync(job_id, handler)
