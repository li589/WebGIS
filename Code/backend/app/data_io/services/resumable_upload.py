"""断点续传上传：分块清单模式 + SHA-256 校验 + 并行分块支持。

与 ``upload.py`` 的 append-only 模式并存：
- **append 模式**（现有）：顺序追加到 blob.part，offset 校验。适合小文件。
- **manifest 模式**（本模块）：每块独立存储，可乱序/并行上传，支持断点续传。

manifest 模式工作流::

    1. init_resumable(filename, size, chunk_size, total_chunks, sha256?)
       → 返回 upload_id + chunk 划分信息
    2. upload_chunk_by_index(upload_id, index, data)
       → 每块独立写入 chunk_{index}.part，更新 manifest
       → 客户端可并行上传、失败重试单块
    3. get_upload_status(upload_id)
       → 返回已收/缺失块列表（断点续传查询）
    4. complete_resumable(upload_id)
       → 校验全部块到齐 → 拼接 → SHA-256 校验 → 魔数校验
    5. discard_upload(upload_id)
       → 清理（与 append 模式共用）
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from app.data_io.services.paths import (
    MAX_UPLOAD_BYTES,
    STAGING_DIR,
    assert_quota_available,
    ensure_imports_root,
)
from app.data_io.services.upload_validation import (
    UploadValidationError,
    sniff_magic,
    validate_upload_filename,
)

# 默认分块大小：4 MiB（兼顾网络效率与内存占用）
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
# 单块最大大小：64 MiB（防止异常大块耗尽内存）
MAX_CHUNK_SIZE = 64 * 1024 * 1024
# 最大分块数（防止 manifest 爆炸）
MAX_TOTAL_CHUNKS = 65536


def init_resumable(
    *,
    filename: str,
    size: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    total_chunks: int | None = None,
    sha256_expected: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """初始化断点续传上传会话。

    Args:
        filename: 原始文件名
        size: 文件总字节数
        chunk_size: 每块大小（字节），默认 4 MiB
        total_chunks: 总块数；若为 None 则自动计算 = ceil(size / chunk_size)
        sha256_expected: 客户端提供的文件 SHA-256（十六进制），完成后校验
        content_type: MIME 类型

    Returns:
        ``{upload_id, chunk_size, total_chunks, size, sha256_expected}``
    """
    ensure_imports_root()
    if size <= 0:
        raise ValueError("文件大小无效")
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(f"文件超过上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB")
    if chunk_size <= 0 or chunk_size > MAX_CHUNK_SIZE:
        raise ValueError(f"分块大小无效（需 1-{MAX_CHUNK_SIZE // (1024 * 1024)} MiB）")
    if total_chunks is None:
        total_chunks = (size + chunk_size - 1) // chunk_size
    if total_chunks <= 0 or total_chunks > MAX_TOTAL_CHUNKS:
        raise ValueError(f"分块数无效（需 1-{MAX_TOTAL_CHUNKS}）")
    # 校验 chunk_size × total_chunks 覆盖 size
    if chunk_size * (total_chunks - 1) >= size:
        raise ValueError("分块参数与文件大小不匹配（块数过多）")

    assert_quota_available(size)

    try:
        safe_name = validate_upload_filename(filename)
    except UploadValidationError as exc:
        raise ValueError(str(exc)) from exc

    upload_id = f"up-{uuid.uuid4().hex[:16]}"
    dest = STAGING_DIR / upload_id
    dest.mkdir(parents=True, exist_ok=True)
    meta = {
        "upload_id": upload_id,
        "mode": "manifest",
        "filename": safe_name,
        "size": int(size),
        "chunk_size": int(chunk_size),
        "total_chunks": int(total_chunks),
        "sha256_expected": sha256_expected,
        "content_type": content_type,
        "received_chunks": [],
        "received_bytes": 0,
        "created_at": time.time(),
        "complete": False,
    }
    (dest / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return {
        "upload_id": upload_id,
        "chunk_size": int(chunk_size),
        "total_chunks": int(total_chunks),
        "size": int(size),
        "sha256_expected": sha256_expected,
    }


def _load_meta(upload_id: str) -> tuple[Path, dict[str, Any]]:
    """加载 manifest 模式的 meta.json。"""
    dest = STAGING_DIR / upload_id
    meta_path = dest / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"上传会话不存在: {upload_id}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("mode") != "manifest":
        raise ValueError(f"上传会话非 manifest 模式: {upload_id}")
    return dest, meta


def _save_meta(dest: Path, meta: dict[str, Any]) -> None:
    """原子写 meta.json：先写临时文件再 os.replace，避免并发读读到半写内容。"""
    meta_path = dest / "meta.json"
    tmp_path = meta_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, meta_path)


def _meta_lock(dest: Path):
    """跨进程/线程安全的 meta 文件锁（Windows 上用 msvcrt，否则 fcntl）。"""
    from contextlib import contextmanager

    @contextmanager
    def _lock():
        lock_path = dest / "meta.lock"
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

    return _lock()


def upload_chunk_by_index(
    upload_id: str, chunk_index: int, data: bytes
) -> dict[str, Any]:
    """按索引上传单个分块（可乱序、可并行、可重试）。

    Args:
        upload_id: 上传会话 ID
        chunk_index: 块索引（0-based）
        data: 块数据

    Returns:
        ``{upload_id, chunk_index, received_chunks, total_chunks, complete}``
    """
    dest = STAGING_DIR / upload_id

    with _meta_lock(dest):
        dest, meta = _load_meta(upload_id)
        if meta.get("complete"):
            raise ValueError("上传已完成，不能继续写入")

        total_chunks = int(meta["total_chunks"])
        chunk_size = int(meta["chunk_size"])
        size = int(meta["size"])

        if chunk_index < 0 or chunk_index >= total_chunks:
            raise ValueError(
                f"块索引越界: {chunk_index}（有效范围 0-{total_chunks - 1}）"
            )

        received: list[int] = list(meta.get("received_chunks") or [])
        if chunk_index in received:
            # 幂等：已收到的块直接返回（重试安全）
            return {
                "upload_id": upload_id,
                "chunk_index": chunk_index,
                "received_chunks": received,
                "total_chunks": total_chunks,
                "complete": len(received) >= total_chunks,
                "duplicate": True,
            }

        # 校验块大小：最后一块可以小于 chunk_size
        expected_size = chunk_size
        if chunk_index == total_chunks - 1:
            expected_size = size - chunk_size * (total_chunks - 1)
        if len(data) != expected_size:
            raise ValueError(
                f"块 {chunk_index} 大小不匹配：期望 {expected_size}，收到 {len(data)}"
            )

        # 写入独立块文件
        chunk_path = dest / f"chunk_{chunk_index:06d}.part"
        chunk_path.write_bytes(data)

        # 更新 manifest（持锁，避免并行同 index / 并发写坏 JSON）
        received.append(chunk_index)
        received.sort()
        meta["received_chunks"] = received
        meta["received_bytes"] = int(meta.get("received_bytes") or 0) + len(data)
        _save_meta(dest, meta)

        return {
            "upload_id": upload_id,
            "chunk_index": chunk_index,
            "received_chunks": received,
            "total_chunks": total_chunks,
            "complete": len(received) >= total_chunks,
            "duplicate": False,
        }


def get_upload_status(upload_id: str) -> dict[str, Any]:
    """查询上传状态（断点续传核心：客户端据此补传缺失块）。

    Returns:
        ``{upload_id, mode, size, chunk_size, total_chunks,
           received_chunks, missing_chunks, received_bytes, complete}``
    """
    dest, meta = _load_meta(upload_id)
    total_chunks = int(meta["total_chunks"])
    received: list[int] = list(meta.get("received_chunks") or [])
    received_set = set(received)
    missing = [i for i in range(total_chunks) if i not in received_set]

    return {
        "upload_id": upload_id,
        "mode": "manifest",
        "filename": meta.get("filename"),
        "size": int(meta["size"]),
        "chunk_size": int(meta["chunk_size"]),
        "total_chunks": total_chunks,
        "received_chunks": received,
        "missing_chunks": missing,
        "received_bytes": int(meta.get("received_bytes") or 0),
        "complete": bool(meta.get("complete")),
        "sha256_expected": meta.get("sha256_expected"),
    }


def complete_resumable(upload_id: str) -> dict[str, Any]:
    """完成断点续传上传：校验块完整性 → 拼接 → SHA-256 校验 → 魔数校验。

    幂等：若已完成，直接返回已有结果。
    """
    dest, meta = _load_meta(upload_id)
    if meta.get("complete"):
        final_name = str(meta["filename"])
        final_path = Path(str(meta.get("path") or dest / final_name))
        return {
            "upload_id": upload_id,
            "filename": final_name,
            "path": str(final_path),
            "size": int(meta["size"]),
            "sha256_verified": meta.get("sha256_verified", False),
        }

    total_chunks = int(meta["total_chunks"])
    received: list[int] = list(meta.get("received_chunks") or [])
    if len(received) != total_chunks:
        missing = [i for i in range(total_chunks) if i not in set(received)]
        raise ValueError(
            f"上传未完整：已收 {len(received)}/{total_chunks} 块，"
            f"缺失块: {missing[:20]}{'...' if len(missing) > 20 else ''}"
        )

    # 拼接所有块到最终文件
    final_name = str(meta["filename"])
    final_path = dest / final_name
    if final_path.exists():
        final_path.unlink()

    sha256_hasher = hashlib.sha256()
    size = int(meta["size"])
    written = 0
    with final_path.open("wb") as out:
        for idx in range(total_chunks):
            chunk_path = dest / f"chunk_{idx:06d}.part"
            if not chunk_path.exists():
                raise ValueError(f"块文件缺失: {idx}")
            chunk_data = chunk_path.read_bytes()
            out.write(chunk_data)
            sha256_hasher.update(chunk_data)
            written += len(chunk_data)

    if written != size:
        raise ValueError(f"拼接后大小不匹配：期望 {size}，实际 {written}")

    # SHA-256 校验（若客户端提供了期望值）
    actual_sha256 = sha256_hasher.hexdigest()
    sha256_verified = False
    expected = meta.get("sha256_expected")
    if expected:
        if actual_sha256.lower() != expected.lower():
            # 校验失败：清理拼接文件，保留分块供重试
            final_path.unlink(missing_ok=True)
            raise ValueError(f"SHA-256 校验失败：期望 {expected}，实际 {actual_sha256}")
        sha256_verified = True

    # 魔数校验（与 append 模式一致）
    try:
        sniff_magic(final_path, declared_ext=final_name.rsplit(".", 1)[-1].lower())
    except UploadValidationError as exc:
        # 清理不合法载荷
        _discard_resumable(upload_id)
        raise ValueError(str(exc)) from exc

    # 清理分块文件
    for idx in range(total_chunks):
        chunk_path = dest / f"chunk_{idx:06d}.part"
        chunk_path.unlink(missing_ok=True)

    # 更新 manifest
    meta["complete"] = True
    meta["path"] = str(final_path)
    meta["sha256_actual"] = actual_sha256
    meta["sha256_verified"] = sha256_verified
    _save_meta(dest, meta)

    return {
        "upload_id": upload_id,
        "filename": final_name,
        "path": str(final_path),
        "size": size,
        "sha256_actual": actual_sha256,
        "sha256_verified": sha256_verified,
    }


def _discard_resumable(upload_id: str) -> None:
    """清理 manifest 模式上传目录。"""
    dest = STAGING_DIR / upload_id
    if dest.exists():
        import shutil

        shutil.rmtree(dest, ignore_errors=True)
