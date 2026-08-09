"""上传 staging ``meta.json`` 的共享 IO：跨进程锁 + 原子写。

append 模式（``upload.py``）与 manifest 模式（``resumable_upload.py``）共用本模块，
确保两套上传路径的 meta 读写语义一致：

- ``save_meta``：先写 ``meta.json.tmp`` 再 ``os.replace``，避免并发读读到半写 JSON。
- ``meta_lock``：跨进程/线程文件锁（Windows ``msvcrt.locking`` / POSIX ``fcntl.flock``），
  保护「读 meta → 改字段 → 写 meta」的 check-then-act 临界区。
- ``load_meta``：纯读，``save_meta`` 的原子性保证读不到半写内容，故无需持锁。

量纲：``dest`` 为 staging 会话目录（``STAGING_DIR/<upload_id>``），meta 文件名固定 ``meta.json``。
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_META_FILENAME = "meta.json"
_META_TMP_SUFFIX = ".json.tmp"
_LOCK_FILENAME = "meta.lock"


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
    """原子写 ``meta.json``：先写临时文件再 ``os.replace``。

    避免并发读读到半写 JSON（与 2026-08-09 修复的 manifest 模式 JSONDecodeError 同类根因）。
    临时文件名固定 ``meta.json.tmp``，与 manifest 模式历史约定一致。
    """
    meta_path = dest / _META_FILENAME
    tmp_path = meta_path.with_suffix(_META_TMP_SUFFIX)
    tmp_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, meta_path)


@contextmanager
def meta_lock(dest: Path) -> Iterator[None]:
    """跨进程/线程安全的 meta 文件锁。

    Windows 用 ``msvcrt.locking``（``LK_LOCK`` 阻塞获取 / ``LK_UNLCK`` 释放），
    POSIX 用 ``fcntl.flock``（``LOCK_EX`` 排他锁）。

    锁文件 ``meta.lock`` 在 ``dest`` 下（与 ``meta.json`` 同目录），``touch(exist_ok=True)``
    保证存在。锁是建议性的（advisory），只有同样调用本函数的代码才会互斥。
    """
    lock_path = dest / _LOCK_FILENAME
    lock_path.touch(exist_ok=True)
    with lock_path.open("a+b") as lock_f:
        try:
            import msvcrt

            msvcrt.locking(lock_f.fileno(), msvcrt.LK_LOCK, 1)
        except ImportError:
            import fcntl

            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            try:
                import msvcrt

                lock_f.seek(0)
                msvcrt.locking(lock_f.fileno(), msvcrt.LK_UNLCK, 1)
            except ImportError:
                import fcntl

                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
