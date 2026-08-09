"""Manifest 断点续传：乱序块、缺块 status、SHA 失败、幂等重传、并行同 index。"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.data_io.services import paths as import_paths
from app.data_io.services import resumable_upload as resumable_mod
from app.data_io.services import upload as upload_mod
from app.data_io.services.resumable_upload import (
    complete_resumable,
    get_upload_status,
    init_resumable,
    upload_chunk_by_index,
)
from app.data_io.services.upload import get_upload_status as unified_status


@pytest.fixture()
def staging_tmp(tmp_path, monkeypatch):
    root = tmp_path / "imports_output"
    imports_dir = root / "imports"
    staging = imports_dir / "_staging"
    for mod in (import_paths, upload_mod, resumable_mod):
        if hasattr(mod, "IMPORTS_DIR"):
            monkeypatch.setattr(mod, "IMPORTS_DIR", imports_dir)
        if hasattr(mod, "STAGING_DIR"):
            monkeypatch.setattr(mod, "STAGING_DIR", staging)
    import_paths.ensure_imports_root()
    return staging


def _tif_payload(n: int = 64) -> bytes:
    # GeoTIFF-ish magic so sniff_magic accepts .tif
    return b"II*\x00" + bytes((i % 256 for i in range(max(0, n - 4))))


def test_resumable_out_of_order_and_missing_status(staging_tmp):
    payload = _tif_payload(100)
    chunk_size = 30
    total = (len(payload) + chunk_size - 1) // chunk_size
    digest = hashlib.sha256(payload).hexdigest()
    init = init_resumable(
        filename="demo.tif",
        size=len(payload),
        chunk_size=chunk_size,
        sha256_expected=digest,
    )
    upload_id = init["upload_id"]
    assert init["total_chunks"] == total

    # 乱序：先传最后一块再传中间
    chunks = [payload[i * chunk_size : (i + 1) * chunk_size] for i in range(total)]
    upload_chunk_by_index(upload_id, total - 1, chunks[total - 1])
    st = get_upload_status(upload_id)
    assert st["missing_chunks"] == list(range(total - 1))
    assert unified_status(upload_id)["mode"] == "manifest"

    for i in (0, 2, 1):
        if i < total:
            upload_chunk_by_index(upload_id, i, chunks[i])

    st2 = get_upload_status(upload_id)
    assert st2["missing_chunks"] == []
    done = complete_resumable(upload_id)
    assert done["size"] == len(payload)
    assert done.get("sha256_verified") is True


def test_resumable_sha256_mismatch(staging_tmp):
    payload = _tif_payload(40)
    init = init_resumable(
        filename="bad.tif",
        size=len(payload),
        chunk_size=20,
        sha256_expected="0" * 64,
    )
    upload_id = init["upload_id"]
    upload_chunk_by_index(upload_id, 0, payload[:20])
    upload_chunk_by_index(upload_id, 1, payload[20:])
    with pytest.raises(ValueError, match="SHA"):
        complete_resumable(upload_id)


def test_resumable_idempotent_reupload_same_index(staging_tmp):
    payload = _tif_payload(50)
    init = init_resumable(filename="idem.tif", size=len(payload), chunk_size=25)
    upload_id = init["upload_id"]
    first = upload_chunk_by_index(upload_id, 0, payload[:25])
    second = upload_chunk_by_index(upload_id, 0, payload[:25])
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    upload_chunk_by_index(upload_id, 1, payload[25:])
    done = complete_resumable(upload_id)
    assert done["upload_id"] == upload_id
    # 幂等 complete
    again = complete_resumable(upload_id)
    assert again["upload_id"] == upload_id


def test_resumable_parallel_same_index(staging_tmp):
    payload = _tif_payload(60)
    init = init_resumable(filename="par.tif", size=len(payload), chunk_size=30)
    upload_id = init["upload_id"]
    chunk0 = payload[:30]
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            upload_chunk_by_index(upload_id, 0, chunk0)
        except BaseException as exc:  # noqa: BLE001 — collect any race error
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(_worker) for _ in range(8)]
        for f in futs:
            f.result()
    assert not errors
    st = get_upload_status(upload_id)
    assert 0 in st["received_chunks"]
    upload_chunk_by_index(upload_id, 1, payload[30:])
    complete_resumable(upload_id)


# ── append 模式并发（CC-1 修复验证）─────────────────────────────────────────
# 2026-08-10：upload.py append 模式加 _meta_lock + 原子 save_meta 前，
# 并发重试同 offset 会丢 meta 记录、双 complete 会竞争 rename。以下用例锁校验修复。


def test_append_concurrent_same_offset_no_corruption(staging_tmp):
    """并发同 offset 重传：blob.part 不损坏、meta.received 与实际大小一致。"""
    from app.data_io.services.upload import append_chunk, complete_upload, init_upload

    payload = _tif_payload(120)
    upload_id = init_upload(filename="append_par.tif", size=len(payload))["upload_id"]
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            # 所有线程都传同一 offset=0 的完整 payload（模拟客户端重试风暴）
            append_chunk(upload_id, payload, offset=0)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_worker) for _ in range(8)]
        for f in futs:
            f.result()
    assert not errors

    # blob.part 实际大小应等于 payload（不会因并发 append 翻倍或截断）
    from app.data_io.services.upload import get_upload_status

    st = get_upload_status(upload_id)
    assert st["received"] == len(payload)
    # 完成并校验内容
    done = complete_upload(upload_id)
    assert done["size"] == len(payload)
    from app.data_io.services.upload import resolve_upload_path

    assert resolve_upload_path(upload_id).read_bytes() == payload


def test_append_concurrent_double_complete_idempotent(staging_tmp):
    """并发双 complete：恰好一个完成 rename，另一个幂等返回，无报错。"""
    from app.data_io.services.upload import append_chunk, complete_upload, init_upload

    payload = _tif_payload(80)
    upload_id = init_upload(filename="dbl_complete.tif", size=len(payload))["upload_id"]
    append_chunk(upload_id, payload, offset=0)

    results: list[dict] = []
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            results.append(complete_upload(upload_id))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(_worker) for _ in range(4)]
        for f in futs:
            f.result()
    assert not errors
    assert len(results) == 4
    # 所有返回应一致（幂等）
    sizes = {r["size"] for r in results}
    assert sizes == {len(payload)}


def test_append_concurrent_chunk_then_complete_safe(staging_tmp):
    """append 与 complete 并发：不损坏文件，竞态结果自洽。

    合法竞态结果：
    - append 报「上传已完成」（complete 先完成）/「未完整」（offset 不匹配）
    - complete 报「未完整」（append 还没写完）/ 成功
    任何导致文件损坏或非上述语义的报错都视为失败。
    """
    from app.data_io.services.upload import append_chunk, complete_upload, init_upload

    payload = _tif_payload(200)
    upload_id = init_upload(filename="race.tif", size=len(payload))["upload_id"]
    errors: list[BaseException] = []

    def _appender() -> None:
        try:
            append_chunk(upload_id, payload, offset=0)
        except ValueError as exc:
            # 「上传已完成」/「未完整」都是 append 与 complete 竞态的合法结果
            if "已完成" not in str(exc) and "未完整" not in str(exc):
                errors.append(exc)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def _completer() -> None:
        try:
            complete_upload(upload_id)
        except ValueError as exc:
            if "未完整" not in str(exc):
                errors.append(exc)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        # 2 个 append（同 offset，模拟重试）+ 2 个 complete
        futs = [pool.submit(_appender), pool.submit(_appender),
                pool.submit(_completer), pool.submit(_completer)]
        for f in futs:
            f.result()
    assert not errors

    # 最终状态应自洽：complete 后内容正确
    from app.data_io.services.upload import get_upload_status, resolve_upload_path

    st = get_upload_status(upload_id)
    if st["complete"]:
        assert resolve_upload_path(upload_id).read_bytes() == payload
    else:
        # 若 complete 都因竞态未成功，补一次完整 append + complete
        append_chunk(upload_id, payload, offset=0)
        complete_upload(upload_id)
        assert resolve_upload_path(upload_id).read_bytes() == payload
