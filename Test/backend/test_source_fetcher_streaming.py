"""Tests for streaming file copy changes (R1) in source_fetcher.py.

Covers all 4 real fetchers (Http, Minio, LocalFile, RemoteProtocol),
the SourceFetcherRegistry, and the LocalObjectStore.put_stream method.
All external dependencies (safe_urlopen, Minio client, httpx) are mocked
— no real network calls are made.
"""

from __future__ import annotations

from contextlib import nullcontext
import json
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.source_fetcher import (
    FetchResult,
    HttpSourceFetcher,
    LocalFileSourceFetcher,
    MinioSourceFetcher,
    RemoteProtocolSourceFetcher,
    SourceFetcher,
    SourceFetcherRegistry,
)
from app.services.object_store import LocalObjectStore, StoredObject


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeHTTPResponse:
    """Fake HTTP response that mimics urllib's response object.

    Supports ``read()`` for streaming, ``headers`` dict for metadata,
    ``status``/``getcode()`` for status codes, and context-manager protocol
    for ``with safe_urlopen(...) as response:``.
    """

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

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        pass

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _make_stored_object(
    content_length: int = 42, file_path: str = "artifacts/test"
) -> SimpleNamespace:
    """Create a lightweight stand-in for ``StoredObject`` returned by ``put_stream``."""
    return SimpleNamespace(
        content_length=content_length,
        file_path=Path(file_path),
    )


class _StubFetcher(SourceFetcher):
    """Minimal fetcher stub for registry tests — returns a pre-set FetchResult."""

    def __init__(self, scheme: str, result: FetchResult) -> None:
        self._scheme = scheme
        self._result = result

    def supports(self, source_uri: str) -> bool:
        return source_uri.startswith(self._scheme + "://")

    def fetch(
        self, *, ref_id: str, source_uri: str, artifact_key_prefix: str
    ) -> FetchResult:
        return self._result


# ---------------------------------------------------------------------------
# HTTP Source Fetcher tests
# ---------------------------------------------------------------------------


