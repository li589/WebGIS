"""分块上传 staging（append 顺序模式）。

与 ``resumable_upload.py`` 的 **manifest** 模式并存：

- **append（本模块）**：顺序追加到 ``blob.part``，按 offset 校验。适合小文件与兼容旧客户端。
- **manifest（resumable_upload）**：按 ``chunk_index`` 独立落盘，可乱序/并行，complete 时 SHA-256 校验。

``get_upload_status`` 为统一入口：读 meta.mode，``manifest`` 时委托 resumable status
（含 ``missing_chunks``）；append 模式返回 received/total 字节进度。禁止两套语义混用同一 upload_id。
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from app.data_io.services._meta_io import load_meta as _io_load_meta
from app.data_io.services._meta_io import meta_lock as _io_meta_lock
from app.data_io.services._meta_io import save_meta as _io_save_meta
from app.data_io.services.paths import (
    MAX_UPLOAD_BYTES,
    STAGING_DIR,
    STAGING_TTL_SECONDS,
    assert_quota_available,
    ensure_imports_root,
    safe_import_child,
)
from app.data_io.services.upload_validation import (
    UploadValidationError,
    sniff_magic,
    validate_upload_filename,
)
import contextlib


class UploadAccessDenied(LookupError):
    """Raised when caller may not touch an upload session (map to 404)."""


def assert_upload_access(
    upload_id: str,
    *,
    user_id: int | None,
    role: str | None,
    source: str | None = None,
) -> dict[str, Any]:
    """Fail closed: non-owner / non-admin → UploadAccessDenied (404).

    Legacy meta without ``owner_user_id``: only admin or infrastructure
    credentials (``service_key`` / ``dev_bypass``) may proceed.
    """
    dest, meta = _load_meta(upload_id)
    if role == "admin":
        return meta
    owner = meta.get("owner_user_id")
    if owner is None:
        if source in {"service_key", "dev_bypass"}:
            return meta
        raise UploadAccessDenied(f"upload not found: {upload_id}")
    if user_id is not None and int(user_id) == int(owner):
        return meta
    raise UploadAccessDenied(f"upload not found: {upload_id}")


def init_upload(
    *,
    filename: str,
    size: int,
    content_type: str | None = None,
    resume_upload_id: str | None = None,
    owner_user_id: int | None = None,
) -> dict[str, Any]:
    ensure_imports_root()
    if size <= 0:
        raise ValueError("文件大小无效")
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(f"文件超过上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB")
    assert_quota_available(size)

    try:
        safe_name = validate_upload_filename(filename)
    except UploadValidationError as exc:
        raise ValueError(str(exc)) from exc

    # 断电/断网续传：同名同尺寸未完成会话可继续写
    if resume_upload_id:
        try:
            # 安审 2026-08-21 S-2：resume_upload_id 来自 body，须防路径穿越
            resume_dest = safe_import_child(resume_upload_id, root=STAGING_DIR)
            with _io_meta_lock(resume_dest):
                meta = _io_load_meta(resume_dest)
                existing_owner = meta.get("owner_user_id")
                if existing_owner is not None and owner_user_id is not None:
                    if int(existing_owner) != int(owner_user_id):
                        raise UploadAccessDenied(
                            f"upload not found: {resume_upload_id}"
                        )
                elif existing_owner is not None and owner_user_id is None:
                    raise UploadAccessDenied(f"upload not found: {resume_upload_id}")
                if (
                    not meta.get("complete")
                    and str(meta.get("filename")) == safe_name
                    and int(meta.get("size") or 0) == int(size)
                ):
                    part = resume_dest / "blob.part"
                    received = int(meta.get("received") or 0)
                    if part.exists():
                        with contextlib.suppress(OSError):
                            received = min(received, part.stat().st_size)
                    meta["received"] = received
                    meta["content_type"] = content_type or meta.get("content_type")
                    if owner_user_id is not None and meta.get("owner_user_id") is None:
                        meta["owner_user_id"] = int(owner_user_id)
                    _io_save_meta(resume_dest, meta)
                    return {
                        "upload_id": resume_upload_id,
                        "chunk_size_hint": 2 * 1024 * 1024,
                        "max_bytes": MAX_UPLOAD_BYTES,
                        "received": received,
                        "resumed": True,
                    }
        except FileNotFoundError:
            pass

    upload_id = f"up-{uuid.uuid4().hex[:16]}"
    dest = STAGING_DIR / upload_id
    dest.mkdir(parents=True, exist_ok=True)
    meta = {
        "upload_id": upload_id,
        "mode": "append",
        "filename": safe_name,
        "size": int(size),
        "content_type": content_type,
        "received": 0,
        "created_at": time.time(),
        "complete": False,
        "owner_user_id": int(owner_user_id) if owner_user_id is not None else None,
    }
    _io_save_meta(dest, meta)
    (dest / "blob.part").write_bytes(b"")
    return {
        "upload_id": upload_id,
        "chunk_size_hint": 2 * 1024 * 1024,
        "max_bytes": MAX_UPLOAD_BYTES,
        "received": 0,
        "resumed": False,
    }


def get_upload_status(upload_id: str) -> dict[str, Any]:
    dest, meta = _load_meta(upload_id)
    if meta.get("mode") == "manifest":
        from app.data_io.services.resumable_upload import (
            get_upload_status as get_manifest_status,
        )

        return get_manifest_status(upload_id)

    received = int(meta.get("received") or 0)
    part = dest / "blob.part"
    if part.exists() and not meta.get("complete"):
        with contextlib.suppress(OSError):
            received = max(received, part.stat().st_size)
    return {
        "upload_id": upload_id,
        "mode": "append",
        "filename": meta.get("filename"),
        "size": int(meta.get("size") or 0),
        "received": received,
        "complete": bool(meta.get("complete")),
        "path": meta.get("path"),
    }


def _load_meta(upload_id: str) -> tuple[Path, dict[str, Any]]:
    dest = safe_import_child(upload_id, root=STAGING_DIR)
    return dest, _io_load_meta(dest)


def append_chunk(
    upload_id: str, chunk: bytes, *, offset: int | None = None
) -> dict[str, Any]:
    dest = safe_import_child(upload_id, root=STAGING_DIR)
    # 持锁保护「读 meta → 校验/截断 → append 写 blob.part → 写 meta」整个 check-then-act，
    # 避免并发重试/双 complete 导致 blob.part 损坏或 meta.received 与实际大小不一致。
    with _io_meta_lock(dest):
        meta = _io_load_meta(dest)
        if meta.get("complete"):
            raise ValueError("上传已完成，不能继续写入")
        part = dest / "blob.part"
        current = int(meta.get("received") or 0)
        if part.exists():
            with contextlib.suppress(OSError):
                current = max(current, part.stat().st_size)

        if offset is not None:
            if offset > current:
                raise ValueError(f"分块偏移不匹配：期望 {current}，收到 {offset}")
            end = offset + len(chunk)
            # 幂等：该区间已完整写入（重试/断电后续传）
            if end <= current:
                return {
                    "upload_id": upload_id,
                    "received": current,
                    "size": meta["size"],
                    "skipped": True,
                }
            # 部分重叠：截断到 offset 后继续追加，避免损坏拼接
            if offset < current:
                with part.open("r+b") as f:
                    f.truncate(offset)
                current = offset
                meta["received"] = current

        new_size = current + len(chunk)
        if new_size > int(meta["size"]):
            raise ValueError("分块累计超过声明大小")
        if new_size > MAX_UPLOAD_BYTES:
            raise ValueError(f"文件超过上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB")
        with part.open("ab") as f:
            f.write(chunk)
        meta["received"] = new_size
        _io_save_meta(dest, meta)
        return {"upload_id": upload_id, "received": new_size, "size": meta["size"]}


def complete_upload(upload_id: str) -> dict[str, Any]:
    dest = safe_import_child(upload_id, root=STAGING_DIR)
    # 持锁防与 append_chunk 并发（rename 与 append 竞争）及双 complete 竞争。
    with _io_meta_lock(dest):
        meta = _io_load_meta(dest)
        # 幂等：网络重试时若已完成，直接返回，避免「会话不存在」或二次 rename
        if meta.get("complete"):
            final_name = str(meta["filename"])
            final_path = Path(str(meta.get("path") or dest / final_name))
            return {
                "upload_id": upload_id,
                "filename": final_name,
                "path": str(final_path),
                "size": int(meta["size"]),
            }
        received = int(meta.get("received") or 0)
        expected = int(meta["size"])
        if received != expected:
            raise ValueError(f"上传未完整：已收 {received} / 声明 {expected}")
        part = dest / "blob.part"
        final_name = str(meta["filename"])
        try:
            validate_upload_filename(final_name)
        except UploadValidationError as exc:
            raise ValueError(str(exc)) from exc
        final_path = dest / final_name
        if final_path.exists():
            final_path.unlink()
        part.replace(final_path)
        try:
            sniff_magic(final_path, declared_ext=final_name.rsplit(".", 1)[-1].lower())
        except UploadValidationError as exc:
            # 清理不合法载荷，避免后续被误用
            discard_upload(upload_id)
            raise ValueError(str(exc)) from exc
        meta["complete"] = True
        meta["path"] = str(final_path)
        _io_save_meta(dest, meta)
        return {
            "upload_id": upload_id,
            "filename": final_name,
            "path": str(final_path),
            "size": expected,
        }


def resolve_upload_path(upload_id: str) -> Path:
    dest, meta = _load_meta(upload_id)
    if not meta.get("complete"):
        raise ValueError(f"上传未完成: {upload_id}")
    path = Path(str(meta.get("path") or dest / meta["filename"]))
    if not path.exists():
        raise FileNotFoundError(f"上传文件缺失: {upload_id}")
    return path


def discard_upload(upload_id: str) -> None:
    # 安审 2026-08-21 S-1：upload_id 可来自 URL/body，拼接前防路径穿越
    # （否则 rmtree 可删除 staging 根外任意目录）。
    dest = safe_import_child(upload_id, root=STAGING_DIR)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)


def cleanup_expired_staging(*, ttl_seconds: int | None = None) -> int:
    """清理过期 staging 上传目录。返回删除数量。"""
    ensure_imports_root()
    ttl = STAGING_TTL_SECONDS if ttl_seconds is None else max(60, int(ttl_seconds))
    now = time.time()
    removed = 0
    for child in list(STAGING_DIR.iterdir()):
        if not child.is_dir():
            continue
        meta_path = child / "meta.json"
        created = None
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                raw_created = meta.get("created_at")
                if raw_created is not None:
                    created = float(raw_created)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                created = None
        if created is None:
            try:
                created = child.stat().st_mtime
            except OSError:
                continue
        if now - created < ttl:
            continue
        shutil.rmtree(child, ignore_errors=True)
        removed += 1
    return removed
