"""ingest/_http_resume.py 共享续传工具单元测试。

覆盖：format_size / check_disk_space / download_resumable（200 全量、206 续传、
416 已完成、其它状态码报错）/ download_with_retry（重试后成功、耗尽返回 False）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ingest._http_resume import (
    check_disk_space,
    download_resumable,
    download_with_retry,
    format_size,
)


class _FakeResponse:
    def __init__(self, status_code: int, chunks: list[bytes], headers: dict[str, str]):
        self.status_code = status_code
        self._chunks = chunks
        self.headers = headers
        self.closed = False

    def iter_content(self, chunk_size: int = 8192):  # noqa: ARG002
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


class _FakeSession:
    """按脚本回放响应，并记录每次请求的 headers。"""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.request_headers: list[dict[str, str]] = []

    def get(self, url: str, headers: dict[str, str] | None = None, **kwargs):  # noqa: ARG002
        self.request_headers.append(dict(headers or {}))
        return self._responses.pop(0)


class TestFormatSize(unittest.TestCase):
    def test_formats_common_units(self) -> None:
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(-5), "0 B")
        self.assertEqual(format_size(512), "512.00 B")
        self.assertEqual(format_size(1024), "1.00 KB")
        self.assertEqual(format_size(1024**2), "1.00 MB")
        self.assertEqual(format_size(1024**3 * 3), "3.00 GB")


class TestCheckDiskSpace(unittest.TestCase):
    def test_reports_free_space_for_temp_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok, free_gb = check_disk_space(Path(tmp), min_gb=0.0)
        self.assertTrue(ok)
        self.assertGreater(free_gb, 0.0)

    def test_insufficient_space_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok, free_gb = check_disk_space(Path(tmp), min_gb=1e9)
        self.assertFalse(ok)
        self.assertGreater(free_gb, 0.0)


class TestDownloadResumable(unittest.TestCase):
    def test_fresh_download_200(self) -> None:
        body = [b"hello ", b"world"]
        resp = _FakeResponse(200, body, {"Content-Length": "11"})
        session = _FakeSession([resp])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.bin"
            ok, downloaded = download_resumable(session, "http://x/a", path)
            self.assertTrue(ok)
            self.assertEqual(downloaded, 11)
            self.assertEqual(path.read_bytes(), b"hello world")
        self.assertTrue(resp.closed)
        # 全新下载不应携带 Range 头
        self.assertNotIn("Range", session.request_headers[0])

    def test_resume_download_206_appends(self) -> None:
        resp = _FakeResponse(206, [b"world"], {"Content-Length": "5"})
        session = _FakeSession([resp])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.bin"
            path.write_bytes(b"hello ")
            ok, downloaded = download_resumable(session, "http://x/a", path)
            self.assertTrue(ok)
            self.assertEqual(downloaded, 5)
            self.assertEqual(path.read_bytes(), b"hello world")
        self.assertEqual(
            session.request_headers[0].get("Range"), "bytes=6-"
        )

    def test_416_means_already_complete(self) -> None:
        resp = _FakeResponse(416, [], {})
        session = _FakeSession([resp])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.bin"
            path.write_bytes(b"done")
            ok, downloaded = download_resumable(session, "http://x/a", path)
            self.assertTrue(ok)
            self.assertEqual(downloaded, 0)
            self.assertEqual(path.read_bytes(), b"done")

    def test_error_status_raises(self) -> None:
        resp = _FakeResponse(403, [], {})
        session = _FakeSession([resp])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                download_resumable(session, "http://x/a", Path(tmp) / "a.bin")
        self.assertTrue(resp.closed)


class TestDownloadWithRetry(unittest.TestCase):
    def test_retries_then_succeeds(self) -> None:
        fail = _FakeResponse(500, [], {})
        ok_resp = _FakeResponse(200, [b"data"], {"Content-Length": "4"})
        session = _FakeSession([fail, ok_resp])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.bin"
            result = download_with_retry(
                session, "http://x/a", path, max_retries=3, initial_backoff=0.0
            )
            self.assertTrue(result)
            self.assertEqual(path.read_bytes(), b"data")

    def test_exhausts_retries_returns_false(self) -> None:
        responses = [_FakeResponse(500, [], {}) for _ in range(3)]
        session = _FakeSession(responses)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.bin"
            result = download_with_retry(
                session, "http://x/a", path, max_retries=3, initial_backoff=0.0
            )
            self.assertFalse(result)

    def test_empty_file_triggers_retry(self) -> None:
        empty = _FakeResponse(200, [], {"Content-Length": "0"})
        good = _FakeResponse(200, [b"x"], {"Content-Length": "1"})
        session = _FakeSession([empty, good])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.bin"
            result = download_with_retry(
                session, "http://x/a", path, max_retries=2, initial_backoff=0.0
            )
            self.assertTrue(result)
            self.assertEqual(path.read_bytes(), b"x")


if __name__ == "__main__":
    unittest.main()