class _PutStreamCapture:
    """Capture put_stream args at call time (stream is closed after the call)."""

    def __init__(self, content_length: int, file_path: str = "artifacts/test") -> None:
        self.content_length = content_length
        self.file_path = file_path
        self.data = b""
        self.kwargs: dict[str, object] = {}

    def __call__(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = dict(kwargs)
        self.data = kwargs["stream"].read()
        return _make_stored_object(
            content_length=self.content_length, file_path=self.file_path
        )


def test_http_fetcher_streams_to_object_store() -> None:
    """Mock safe_urlopen → put_stream called with staging file; FetchResult.success."""
    body = b'{"key": "value"}'
    fake_response = _FakeHTTPResponse(
        body=body,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
    )
    fetcher = HttpSourceFetcher()

    with tempfile.TemporaryDirectory() as staging:
        capture = _PutStreamCapture(content_length=len(body))
        with (
            patch("app.core.ssrf.safe_urlopen", return_value=fake_response),
            patch(
                "app.services.source_fetcher._http_staging_dir",
                return_value=Path(staging),
            ),
            patch("app.services.source_fetcher.object_store") as mock_store,
        ):
            mock_store.put_stream.side_effect = capture

            result = fetcher.fetch(
                ref_id="ref-1",
                source_uri="http://example.com/data.json",
                artifact_key_prefix="artifacts/test",
            )

    # Verify put_stream was called with correct arguments
    mock_store.put_stream.assert_called_once()
    assert (
        capture.kwargs["object_key"] == "artifacts/test/ref-1"
    ), 'capture.kwargs["object_key"] == "artifacts/test/ref-1"'
    # 断点续传改造后：完整字节先落暂存文件，再以文件流入库
    assert capture.data == body, "capture.data == body"
    assert (
        capture.kwargs["content_type"] == "application/json"
    ), 'capture.kwargs["content_type"] == "application/json"'
    assert capture.kwargs["length"] == len(
        body
    ), 'capture.kwargs["length"] == len(body)'

    # Verify FetchResult
    assert result.success, "result.success is truthy"
    assert result.ref_id == "ref-1", 'result.ref_id == "ref-1"'
    assert (
        result.artifact_key == "artifacts/test/ref-1"
    ), 'result.artifact_key == "artifacts/test/ref-1"'
    assert result.fetched_bytes == len(body), "result.fetched_bytes == len(body)"
    assert (
        result.content_type == "application/json"
    ), 'result.content_type == "application/json"'
    assert result.fetched_at, "result.fetched_at is truthy"


def test_http_fetcher_missing_content_length() -> None:
    """No Content-Length header → length=None passed to put_stream."""
    body = b"some data without length"
    fake_response = _FakeHTTPResponse(
        body=body,
        headers={"Content-Type": "application/octet-stream"},
    )
    fetcher = HttpSourceFetcher()

    with tempfile.TemporaryDirectory() as staging:
        capture = _PutStreamCapture(content_length=len(body))
        with (
            patch("app.core.ssrf.safe_urlopen", return_value=fake_response),
            patch(
                "app.services.source_fetcher._http_staging_dir",
                return_value=Path(staging),
            ),
            patch("app.services.source_fetcher.object_store") as mock_store,
        ):
            mock_store.put_stream.side_effect = capture

            result = fetcher.fetch(
                ref_id="ref-2",
                source_uri="http://example.com/blob",
                artifact_key_prefix="artifacts/test",
            )

    # 断点续传改造后：暂存落盘即知确切大小，length 传实际字节数（避免 MinIO multipart）
    assert capture.kwargs["length"] == len(
        body
    ), 'capture.kwargs["length"] == len(body)'
    assert result.success, "result.success is truthy"
    assert result.fetched_bytes == len(body), "result.fetched_bytes == len(body)"


def test_http_fetcher_invalid_content_length() -> None:
    """Content-Length='abc' → 暂存实测大小作为 length（头不可信但不影响入库）。"""
    body = b"data with bad length"
    fake_response = _FakeHTTPResponse(
        body=body,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Length": "abc",
        },
    )
    fetcher = HttpSourceFetcher()

    with tempfile.TemporaryDirectory() as staging:
        capture = _PutStreamCapture(content_length=len(body))
        with (
            patch("app.core.ssrf.safe_urlopen", return_value=fake_response),
            patch(
                "app.services.source_fetcher._http_staging_dir",
                return_value=Path(staging),
            ),
            patch("app.services.source_fetcher.object_store") as mock_store,
        ):
            mock_store.put_stream.side_effect = capture

            result = fetcher.fetch(
                ref_id="ref-3",
                source_uri="http://example.com/blob",
                artifact_key_prefix="artifacts/test",
            )

    assert capture.kwargs["length"] == len(
        body
    ), 'capture.kwargs["length"] == len(body)'
    assert result.success, "result.success is truthy"


def test_http_fetcher_ssrf_exception_returns_failure() -> None:
    """safe_urlopen raises Exception → FetchResult.success=False, error contains 'HTTP fetch failed'."""
    fetcher = HttpSourceFetcher()

    with (
        patch(
            "app.core.ssrf.safe_urlopen",
            side_effect=Exception("SSRF blocked"),
        ),
        patch("app.services.source_fetcher.object_store") as mock_store,
    ):
        result = fetcher.fetch(
            ref_id="ref-4",
            source_uri="http://example.com/blocked",
            artifact_key_prefix="artifacts/test",
        )

    mock_store.put_stream.assert_not_called()
    assert not result.success, "result.success is falsy"
    assert (
        "HTTP fetch failed" in result.error or ""
    ), '"HTTP fetch failed" in result.error or ""'
    assert "SSRF blocked" in result.error or "", '"SSRF blocked" in result.error or ""'


# ---------------------------------------------------------------------------
# Local File Source Fetcher tests
# ---------------------------------------------------------------------------


def test_local_file_fetcher_streams_file() -> None:
    """Create a temp file with known content → FetchResult.success, correct bytes and content_type."""
    content = b'{"data": 123}'
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "data.json"
        file_path.write_bytes(content)

        fetcher = LocalFileSourceFetcher()

        with patch("app.services.source_fetcher.object_store") as mock_store:
            mock_store.put_stream.return_value = _make_stored_object(
                content_length=len(content),
                file_path=str(file_path),
            )

            result = fetcher.fetch(
                ref_id="ref-local-1",
                source_uri=f"file:///{file_path.as_posix()}",
                artifact_key_prefix="artifacts/test",
            )

    mock_store.put_stream.assert_called_once()
    call_kwargs = mock_store.put_stream.call_args.kwargs
    assert (
        call_kwargs["object_key"] == "artifacts/test/ref-local-1"
    ), 'call_kwargs["object_key"] == "artifacts/test/ref-local-1"'
    assert (
        call_kwargs["content_type"] == "application/json"
    ), 'call_kwargs["content_type"] == "application/json"'
    assert call_kwargs["length"] == len(
        content
    ), 'call_kwargs["length"] == len(content)'

    assert result.success, "result.success is truthy"
    assert result.fetched_bytes == len(content), "result.fetched_bytes == len(content)"
    assert (
        result.content_type == "application/json"
    ), 'result.content_type == "application/json"'


