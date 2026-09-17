"""上传 staging ``meta.json`` 的共享 IO：跨进程锁 + 原子写。

append 模式（``upload.py``）与 manifest 模式（``resumable_upload.py``）共用本模块，
确保两套上传路径的 meta 读写语义一致：

- ``save_meta``：先写临时文件再 ``os.replace``，避免并发读读到半写 JSON。
- ``meta_lock``：跨进程/线程文件锁（Windows ``msvcrt.locking`` / POSIX ``fcntl.flock``），
  保护「读 meta → 改字段 → 写 meta」的 check-then-act 临界区。
- ``file_lock``：上者的通用形式（任意锁文件路径）；``meta_lock`` 现在委托它。
  ``jobs.py`` 的按 job 粒度锁也复用它，避免仓库里出现第二套锁实现。
- ``load_meta``：纯读，``save_meta`` 的原子性保证读不到半写内容，故无需持锁。

量纲：``dest`` 为 staging 会话目录（``staging_dir()/<upload_id>``），meta 文件名固定 ``meta.json``。

原子写的 Windows 注意事项（2026-09-17）
───────────────────────────────────────
``os.replace`` 在 Windows 上是 ``MoveFileEx(MOVEFILE_REPLACE_EXISTING)``：若目标文件
此刻正被读者打开，会直接失败并抛 ``PermissionError [WinError 5]``。因此「固定 ``.tmp``
名 + 裸 ``os.replace``」在两个维度上不够用：

1. **并发写者**共用同一个 ``.tmp`` 路径 → 互相截断/搬走对方的临时文件；
2. **写者与读者并发**时 ``replace`` 抛 ``PermissionError``，调用方看到的是硬失败
   （而非它本应提供的一致性）。

故 ``save_json_atomic`` / ``save_bytes_atomic`` 改为「唯一临时名 + 短退避重试」。
同一模式在 ``app.weatherengine.client``（``unique_cache_tmp_path`` /
``replace_with_retry``）已有实现；此处**不跨模块复用**是为了保持依赖方向
（``data_io`` 不应依赖 ``weatherengine``），代价是一份约 20 行的重复——如需收敛，
应把两者提到一个公共低层模块，而不是让 ``data_io`` 反向依赖。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from collections.abc import Iterator

_META_FILENAME = "meta.json"
_LOCK_FILENAME = "meta.lock"


def _atomic_tmp_path(path: Path) -> Path:
    """为原子写生成**唯一**临时路径（pid + 线程 id + 随机片段）。

    固定 ``.tmp`` 后缀会让并发写者在写同一目标时互相踩踏（Windows 上
    ``replace`` 目标或源被他人占用还会 ``PermissionError``，交错写则产生损坏文件）。
    唯一名 + ``os.replace`` 保证「全有或全无」。
    """
    return path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.tmp"
    )


def _replace_with_retry(
    src: Path, dst: Path, *, attempts: int = 5, delay: float = 0.05
) -> None:
    """``os.replace`` 的 Windows 安全版本（对 sharing violation 短退避重试）。

    即便临时名唯一，``replace`` 目标在 Windows 上仍可能因读者持有句柄而抛
    ``PermissionError``(13/WinError 5)。重试后让「最后一次写入获胜」——
    同一目标的载荷语义等价，覆盖无害。
    """
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2


def save_json_atomic(path: Path, payload: Any) -> None:
    """原子写任意 JSON 文件（同目录唯一 ``.tmp`` + ``os.replace``）。

    安审 2026-08-21 C-2：``bounds.json`` / 时序 ``meta.json`` 等与 staging
    ``meta.json`` 同样存在「worker 写 / API 进程读」并发，半写 JSON 会让
    lazy-load 读端 JSONDecodeError → 图层被判「不存在」。与 ``save_meta``
    同模式，通用化到任意路径。
    """
    tmp_path = _atomic_tmp_path(path)
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _replace_with_retry(tmp_path, path)


def save_bytes_atomic(path: Path, payload: bytes) -> None:
    """原子写二进制文件（同目录唯一 ``.tmp`` + ``os.replace``）。"""
    tmp_path = _atomic_tmp_path(path)
    tmp_path.write_bytes(payload)
    _replace_with_retry(tmp_path, path)


def load_meta(dest: Path) -> dict[str, Any]:
    """从 ``dest/meta.json`` 读取并解析 meta。

    Raises:
        FileNotFoundError: ``meta.json`` 不存在（会话未初始化或已清理）。
    """
    meta_path = dest / _META_FILENAME
    if not meta_path.exists():
        raise FileNotFoundError(f"上传会话目录无 meta.json: {dest}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def save_meta(dest: Path, meta: dict[str, Any]) -> None:
    """原子写 ``meta.json``：先写唯一临时文件再 ``os.replace``（带重试）。

    避免并发读读到半写 JSON（与 2026-08-09 修复的 manifest 模式 JSONDecodeError
    同类根因）。临时名不再固定为 ``meta.json.tmp``：``load_meta`` 是无锁纯读，
    写者与读者并发时 Windows ``replace`` 可能抛 sharing violation，固定名还会让
    多写者互相踩踏——详见模块 docstring「原子写的 Windows 注意事项」。
    """
    meta_path = dest / _META_FILENAME
    tmp_path = _atomic_tmp_path(meta_path)
    tmp_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    _replace_with_retry(tmp_path, meta_path)


@contextmanager
def file_lock(lock_path: Path) -> Iterator[None]:
    """跨进程/线程的**建议性**文件排他锁（通用化，任意锁文件路径）。

    Windows 用 ``msvcrt.locking``（``LK_LOCK`` 阻塞获取 / ``LK_UNLCK`` 释放），
    POSIX 用 ``fcntl.flock``（``LOCK_EX`` 排他锁）。锁文件不存在时创建
    （``mkdir(parents=True)`` + ``touch``）。

    语义与注意：
    - **阻塞式**：拿不到锁会等，不超时、不降级。请勿在持锁期间做慢 IO。
    - **不可重入**：同一线程再次对同一路径取锁会**自锁死**
      （Windows 按句柄判冲突，POSIX ``flock`` 按打开文件描述判冲突）。
      需要嵌套时请把内层改成不取锁的 ``*_locked`` 变体，而不是递归调用。
    - 建议性（advisory）：只有同样经过本函数取锁的代码才会互斥。
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    with lock_path.open("a+b") as lock_f:
        _acquire_lock(lock_f)
        try:
            yield
        finally:
            _release_lock(lock_f)


def _acquire_lock(lock_f: Any) -> None:
    try:
        import msvcrt

        msvcrt.locking(lock_f.fileno(), msvcrt.LK_LOCK, 1)
    except ImportError:
        import fcntl

        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)


def _release_lock(lock_f: Any) -> None:
    try:
        import msvcrt

        lock_f.seek(0)
        msvcrt.locking(lock_f.fileno(), msvcrt.LK_UNLCK, 1)
    except ImportError:
        import fcntl

        fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


@contextmanager
def meta_lock(dest: Path) -> Iterator[None]:
    """staging 会话目录的 meta 文件锁（``dest/meta.lock``）。

    实现委托 ``file_lock``；保留本函数是为了让上传链路（``upload.py`` /
    ``resumable_upload.py``）的调用点语义不变。
    """
    with file_lock(dest / _LOCK_FILENAME):
        yield
