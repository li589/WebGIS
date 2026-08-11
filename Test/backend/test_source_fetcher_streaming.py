"""Tests for streaming file copy changes (R1) in source_fetcher.py.

Covers all 4 real fetchers (Http, Minio, LocalFile, RemoteProtocol),
the SourceFetcherRegistry, and the LocalObjectStore.put_stream method.
All external dependencies (safe_urlopen, Minio client, httpx) are mocked
— no real network calls are made.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
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
    and context-manager protocol for ``with safe_urlopen(...) as response:``.
    """

    def __init__(self, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self._body = body
        self._pos = 0
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        if self._pos >= len(self._body):
            return b""
        if size is None or size < 0:
            data = self._body[self._pos:]
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


def _make_stored_object(content_length: int = 42, file_path: str = "artifacts/test") -> SimpleNamespace:
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

    def fetch(self, *, ref_id: str, source_uri: str, artifact_key_prefix: str) -> FetchResult:
        return self._result


# ---------------------------------------------------------------------------
# HTTP Source Fetcher tests
# ---------------------------------------------------------------------------

class HttpSourceFetcherStreamingTests(unittest.TestCase):
    """Verify HttpSourceFetcher streams response body to object_store."""

    def test_http_fetcher_streams_to_object_store(self) -> None:
        """Mock safe_urlopen → put_stream called with correct args; FetchResult.success."""
        body = b'{"key": "value"}'
        fake_response = _FakeHTTPResponse(
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        fetcher = HttpSourceFetcher()

        with (
            patch("app.core.ssrf.safe_urlopen", return_value=fake_response),
            patch("app.services.source_fetcher.object_store") as mock_store,
        ):
            mock_store.put_stream.return_value = _make_stored_object(
                content_length=len(body), file_path="artifacts/test/ref-1"
            )

            result = fetcher.fetch(
                ref_id="ref-1",
                source_uri="http://example.com/data.json",
                artifact_key_prefix="artifacts/test",
            )

        # Verify put_stream was called with correct arguments
        mock_store.put_stream.assert_called_once()
        call_kwargs = mock_store.put_stream.call_args.kwargs
        self.assertEqual(call_kwargs["object_key"], "artifacts/test/ref-1")
        self.assertEqual(call_kwargs["stream"], fake_response)
        self.assertEqual(call_kwargs["content_type"], "application/json")
        self.assertEqual(call_kwargs["length"], len(body))

        # Verify FetchResult
        self.assertTrue(result.success)
        self.assertEqual(result.ref_id, "ref-1")
        self.assertEqual(result.artifact_key, "artifacts/test/ref-1")
        self.assertEqual(result.fetched_bytes, len(body))
        self.assertEqual(result.content_type, "application/json")
        self.assertTrue(result.fetched_at)

    def test_http_fetcher_missing_content_length(self) -> None:
        """No Content-Length header → length=None passed to put_stream."""
        body = b"some data without length"
        fake_response = _FakeHTTPResponse(
            body=body,
            headers={"Content-Type": "application/octet-stream"},
        )
        fetcher = HttpSourceFetcher()

        with (
            patch("app.core.ssrf.safe_urlopen", return_value=fake_response),
            patch("app.services.source_fetcher.object_store") as mock_store,
        ):
            mock_store.put_stream.return_value = _make_stored_object(
                content_length=len(body)
            )

            result = fetcher.fetch(
                ref_id="ref-2",
                source_uri="http://example.com/blob",
                artifact_key_prefix="artifacts/test",
            )

        call_kwargs = mock_store.put_stream.call_args.kwargs
        self.assertIsNone(call_kwargs["length"])
        self.assertTrue(result.success)
        self.assertEqual(result.fetched_bytes, len(body))

    def test_http_fetcher_invalid_content_length(self) -> None:
        """Content-Length='abc' → length=None (not int)."""
        body = b"data with bad length"
        fake_response = _FakeHTTPResponse(
            body=body,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": "abc",
            },
        )
        fetcher = HttpSourceFetcher()

        with (
            patch("app.core.ssrf.safe_urlopen", return_value=fake_response),
            patch("app.services.source_fetcher.object_store") as mock_store,
        ):
            mock_store.put_stream.return_value = _make_stored_object(
                content_length=len(body)
            )

            result = fetcher.fetch(
                ref_id="ref-3",
                source_uri="http://example.com/blob",
                artifact_key_prefix="artifacts/test",
            )

        call_kwargs = mock_store.put_stream.call_args.kwargs
        self.assertIsNone(call_kwargs["length"])
        self.assertTrue(result.success)

    def test_http_fetcher_ssrf_exception_returns_failure(self) -> None:
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
        self.assertFalse(result.success)
        self.assertIn("HTTP fetch failed", result.error or "")
        self.assertIn("SSRF blocked", result.error or "")


# ---------------------------------------------------------------------------
# Local File Source Fetcher tests
# ---------------------------------------------------------------------------

class LocalFileSourceFetcherStreamingTests(unittest.TestCase):
    """Verify LocalFileSourceFetcher streams files to object_store."""

    def test_local_file_fetcher_streams_file(self) -> None:
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
        self.assertEqual(call_kwargs["object_key"], "artifacts/test/ref-local-1")
        self.assertEqual(call_kwargs["content_type"], "application/json")
        self.assertEqual(call_kwargs["length"], len(content))

        self.assertTrue(result.success)
        self.assertEqual(result.fetched_bytes, len(content))
        self.assertEqual(result.content_type, "application/json")

    def test_local_file_fetcher_not_found(self) -> None:
        """Non-existent file path → FetchResult.success=False, error contains 'Local file not found'."""
        fetcher = LocalFileSourceFetcher()

        with patch("app.services.source_fetcher.object_store"):
            result = fetcher.fetch(
                ref_id="ref-local-2",
                source_uri="file:///nonexistent/path/to/file.json",
                artifact_key_prefix="artifacts/test",
            )

        self.assertFalse(result.success)
        self.assertIn("Local file not found", result.error or "")

    def test_local_file_fetcher_content_type_detection(self) -> None:
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
            with self.subTest(suffix=suffix):
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

                    self.assertTrue(result.success, f"Failed for {suffix}")
                    self.assertEqual(
                        result.content_type,
                        expected_ct,
                        f"Wrong content_type for {suffix}",
                    )


# ---------------------------------------------------------------------------
# Minio Source Fetcher tests
# ---------------------------------------------------------------------------

class MinioSourceFetcherStreamingTests(unittest.TestCase):
    """Verify MinioSourceFetcher streams objects to object_store."""

    def test_minio_fetcher_streams_object(self) -> None:
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
        self.assertEqual(call_kwargs["object_key"], "artifacts/test/ref-minio")
        self.assertEqual(call_kwargs["stream"], fake_response)
        self.assertEqual(call_kwargs["content_type"], "application/json")
        self.assertEqual(call_kwargs["length"], 256)

        # Verify response cleanup
        fake_response.close.assert_called_once()
        fake_response.release_conn.assert_called_once()

        # Verify FetchResult
        self.assertTrue(result.success)
        self.assertEqual(result.fetched_bytes, 256)
        self.assertEqual(result.content_type, "application/json")


# ---------------------------------------------------------------------------
# Remote Protocol Source Fetcher tests
# ---------------------------------------------------------------------------

class RemoteProtocolSourceFetcherStreamingTests(unittest.TestCase):
    """Verify RemoteProtocolSourceFetcher streams downloaded files to object_store."""

    def test_remote_protocol_fetcher_streams_after_download(self) -> None:
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
        self.assertEqual(call_kwargs["object_key"], "artifacts/test/ref-sftp-1")
        self.assertEqual(call_kwargs["content_type"], "application/octet-stream")
        self.assertEqual(call_kwargs["length"], len(content))

        # Verify FetchResult
        self.assertTrue(result.success)
        self.assertEqual(result.fetched_bytes, len(content))
        self.assertEqual(result.content_type, "application/octet-stream")


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class SourceFetcherRegistryTests(unittest.TestCase):
    """Verify SourceFetcherRegistry.fetch_many handles mixed success/failure."""

    def test_registry_fetch_many_partial_failure(self) -> None:
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

        self.assertEqual(len(results), 3)

        # Unsupported scheme → failure
        self.assertFalse(results[0].success)
        self.assertEqual(results[0].ref_id, "ref-unsupported")

        # Empty URI → built-in failure
        self.assertFalse(results[1].success)
        self.assertEqual(results[1].ref_id, "ref-empty")
        self.assertIn("source_uri is empty", results[1].error or "")

        # Valid → success
        self.assertTrue(results[2].success)
        self.assertEqual(results[2].ref_id, "ref-valid")
        self.assertEqual(results[2].fetched_bytes, 100)


# ---------------------------------------------------------------------------
# LocalObjectStore.put_stream tests
# ---------------------------------------------------------------------------

class LocalObjectStorePutStreamTests(unittest.TestCase):
    """Verify LocalObjectStore.put_stream writes files and metadata correctly."""

    def test_object_store_put_stream_local(self) -> None:
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
            self.assertIsInstance(stored, StoredObject)
            self.assertEqual(stored.object_key, "test/object.bin")
            self.assertEqual(stored.content_length, len(content))
            self.assertEqual(stored.content_type, "application/octet-stream")
            self.assertEqual(stored.metadata["source"], "test")

            # Verify file is created with correct content
            file_path = Path(tmpdir) / "test" / "object.bin"
            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.read_bytes(), content)

            # Verify metadata file exists and has correct structure
            meta_path = Path(tmpdir) / "test" / "object.bin.meta.json"
            self.assertTrue(meta_path.exists())
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["object_key"], "test/object.bin")
            self.assertEqual(meta["content_type"], "application/octet-stream")
            self.assertEqual(meta["content_length"], len(content))
            self.assertEqual(meta["metadata"]["source"], "test")

    def test_object_store_put_stream_unknown_length(self) -> None:
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
            self.assertEqual(stored.content_length, len(content))

            # Verify file content matches
            file_path = Path(tmpdir) / "test" / "unknown_len.bin"
            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.read_bytes(), content)

            # Verify metadata file reflects correct length
            meta_path = Path(tmpdir) / "test" / "unknown_len.bin.meta.json"
            self.assertTrue(meta_path.exists())
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["content_length"], len(content))

            # Verify round-trip via get_object
            retrieved = store.get_object("test/unknown_len.bin")
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.content_length, len(content))


if __name__ == "__main__":
    unittest.main()