def test_local_file_fetcher_not_found() -> None:
    """Non-existent file path → FetchResult.success=False, error contains 'Local file not found'."""
    fetcher = LocalFileSourceFetcher()

    with patch("app.services.source_fetcher.object_store"):
        result = fetcher.fetch(
            ref_id="ref-local-2",
            source_uri="file:///nonexistent/path/to/file.json",
            artifact_key_prefix="artifacts/test",
        )

    assert not result.success, "result.success is falsy"
    assert (
        "Local file not found" in result.error or ""
    ), '"Local file not found" in result.error or ""'


def test_local_file_fetcher_content_type_detection() -> None:
    """Test various extensions → correct content_type mapping."""
    test_cases = [
        (".json", "application/json"),
        (".geojson", "application/json"),
        (".png", "image/png"),
        (".jpg", "image/jpg"),
        (".tif", "image/tif"),
        (".tiff", "image/tiff"),
        (".bin", "application/octet-stream"),
    ]

    for suffix, expected_ct in test_cases:
        with nullcontext():
            content = b"test content"
            with tempfile.TemporaryDirectory() as tmpdir:
                file_path = Path(tmpdir) / f"file{suffix}"
                file_path.write_bytes(content)

                fetcher = LocalFileSourceFetcher()

                with patch("app.services.source_fetcher.object_store") as mock_store:
                    mock_store.put_stream.return_value = _make_stored_object(
                        content_length=len(content)
                    )

                    result = fetcher.fetch(
                        ref_id=f"ref-{suffix}",
                        source_uri=f"file:///{file_path.as_posix()}",
                        artifact_key_prefix="artifacts/test",
                    )

                assert result.success, f"Failed for {suffix}"
                assert (
                    result.content_type == expected_ct
                ), f"Wrong content_type for {suffix}"


# ---------------------------------------------------------------------------
# Minio Source Fetcher tests
# ---------------------------------------------------------------------------


def test_minio_fetcher_streams_object() -> None:
    """Mock Minio client → put_stream is used (not put_bytes); response is streamed."""
    mock_minio_module = MagicMock()
    mock_client = MagicMock()
    mock_minio_module.Minio.return_value = mock_client

    fake_response = MagicMock()
    fake_response.headers = {
        "Content-Type": "application/json",
        "Content-Length": "256",
    }
    mock_client.get_object.return_value = fake_response

    fetcher = MinioSourceFetcher()

    with (
        patch.dict(sys.modules, {"minio": mock_minio_module}),
        patch("app.services.source_fetcher.object_store") as mock_store,
    ):
        mock_store.put_stream.return_value = _make_stored_object(
            content_length=256, file_path="artifacts/test/ref-minio"
        )

        result = fetcher.fetch(
            ref_id="ref-minio",
            source_uri="minio://test-bucket/path/to/object.json",
            artifact_key_prefix="artifacts/test",
        )

    # Verify Minio client was created and get_object was called
    mock_minio_module.Minio.assert_called_once()
    mock_client.get_object.assert_called_once_with("test-bucket", "path/to/object.json")

    # Verify put_stream was used (not put_bytes)
    mock_store.put_stream.assert_called_once()
    mock_store.put_bytes.assert_not_called()

    call_kwargs = mock_store.put_stream.call_args.kwargs
    assert (
        call_kwargs["object_key"] == "artifacts/test/ref-minio"
    ), 'call_kwargs["object_key"] == "artifacts/test/ref-minio"'
    assert (
        call_kwargs["stream"] == fake_response
    ), 'call_kwargs["stream"] == fake_response'
    assert (
        call_kwargs["content_type"] == "application/json"
    ), 'call_kwargs["content_type"] == "application/json"'
    assert call_kwargs["length"] == 256, 'call_kwargs["length"] == 256'

    # Verify response cleanup
    fake_response.close.assert_called_once()
    fake_response.release_conn.assert_called_once()

    # Verify FetchResult
    assert result.success, "result.success is truthy"
    assert result.fetched_bytes == 256, "result.fetched_bytes == 256"
    assert (
        result.content_type == "application/json"
    ), 'result.content_type == "application/json"'


