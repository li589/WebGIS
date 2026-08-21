r"""共享 HTTP 下载工具：Range 断点续传 + 指数退避重试 + 磁盘空间检查。

从 ``ingest/nsidc_download.py`` 提取，供 nsidc / nomads / cdse / gldas 等
ingest 下载模块复用，保证各下载链续传语义一致。

``gldas_download.py`` 在此基础上叠加 ``.part`` 临时文件 + 原子替换，
避免部分下载文件污染"已下载跳过"判断。
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CHUNK_SIZE = 262144  # 256 KB
DEFAULT_DOWNLOAD_TIMEOUT = 3600
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_BACKOFF = 2.0
DEFAULT_MIN_DISK_FREE_GB = 5.0
PROGRESS_INTERVAL = 2.0

# 需求3 批次2：线程本地「最近下载速率」，模块层（download_nodes/
# fy_download）emit_progress 时经 get_last_speed_bps() 读出放进 detail
# 供前端显示总下载网速。多 worker 并发时各线程互不干扰。
_speed_tls = threading.local()


def get_last_speed_bps() -> float | None:
    """返回当前线程最近一次下载的瞬时速率（字节/秒），无样本时 None。"""
    return getattr(_speed_tls, "bps", None)


def format_speed(bps: float | None) -> str:
    """速率格式化：1.8 MB/s / 356 KB/s。"""
    if bps is None or bps <= 0:
        return ""
    if bps >= 1024 * 1024:
        return f"{bps / 1024 / 1024:.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f} KB/s"
    return f"{bps:.0f} B/s"


def format_size(size_bytes: float) -> str:
    """将字节数格式化为易读字符串。"""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.2f} {units[idx]}"


def check_disk_space(
    path: Path,
    min_gb: float = DEFAULT_MIN_DISK_FREE_GB,
) -> tuple[bool, float]:
    """检查 path 所在磁盘可用空间，返回 (是否充足, 可用 GB)。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024**3)
        return free_gb >= min_gb, free_gb
    except OSError as exc:
        logger.error("磁盘空间检查失败: %s", exc)
        return False, 0.0


def download_resumable(
    session: Any,
    url: str,
    local_path: Path,
    *,
    chunk_size: int = CHUNK_SIZE,
    timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[bool, int]:
    """流式下载单个文件，支持 HTTP Range 断点续传。

    本地已存在部分文件时携带 ``Range: bytes=<existing>-``；
    服务器返回 206 追加写、200 整文件重写、416 视为已完成。

    Returns:
        (是否成功, 本次下载字节数)
    """
    local_path.parent.mkdir(parents=True, exist_ok=True)
    existing = local_path.stat().st_size if local_path.exists() else 0

    headers: dict[str, str] = {}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
        logger.info("  断点续传: 从 %s 开始", format_size(existing))

    resp = session.get(
        url,
        headers=headers,
        stream=True,
        timeout=timeout,
        allow_redirects=True,
    )

    if resp.status_code == 416:
        resp.close()
        logger.info("  本地文件已完成，跳过")
        return True, 0

    if resp.status_code not in (200, 206):
        resp.close()
        raise RuntimeError(f"HTTP {resp.status_code} 下载失败: {url}")

    mode = "ab" if resp.status_code == 206 else "wb"
    if mode == "wb" and existing > 0:
        existing = 0

    content_length = int(resp.headers.get("Content-Length", 0))
    total = content_length + existing
    downloaded = 0
    last_report = time.time()
    last_report_bytes = 0

    try:
        with open(local_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_report >= PROGRESS_INTERVAL:
                    cur = existing + downloaded
                    elapsed = now - last_report
                    bps = (
                        (downloaded - last_report_bytes) / elapsed
                        if elapsed > 0 and downloaded >= last_report_bytes
                        else None
                    )
                    if bps is not None:
                        _speed_tls.bps = bps
                    speed_txt = f" ({format_speed(bps)})" if bps else ""
                    logger.info(
                        "  下载中 %s: %s / %s%s",
                        local_path.name,
                        format_size(cur),
                        format_size(total) if total else "?",
                        speed_txt,
                    )
                    last_report = now
                    last_report_bytes = downloaded
                if progress_callback:
                    progress_callback(downloaded, total)
    finally:
        resp.close()

    return True, downloaded


def download_with_retry(
    session: Any,
    url: str,
    local_path: Path,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
    chunk_size: int = CHUNK_SIZE,
    timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
    progress_callback: Callable[[int, int], None] | None = None,
) -> bool:
    """带重试（指数退避）的续传下载封装。"""
    for attempt in range(1, max_retries + 1):
        try:
            ok, _ = download_resumable(
                session,
                url,
                local_path,
                chunk_size=chunk_size,
                timeout=timeout,
                progress_callback=progress_callback,
            )
            if ok:
                final_size = local_path.stat().st_size if local_path.exists() else 0
                if final_size <= 0:
                    raise RuntimeError("下载后文件大小为 0")
                return True
        except Exception as exc:
            logger.warning("  尝试 %d/%d 失败: %s", attempt, max_retries, exc)
            if attempt < max_retries:
                backoff = initial_backoff * (2 ** (attempt - 1))
                logger.info("  等待 %.1fs 后重试...", backoff)
                time.sleep(backoff)
            else:
                logger.error("  已达最大重试次数，放弃: %s", local_path.name)
                return False
    return False
