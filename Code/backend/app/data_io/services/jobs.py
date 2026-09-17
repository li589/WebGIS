"""导入任务状态（磁盘 JSON；大文件可走 Celery）。"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from collections.abc import Callable, Iterator

from app.data_io.services.paths import jobs_dir, ensure_imports_root, safe_import_child
from app.data_io.services._meta_io import file_lock, save_json_atomic

logger = logging.getLogger(__name__)

JobHandler = Callable[[dict[str, Any]], dict[str, Any]]


def _job_path(job_id: str) -> Path:
    ensure_imports_root()
    # 安审 2026-08-22（B-3）：job_id 纯名称校验，防越界读任意 JSON 文件
    safe = safe_import_child(job_id, root=jobs_dir())
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
    # 原子写：同目录 ``.tmp`` + ``os.replace``（见 ``_meta_io.save_json_atomic``）。
    # 直接 ``write_text`` 是「先截断再写」，并发读者可读到 0 字节文件 → JSONDecodeError。
    save_json_atomic(_job_path(job_id), record)
    return job_id


def update_job(job_id: str, **fields: Any) -> dict[str, Any]:
    """读-改-写任务记录（**按 job 粒度加锁**，不会 lost update）。

    写入本身是原子的（``save_json_atomic``），读者不会看到半写 JSON；但
    「读 → 改 → 写」若不串行化，两个写者（worker 线程与 API 侧 ``cancel_job``）
    交错时后写者会覆盖前写者刚改的字段。本函数用 ``job_lock`` 把整个
    临界区串起来，故**不要**在持锁期间再调用 ``update_job``（不可重入，会自锁死）——
    需要更宽的临界区请在调用方用 ``job_lock`` 包住，并在内层调 ``_update_job_locked``。

    锁开销：每个 job 一个 ``<job_id>.lock`` 空文件（只作为锁锚点，不写内容）。
    """
    with job_lock(job_id):
        return _update_job_locked(job_id, **fields)


def _update_job_locked(job_id: str, **fields: Any) -> dict[str, Any]:
    """``update_job`` 的无锁内核：**调用方必须已持有 ``job_lock(job_id)``**。"""
    path = _job_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"任务不存在: {job_id}")
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(fields)
    record["updated_at"] = time.time()
    save_json_atomic(path, record)
    return record


@contextmanager
def job_lock(job_id: str) -> Iterator[None]:
    """按 job 粒度的排他文件锁（跨线程/进程，委托 ``_meta_io.file_lock``）。

    锁锚点与任务记录同目录：``<job_id>.lock``。命名后缀有意区别于 ``job-*.json``，
    不会被 ``list_jobs`` 的 glob 扫到，也不影响 ``_job_path`` 的越界校验。

    **不可重入**——需要嵌套临界区时用 ``_update_job_locked``。
    """
    with file_lock(_job_path(job_id).with_suffix(".lock")):
        yield


def get_job(job_id: str) -> dict[str, Any]:
    """读取任务记录。

    Raises:
        FileNotFoundError: 记录不存在（含 job_id 校验不通过）。

    **不捕获** ``json.JSONDecodeError``：任务文件不可解析属**服务端故障**
    （磁盘损坏 / 历史半写文件 / 进程被强杀），按 Phase 3「异常边界收窄」的既定
    契约上抛全局处理器 → 500 + 通用文案。切勿改成返回 404 或空记录：
    那会把服务端故障伪装成客户端错误，并让 ``Test/backend/test_exception_narrowing.py``
    场景 4a 的回归失效。

    正常路径下不会读到半写内容——写入侧统一走 ``save_json_atomic`` 原子替换
    （2026-09-17 修复：``enqueue_job`` 的 force_async 分支启动 worker 线程后
    立即回读同一文件，与旧的非原子 ``write_text`` 竞态，偶发 400）。
    """
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
        jobs_dir().glob("job-*.json"), key=lambda p: p.stat().st_mtime, reverse=True
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
    """尽力取消：queued 立即可取消；running 标记 cancelled，handler 起点检查。

    「读状态 → 判终态 → 写 cancelled」整段在 ``job_lock`` 内完成：否则与 worker
    的终态写入交错时，可能把刚落库的 ``succeeded`` / ``failed`` 覆盖成 ``cancelled``
    （比单纯的 lost update 更严重——状态被回退）。内层必须用 ``_update_job_locked``，
    ``update_job`` 会再次取同一把锁而自锁死。
    """
    with job_lock(job_id):
        record = get_job(job_id)
        status = str(record.get("status") or "")
        if status in {"succeeded", "failed", "cancelled"}:
            return {"job_id": job_id, "status": status}
        return _update_job_locked(
            job_id, status="cancelled", message="cancelled", progress=1.0
        )


def _cancelled_snapshot(job_id: str) -> dict[str, Any] | None:
    """**必须在持有 ``job_lock(job_id)`` 时调用**：已取消则返回其记录，否则 ``None``。"""
    current = get_job(job_id)
    if str(current.get("status") or "") == "cancelled":
        return current
    return None


def run_job_sync(job_id: str, handler: JobHandler) -> dict[str, Any]:
    """同步执行任务。

    每次「判 cancelled + 写终态」都放在同一把 ``job_lock`` 内，使取消与终态写入
    互斥；``handler`` 本身**不在锁内**执行（可能耗时数分钟，持锁会阻塞取消）。
    """
    with job_lock(job_id):
        record = get_job(job_id)
        if str(record.get("status") or "") == "cancelled":
            return record
        _update_job_locked(job_id, status="running", progress=0.05, message="running")
    try:
        with job_lock(job_id):
            cancelled = _cancelled_snapshot(job_id)
            if cancelled is not None:
                return cancelled
            record = get_job(job_id)
        result = handler(record.get("payload") or {})
        with job_lock(job_id):
            # 若运行中被取消，保留 cancelled，不覆盖为 succeeded
            cancelled = _cancelled_snapshot(job_id)
            if cancelled is not None:
                return cancelled
            return _update_job_locked(
                job_id,
                status="succeeded",
                progress=1.0,
                message="done",
                result=result,
                error=None,
            )
    except Exception as exc:
        logger.exception("import job failed: %s", job_id)
        with job_lock(job_id):
            cancelled = _cancelled_snapshot(job_id)
            if cancelled is not None:
                return cancelled
            _update_job_locked(
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
        # 注意：下一行起 worker 线程后会立即 ``update_job``（重写同一文件），
        # 而本请求线程紧接着 ``get_job`` 回读。两者曾因非原子写入竞态读到 0 字节
        # 文件（2026-09-17 CI 偶发 400）。写入已原子化，此回读不再可能读到半写内容。
        threading.Thread(target=_run, name=f"import-{job_id}", daemon=True).start()
        return get_job(job_id)

    if handler is None:
        from app.data_io.tasks.import_jobs import _dispatch

        return run_job_sync(job_id, lambda p: _dispatch(kind, p))
    return run_job_sync(job_id, handler)