# ---------------------------------------------------------------------------
# Remote Protocol Source Fetcher tests
# ---------------------------------------------------------------------------


def test_remote_protocol_fetcher_streams_after_download() -> None:
    """Mock download_remote_uri → file is streamed (not read_bytes); put_stream used."""
    content = b"remote file content for streaming test"
    with tempfile.TemporaryDirectory() as tmpdir:
        downloaded_file = Path(tmpdir) / "downloaded.bin"
        downloaded_file.write_bytes(content)

        fetcher = RemoteProtocolSourceFetcher()

        with (
            patch(
                "shared.remote_sources.download.download_remote_uri",
                return_value=(downloaded_file, SimpleNamespace(st_size=len(content))),
            ) as mock_download,
            patch(
                "shared.remote_sources.limits.get_max_remote_bytes",
                return_value=512 * 1024 * 1024,
            ),
            patch("app.services.remote_auth_resolver.resolve_remote_auth") as mock_auth,
            patch("app.services.source_fetcher.object_store") as mock_store,
        ):
            mock_auth.return_value = None
            mock_store.put_stream.return_value = _make_stored_object(
                content_length=len(content),
                file_path=str(downloaded_file),
            )

            result = fetcher.fetch(
                ref_id="ref-sftp-1",
                source_uri="sftp://example.com/data/file.bin",
                artifact_key_prefix="artifacts/test",
            )

    # Verify download_remote_uri was called
    mock_download.assert_called_once()

    # Verify put_stream was used (not read_bytes or put_bytes)
    mock_store.put_stream.assert_called_once()
    mock_store.put_bytes.assert_not_called()

    call_kwargs = mock_store.put_stream.call_args.kwargs
    assert (
        call_kwargs["object_key"] == "artifacts/test/ref-sftp-1"
    ), 'call_kwargs["object_key"] == "artifacts/test/ref-sftp-1"'
    assert (
        call_kwargs["content_type"] == "application/octet-stream"
    ), 'call_kwargs["content_type"] == "application/octet-stream"'
    assert call_kwargs["length"] == len(
        content
    ), 'call_kwargs["length"] == len(content)'

    # Verify FetchResult
    assert result.success, "result.success is truthy"
    assert result.fetched_bytes == len(content), "result.fetched_bytes == len(content)"
    assert (
        result.content_type == "application/octet-stream"
    ), 'result.content_type == "application/octet-stream"'


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


def test_registry_fetch_many_partial_failure() -> None:
    """3 source_refs: unsupported scheme (stub fail), empty uri (built-in fail), valid (stub success).
    Verify results list has 3 entries with correct success/failure."""
    registry = SourceFetcherRegistry()

    # Register stub fetchers for custom schemes
    fail_fetcher = _StubFetcher(
        "foo",
        FetchResult(
            ref_id="ref-unsupported",
            success=False,
            error="Unsupported source_uri scheme: foo://bar",
            fetched_at="2024-01-01T00:00:00+00:00",
        ),
    )
    success_fetcher = _StubFetcher(
        "http",
        FetchResult(
            ref_id="ref-valid",
            success=True,
            artifact_key="test-prefix/ref-valid",
            fetched_bytes=100,
            content_type="application/json",
            fetched_at="2024-01-01T00:00:00+00:00",
        ),
    )
    # Register success first, then fail — register inserts at front,
    # so fail_fetcher ends up before success_fetcher in the chain.
    # But _StubFetcher.supports uses exact scheme prefix, so order
    # between them doesn't matter (they handle different schemes).
    registry.register(success_fetcher)
    registry.register(fail_fetcher)

    source_refs = [
        {"ref_id": "ref-unsupported", "source_uri": "foo://bar"},
        {"ref_id": "ref-empty", "source_uri": ""},
        {"ref_id": "ref-valid", "source_uri": "http://example.com/data.json"},
    ]

    results = registry.fetch_many(
        source_refs=source_refs,
        artifact_key_prefix="test-prefix",
    )

    assert len(results) == 3, "len(results) == 3"

    # Unsupported scheme → failure
    assert not results[0].success, "results[0].success is falsy"
    assert (
        results[0].ref_id == "ref-unsupported"
    ), 'results[0].ref_id == "ref-unsupported"'

    # Empty URI → built-in failure
    assert not results[1].success, "results[1].success is falsy"
    assert results[1].ref_id == "ref-empty", 'results[1].ref_id == "ref-empty"'
    assert (
        "source_uri is empty" in results[1].error or ""
    ), '"source_uri is empty" in results[1].error or ""'

    # Valid → success
    assert results[2].success, "results[2].success is truthy"
    assert results[2].ref_id == "ref-valid", 'results[2].ref_id == "ref-valid"'
    assert results[2].fetched_bytes == 100, "results[2].fetched_bytes == 100"


