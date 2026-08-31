"""共享目录并发下载协调：认领锁 + 唯一 .part + 可重试原子落盘。

多用户 / 多 workflow 同时写同一 ``DATA_ROOT``  granule 时，旧实现共用
``name.h5.part`` 再 ``Path.replace``，在 Windows 上易触发 WinError 32
（文件被另一进程占用）。本模块提供：

1. ``.claim`` 排他认领（``O_CREAT|O_EXCL``），其它任务等待成品出现；
2. 每任务独立 ``.part.<pid>.<uuid>``，互不覆盖半成品；
3. ``os.replace`` 遇占用重试；若对端已先落盘则丢弃本方临时文件并视为成功。
"""

from __future__ import annotations

import errno
import logging
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_WINERROR_SHARING_VIOLATION = 32
_DEFAULT_STALE_CLAIM_SECONDS = 2 * 60 * 60
_DEFAULT_WAIT_TIMEOUT_SECONDS = 30 * 60
_DEFAULT_REPLACE_RETRIES = 30
_DEFAULT_REPLACE_DELAY = 0.5


def is_complete_file(path: Path) -> bool:
    """成品存在且非空。"""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def make_unique_part_path(dest: Path) -> Path:
    """生成进程级唯一半成品路径，避免并发写同一 ``.part``。"""
    token = uuid.uuid4().hex[:8]
    return dest.with_name(f"{dest.name}.part.{os.getpid()}.{token}")


def claim_path_for(dest: Path) -> Path:
    return dest.with_name(f"{dest.name}.claim")


def _steal_stale_claim(lock_path: Path, stale_seconds: float) -> bool:
    try:
        age = time.time() - lock_path.stat().st_mtime
        if age < stale_seconds:
            return False
        logger.warning("回收过期下载认领锁: %s (age=%.0fs)", lock_path.name, age)
        lock_path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def try_claim_download(
    dest: Path,
    *,
    stale_seconds: float = _DEFAULT_STALE_CLAIM_SECONDS,
) -> Path | None:
    """尝试排他认领 ``dest`` 的下载权。成功返回 claim 路径，否则 None。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    lock_path = claim_path_for(dest)
    for _ in range(2):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                payload = f"{os.getpid()}\n{time.time():.3f}\n".encode()
                os.write(fd, payload)
            finally:
                os.close(fd)
            return lock_path
        except FileExistsError:
            if _steal_stale_claim(lock_path, stale_seconds):
                continue
            return None
        except OSError as exc:
            # Windows 偶发竞态：等价于已被占用
            if getattr(exc, "winerror", None) == _WINERROR_SHARING_VIOLATION:
                return None
            if exc.errno in (errno.EEXIST, errno.EACCES):
                return None
            raise
    return None


def release_claim(lock_path: Path | None) -> None:
    if lock_path is None:
        return
    try:
        lock_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("释放认领锁失败 %s: %s", lock_path, exc)


def wait_until_complete(
    dest: Path,
    *,
    timeout: float = _DEFAULT_WAIT_TIMEOUT_SECONDS,
    poll: float = 1.0,
) -> bool:
    """等待对端把 ``dest`` 落盘完成；超时或认领消失且无成品则 False。"""
    deadline = time.time() + max(0.0, timeout)
    lock_path = claim_path_for(dest)
    while time.time() < deadline:
        if is_complete_file(dest):
            return True
        if not lock_path.exists() and not is_complete_file(dest):
            # 对端失败并释放锁
            return False
        time.sleep(poll)
    return is_complete_file(dest)


def replace_with_retry(
    src: Path,
    dest: Path,
    *,
    retries: int = _DEFAULT_REPLACE_RETRIES,
    delay: float = _DEFAULT_REPLACE_DELAY,
) -> None:
    """将半成品原子替换为成品；占用时重试，对端已完成后丢弃半成品。"""
    last_exc: OSError | None = None
    for attempt in range(1, max(1, retries) + 1):
        if is_complete_file(dest):
            try:
                src.unlink(missing_ok=True)
            except OSError:
                pass
            logger.info("  对端已落盘，跳过替换: %s", dest.name)
            return
        try:
            os.replace(src, dest)
            return
        except OSError as exc:
            last_exc = exc
            winerror = getattr(exc, "winerror", None)
            retryable = winerror == _WINERROR_SHARING_VIOLATION or exc.errno in (
                errno.EACCES,
                errno.EPERM,
                errno.EBUSY,
                errno.EAGAIN,
            )
            if not retryable or attempt >= retries:
                break
            logger.warning(
                "  落盘占用重试 %d/%d: %s -> %s (%s)",
                attempt,
                retries,
                src.name,
                dest.name,
                exc,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def download_claimed_file(
    *,
    dest: Path,
    do_download: Callable[[Path], bool],
    wait_timeout: float = _DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> str:
    """协调单文件下载。

    ``do_download(part_path: Path) -> bool`` 负责把内容写到唯一 part。

    Returns:
        ``"skipped"`` | ``"downloaded"`` | ``"failed"``
    """
    if is_complete_file(dest):
        return "skipped"

    claim = try_claim_download(dest)
    if claim is None:
        logger.info("  其它任务正在下载，等待: %s", dest.name)
        if wait_until_complete(dest, timeout=wait_timeout):
            return "skipped"
        # 对端失败，再争一次
        claim = try_claim_download(dest)
        if claim is None:
            if is_complete_file(dest):
                return "skipped"
            logger.error("  无法取得下载认领且成品未就绪: %s", dest.name)
            return "failed"

    part = make_unique_part_path(dest)
    try:
        if is_complete_file(dest):
            return "skipped"
        ok = bool(do_download(part))
        if not ok:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
            return "failed"
        replace_with_retry(part, dest)
        return "downloaded"
    except Exception:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        release_claim(claim)
