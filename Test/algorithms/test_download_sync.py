"""ingest/_download_sync.py：共享目录并发下载协调单测。"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from ingest._download_sync import (
    download_claimed_file,
    is_complete_file,
    make_unique_part_path,
    release_claim,
    replace_with_retry,
    try_claim_download,
    wait_until_complete,
)


def test_make_unique_part_path_differs_per_call(tmp_path: Path) -> None:
    dest = tmp_path / "granule.h5"
    a = make_unique_part_path(dest)
    b = make_unique_part_path(dest)
    assert a != b
    assert a.name.startswith("granule.h5.part.")
    assert a.parent == dest.parent


def test_claim_is_exclusive(tmp_path: Path) -> None:
    dest = tmp_path / "g.h5"
    first = try_claim_download(dest)
    second = try_claim_download(dest)
    assert first is not None
    assert second is None
    release_claim(first)
    third = try_claim_download(dest)
    assert third is not None
    release_claim(third)


def test_replace_with_retry_when_peer_already_finalized(tmp_path: Path) -> None:
    dest = tmp_path / "g.h5"
    dest.write_bytes(b"peer")
    part = tmp_path / "g.h5.part.1.abcd"
    part.write_bytes(b"mine")
    replace_with_retry(part, dest, retries=3, delay=0.01)
    assert dest.read_bytes() == b"peer"
    assert not part.exists()


def test_replace_with_retry_moves_part(tmp_path: Path) -> None:
    dest = tmp_path / "g.h5"
    part = tmp_path / "g.h5.part.1.abcd"
    part.write_bytes(b"payload")
    replace_with_retry(part, dest, retries=3, delay=0.01)
    assert dest.read_bytes() == b"payload"
    assert not part.exists()


def test_download_claimed_skips_existing(tmp_path: Path) -> None:
    dest = tmp_path / "g.h5"
    dest.write_bytes(b"done")
    calls: list[Path] = []

    def do_download(part: Path) -> bool:
        calls.append(part)
        return True

    assert download_claimed_file(dest=dest, do_download=do_download) == "skipped"
    assert calls == []


def test_download_claimed_downloads_once(tmp_path: Path) -> None:
    dest = tmp_path / "g.h5"

    def do_download(part: Path) -> bool:
        part.write_bytes(b"data")
        return True

    assert download_claimed_file(dest=dest, do_download=do_download) == "downloaded"
    assert dest.read_bytes() == b"data"
    assert not list(tmp_path.glob("*.part.*"))
    assert not list(tmp_path.glob("*.claim"))


def test_concurrent_claim_one_downloads_one_waits(tmp_path: Path) -> None:
    dest = tmp_path / "g.h5"
    outcomes: list[str] = []
    lock = threading.Lock()

    claim = try_claim_download(dest)
    assert claim is not None

    def waiter_side() -> None:
        status = download_claimed_file(
            dest=dest,
            do_download=lambda _p: (_ for _ in ()).throw(AssertionError("no")),
            wait_timeout=5.0,
        )
        with lock:
            outcomes.append(status)

    t = threading.Thread(target=waiter_side)
    t.start()
    time.sleep(0.2)

    part = make_unique_part_path(dest)
    part.write_bytes(b"payload")
    replace_with_retry(part, dest)
    release_claim(claim)
    t.join(timeout=5)

    assert is_complete_file(dest)
    assert outcomes == ["skipped"]


def test_wait_until_complete_false_when_claim_released_without_file(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "g.h5"
    claim = try_claim_download(dest)
    assert claim is not None

    def releaser() -> None:
        time.sleep(0.2)
        release_claim(claim)

    t = threading.Thread(target=releaser)
    t.start()
    assert wait_until_complete(dest, timeout=2.0, poll=0.05) is False
    t.join(timeout=2)