# ---------------------------------------------------------------------------
# LocalObjectStore.put_stream tests
# ---------------------------------------------------------------------------


def test_object_store_put_stream_local() -> None:
    """Create LocalObjectStore with temp dir, put_stream with BytesIO → file + metadata created."""
    content = b"hello world " * 100  # ~1200 bytes
    with tempfile.TemporaryDirectory() as tmpdir:
        store = LocalObjectStore(tmpdir)
        stream = BytesIO(content)

        stored = store.put_stream(
            object_key="test/object.bin",
            stream=stream,
            content_type="application/octet-stream",
            length=len(content),
            metadata={"source": "test", "ref_id": "ref-1"},
        )

        # Verify StoredObject
        assert isinstance(stored, StoredObject), "isinstance(stored, StoredObject)"
        assert (
            stored.object_key == "test/object.bin"
        ), 'stored.object_key == "test/object.bin"'
        assert stored.content_length == len(
            content
        ), "stored.content_length == len(content)"
        assert (
            stored.content_type == "application/octet-stream"
        ), 'stored.content_type == "application/octet-stream"'
        assert (
            stored.metadata["source"] == "test"
        ), 'stored.metadata["source"] == "test"'

        # Verify file is created with correct content
        file_path = Path(tmpdir) / "test" / "object.bin"
        assert file_path.exists(), "file_path.exists() is truthy"
        assert file_path.read_bytes() == content, "file_path.read_bytes() == content"

        # Verify metadata file exists and has correct structure
        meta_path = Path(tmpdir) / "test" / "object.bin.meta.json"
        assert meta_path.exists(), "meta_path.exists() is truthy"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert (
            meta["object_key"] == "test/object.bin"
        ), 'meta["object_key"] == "test/object.bin"'
        assert (
            meta["content_type"] == "application/octet-stream"
        ), 'meta["content_type"] == "application/octet-stream"'
        assert meta["content_length"] == len(
            content
        ), 'meta["content_length"] == len(content)'
        assert (
            meta["metadata"]["source"] == "test"
        ), 'meta["metadata"]["source"] == "test"'


def test_object_store_put_stream_unknown_length() -> None:
    """put_stream with length=None → still works (uses chunked read)."""
    content = b"chunked data " * 200  # ~2600 bytes, spans multiple 1MB chunks boundary?
    # Actually 2600 bytes < 1MB, but the point is length=None works.
    with tempfile.TemporaryDirectory() as tmpdir:
        store = LocalObjectStore(tmpdir)
        stream = BytesIO(content)

        stored = store.put_stream(
            object_key="test/unknown_len.bin",
            stream=stream,
            content_type="application/octet-stream",
            length=None,
            metadata={"source": "test"},
        )

        # Verify content_length is computed from actual bytes written
        assert stored.content_length == len(
            content
        ), "stored.content_length == len(content)"

        # Verify file content matches
        file_path = Path(tmpdir) / "test" / "unknown_len.bin"
        assert file_path.exists(), "file_path.exists() is truthy"
        assert file_path.read_bytes() == content, "file_path.read_bytes() == content"

        # Verify metadata file reflects correct length
        meta_path = Path(tmpdir) / "test" / "unknown_len.bin.meta.json"
        assert meta_path.exists(), "meta_path.exists() is truthy"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["content_length"] == len(
            content
        ), 'meta["content_length"] == len(content)'

        # Verify round-trip via get_object
        retrieved = store.get_object("test/unknown_len.bin")
        assert retrieved is not None, "retrieved is not None"
        assert retrieved.content_length == len(
            content
        ), "retrieved.content_length == len(content)"
