"""Tests for HTTP Range resume in source_fetcher.py (M4/P3).

覆盖：断点续传（206 追加）、Range 被忽略（200 整写）、416 暂存过期重下、
ETag 变更重下、瞬时错误退避重试、重试预算耗尽保留暂存、404 立即失败、
崩溃恢复（完整暂存免网络直传）。全部离线 mock，无真实网络。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from app.services.source_fetcher import HttpSourceFetcher


class _FakeHTTPResponse:
    """Mimics urllib response: read()/headers/status + context manager."""

    def __init__(
        self,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        status: int = 200,
    ) -> None:
        self._body = body
        self._pos = 0
        self.headers = headers or {}
        self.status = status

    def getcode(self) -> int:
        return self.status

    def read(self, size: int = -1) -> bytes:
        if self._pos >= len(self._body):
            return b""
        if size is None or size < 0:
            data = self._body[self._pos :]
            self._pos = len(self._body)
            return data
        data = self._body[self._pos : self._pos + size]
        self._pos += len(data)
        return data

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class _PutStreamCapture:
    """Capture put_stream args at call time (stream is closed after the call)."""

    def __init__(self, content_length: int) -> None:
        self.content_length = content_length
        self.data = b""
        self.kwargs: dict[str, object] = {}

    def __call__(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = dict(kwargs)
        self.data = kwargs["stream"].read()
        return SimpleNamespace(
            content_length=self.content_length, file_path=Path("artifacts/test")
        )


def _staging_paths(staging: Path, artifact_key: str) -> tuple[Path, Path]:
    digest = hashlib.sha1(artifact_key.encode("utf-8")).hexdigest()[:16]
    return staging / f"{digest}.part", staging / f"{digest}.json"


def _seed_staging(
    staging: Path,
    artifact_key: str,
    partial: bytes,
    *,
    total: int | None,
    etag: str | None = None,
    content_type: str | None = "application/octet-stream",
) -> tuple[Path, Path]:
    part_path, sidecar_path = _staging_paths(staging, artifact_key)
    part_path.parent.mkdir(parents=True, exist_ok=True)
    part_path.write_bytes(partial)
    sidecar_path.write_text(
        json.dumps({"total": total, "etag": etag, "content_type": content_type}),
        encoding="utf-8",
    )
    return part_path, sidecar_path


def _run_fetch(
    staging: Path,
    ref_id: str,
    responses: list[object],
    body_length: int,
) -> tuple[object, _PutStreamCapture, MagicMock]:
    """Patch urlopen with side_effect responses; run fetch; return (result, capture, urlopen_mock)."""
    staging.mkdir(parents=True, exist_ok=True)
    capture = _PutStreamCapture(content_length=body_length)
    with (
        patch("app.core.ssrf.safe_urlopen", side_effect=responses) as urlopen_mock,
        patch(
            "app.services.source_fetcher._http_staging_dir",
            return_value=Path(staging),
        ),
        patch("app.services.source_fetcher.time.sleep"),
        patch("app.services.source_fetcher.object_store") as mock_store,
    ):
        mock_store.put_stream.side_effect = capture
        result = HttpSourceFetcher().fetch(
            ref_id=ref_id,
            source_uri=f"http://example.com/{ref_id}.bin",
            artifact_key_prefix="artifacts/test",
        )
    return result, capture, urlopen_mock


def test_resume_appends_from_partial_206(tmp_path: Path) -> None:
    """已有半段暂存 → 请求带 Range；206 追加后入库完整字节。"""
    body = b"0123456789" * 10  # 100 bytes
    head, tail = body[:40], body[40:]
    artifact_key = "artifacts/test/ref-resume"

    staging = tmp_path / "staging"
    _seed_staging(staging, artifact_key, head, total=len(body), etag='"v1"')

    partial_resp = _FakeHTTPResponse(
        body=tail,
        status=206,
        headers={
            "Content-Type": "application/octet-stream",
            "ETag": '"v1"',
            "Content-Range": f"bytes 40-{len(body) - 1}/{len(body)}",
        },
    )

    result, capture, urlopen_mock = _run_fetch(
        staging, "ref-resume", [partial_resp], len(body)
    )

    assert result.success, f"resume fetch should succeed: {result.error}"
    assert capture.data == body, "stored bytes must equal full body"
    assert capture.kwargs["length"] == len(body), "declared length must be total size"
    sent_headers = urlopen_mock.call_args.kwargs["headers"]
    assert sent_headers["Range"] == "bytes=40-", "Range header must resume at 40"
    # 成功后暂存清理
    part_path, sidecar_path = _staging_paths(staging, artifact_key)
    assert not part_path.exists(), "staging .part must be removed after success"
    assert not sidecar_path.exists(), "staging sidecar must be removed after success"


def test_range_ignored_falls_back_to_full_rewrite(tmp_path: Path) -> None:
    """服务端忽略 Range 返回 200 整文件 → 整写覆盖，最终字节完整。"""
    body = b"full-body-" * 12
    artifact_key = "artifacts/test/ref-ignored"

    staging = tmp_path / "staging"
    _seed_staging(staging, artifact_key, body[:10], total=len(body), etag='"v1"')

    full_resp = _FakeHTTPResponse(
        body=body,
        status=200,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(body)),
        },
    )

    result, capture, _ = _run_fetch(staging, "ref-ignored", [full_resp], len(body))

    assert result.success, f"fetch should succeed: {result.error}"
    assert capture.data == body, "stored bytes must be the full rewritten body"


def test_416_stale_part_restarts(tmp_path: Path) -> None:
    """416（暂存超过资源当前大小）→ 截断暂存整体重下。"""
    body = b"shorter-now"
    artifact_key = "artifacts/test/ref-stale"

    staging = tmp_path / "staging"
    # 暂存 50 字节且未完成（sidecar total=60），但资源现在只有 11 字节
    _seed_staging(staging, artifact_key, b"x" * 50, total=60, etag='"old"')

    error_416 = HTTPError(
        "http://example.com/ref-stale.bin", 416, "Range Not Satisfiable", None, None
    )
    full_resp = _FakeHTTPResponse(
        body=body,
        status=200,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(body)),
        },
    )

    result, capture, urlopen_mock = _run_fetch(
        staging, "ref-stale", [error_416, full_resp], len(body)
    )

    assert result.success, f"fetch should succeed after restart: {result.error}"
    assert capture.data == body, "stored bytes must be the fresh full body"
    assert urlopen_mock.call_count == 2, "416 should trigger exactly one restart"


def test_etag_change_on_206_restarts(tmp_path: Path) -> None:
    """206 但 ETag 与 sidecar 不一致（源内容变更）→ 整体重下。"""
    body = b"new-content-" * 8
    artifact_key = "artifacts/test/ref-etag"

    staging = tmp_path / "staging"
    _seed_staging(staging, artifact_key, body[:20], total=100, etag='"old"')

    stale_206 = _FakeHTTPResponse(
        body=b"whatever",
        status=206,
        headers={
            "Content-Type": "application/octet-stream",
            "ETag": '"new"',
            "Content-Range": "bytes 20-99/100",
        },
    )
    full_resp = _FakeHTTPResponse(
        body=body,
        status=200,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(body)),
        },
    )

    result, capture, urlopen_mock = _run_fetch(
        staging, "ref-etag", [stale_206, full_resp], len(body)
    )

    assert result.success, f"fetch should succeed after etag restart: {result.error}"
    assert capture.data == body, "stored bytes must be the new full body"
    assert urlopen_mock.call_count == 2, "etag mismatch should trigger one restart"


def test_transient_error_retries_with_backoff(tmp_path: Path) -> None:
    """首个尝试网络失败 → 退避后重试成功（sleep 被调用，共 2 次请求）。"""
    body = b"retry-me" * 5
    good_resp = _FakeHTTPResponse(
        body=body,
        status=200,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(body)),
        },
    )

    staging = tmp_path / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    with (
        patch(
            "app.core.ssrf.safe_urlopen",
            side_effect=[URLError("boom"), good_resp],
        ) as urlopen_mock,
        patch(
            "app.services.source_fetcher._http_staging_dir",
            return_value=staging,
        ),
        patch("app.services.source_fetcher.time.sleep") as sleep_mock,
        patch("app.services.source_fetcher.object_store") as mock_store,
    ):
        capture = _PutStreamCapture(content_length=len(body))
        mock_store.put_stream.side_effect = capture
        result = HttpSourceFetcher().fetch(
            ref_id="ref-retry",
            source_uri="http://example.com/ref-retry.bin",
            artifact_key_prefix="artifacts/test",
        )

    assert result.success, f"fetch should succeed after retry: {result.error}"
    assert capture.data == body, "stored bytes must equal body"
    assert urlopen_mock.call_count == 2, "exactly one retry expected"
    assert sleep_mock.call_count == 1, "backoff sleep expected between attempts"


def test_retry_budget_exhausted_keeps_partial(tmp_path: Path) -> None:
    """瞬时错误超过 3 次重试预算 → 失败返回，暂存 .part 保留供下次续传。"""
    body = b"never-finishes"
    artifact_key = "artifacts/test/ref-exhaust"

    staging = tmp_path / "staging"
    # 预置 5 字节暂存；每次请求都网络失败
    _seed_staging(staging, artifact_key, body[:5], total=len(body))

    with (
        patch(
            "app.core.ssrf.safe_urlopen",
            side_effect=URLError("down"),
        ) as urlopen_mock,
        patch(
            "app.services.source_fetcher._http_staging_dir",
            return_value=staging,
        ),
        patch("app.services.source_fetcher.time.sleep"),
        patch("app.services.source_fetcher.object_store") as mock_store,
    ):
        result = HttpSourceFetcher().fetch(
            ref_id="ref-exhaust",
            source_uri="http://example.com/ref-exhaust.bin",
            artifact_key_prefix="artifacts/test",
        )

    assert not result.success, "fetch must fail after retry budget exhausted"
    assert "HTTP fetch failed" in (result.error or ""), "error must surface failure"
    mock_store.put_stream.assert_not_called(), "no artifact should be stored"
    assert urlopen_mock.call_count == 4, "1 initial + 3 retries expected"
    part_path, _ = _staging_paths(staging, artifact_key)
    assert part_path.read_bytes() == body[:5], "partial staging must be preserved"


def test_non_transient_404_fails_immediately(tmp_path: Path) -> None:
    """404 非瞬时错误 → 不重试，单次请求即失败。"""
    staging = tmp_path / "staging"
    with (
        patch(
            "app.core.ssrf.safe_urlopen",
            side_effect=HTTPError(
                "http://example.com/ref-404.bin", 404, "Not Found", None, None
            ),
        ) as urlopen_mock,
        patch(
            "app.services.source_fetcher._http_staging_dir",
            return_value=staging,
        ),
        patch("app.services.source_fetcher.object_store"),
    ):
        result = HttpSourceFetcher().fetch(
            ref_id="ref-404",
            source_uri="http://example.com/ref-404.bin",
            artifact_key_prefix="artifacts/test",
        )

    assert not result.success, "404 must fail"
    assert urlopen_mock.call_count == 1, "404 must not be retried"


def test_completed_staging_skips_network(tmp_path: Path) -> None:
    """崩溃恢复：暂存已完整（size == sidecar total）→ 免网络直接入库。"""
    body = b"already-complete"
    artifact_key = "artifacts/test/ref-crashed"

    staging = tmp_path / "staging"
    _seed_staging(
        staging,
        artifact_key,
        body,
        total=len(body),
        etag='"v1"',
        content_type="application/x-ndjson",
    )

    result, capture, urlopen_mock = _run_fetch(staging, "ref-crashed", [], len(body))

    assert result.success, f"recovery fetch should succeed: {result.error}"
    urlopen_mock.assert_not_called(), "complete staging must skip network"
    assert capture.data == body, "stored bytes must come from staging file"
    assert (
        capture.kwargs["content_type"] == "application/x-ndjson"
    ), "content_type must be restored from sidecar"


def test_short_body_triggers_resume_retry(tmp_path: Path) -> None:
    """首次响应体短于声明总长（IncompleteRead）→ 重试时 Range 续传补齐。"""
    body = b"truncate-me-" * 10  # 120 bytes
    artifact_key = "artifacts/test/ref-short"

    staging = tmp_path / "staging"
    short_resp = _FakeHTTPResponse(
        body=body[:80],
        status=200,
        headers={
            "Content-Type": "application/octet-stream",
            "ETag": '"v1"',
            "Content-Length": str(len(body)),
        },
    )
    rest_resp = _FakeHTTPResponse(
        body=body[80:],
        status=206,
        headers={
            "Content-Type": "application/octet-stream",
            "ETag": '"v1"',
            "Content-Range": f"bytes 80-{len(body) - 1}/{len(body)}",
        },
    )

    result, capture, urlopen_mock = _run_fetch(
        staging, "ref-short", [short_resp, rest_resp], len(body)
    )

    assert result.success, f"fetch should complete after resume retry: {result.error}"
    assert capture.data == body, "stored bytes must be the complete body"
    second_headers = urlopen_mock.call_args_list[1].kwargs["headers"]
    assert second_headers["Range"] == "bytes=80-", "retry must resume at byte 80"
