"""Ensure HTTP/MinIO materialize never returns deferred-as-ready without a local file."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PYTHON_PROVIDER = (
    Path(__file__).resolve().parents[2] / "Code" / "algorithms" / "providers" / "Python"
)
if str(PYTHON_PROVIDER) not in sys.path:
    sys.path.insert(0, str(PYTHON_PROVIDER))


def test_http_materialize_marks_ready_after_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from data_access.contracts import build_resource_ref
    from data_access.sources import http as http_mod

    source = http_mod.HttpSource()
    resource = build_resource_ref(
        uri="https://example.com/sample.tif",
        source_kind="online",
        storage_backend="https",
    )

    fake_body = b"GEOTIFF-BYTES"

    class _Resp:
        """最小 urlopen 响应：真实响应总有 .headers（HTTPMessage），mock 用 dict 模拟 .get。"""

        def __init__(self) -> None:
            self._buf = fake_body
            self.headers = {
                "ETag": '"v1"',
                "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT",
            }

        def read(self, n: int = -1):
            if n < 0 or n >= len(self._buf):
                chunk, self._buf = self._buf, b""
                return chunk
            chunk, self._buf = self._buf[:n], self._buf[n:]
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(http_mod, "urlopen", lambda *a, **k: _Resp())
    out = source.materialize(resource, target_dir=tmp_path)

    assert out.metadata.get("materialization_status") == "ready"
    local = Path(str(out.metadata["local_path"]))
    assert local.exists()
    assert local.read_bytes() == fake_body
    # 响应头写入 sidecar（ETag / Last-Modified 供后续条件请求复用）
    sidecar = local.with_suffix(local.suffix + ".httpmeta.json")
    assert sidecar.is_file()
    import json

    sidecar_payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert sidecar_payload.get("etag") == '"v1"'
    assert sidecar_payload.get("last_modified") == "Wed, 01 Jan 2025 00:00:00 GMT"


def test_minio_materialize_refuses_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from data_access.contracts import build_resource_ref
    from data_access.sources.minio import MinioSource

    for key in (
        "BACKEND_MINIO_ENDPOINT",
        "MINIO_ENDPOINT",
        "BACKEND_MINIO_ACCESS_KEY",
        "MINIO_ACCESS_KEY",
        "BACKEND_MINIO_SECRET_KEY",
        "MINIO_SECRET_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    source = MinioSource()
    resource = build_resource_ref(
        uri="minio://bucket/path/object.tif",
        source_kind="object_storage",
        storage_backend="minio",
        bucket="bucket",
        object_key="path/object.tif",
    )
    with pytest.raises(ValueError, match="requires"):
        source.materialize(resource, target_dir=tmp_path)


# ── 下载重试 / Range 续传 / 错误分类 ─────────────────────────────────────────


class _ScriptedResp:
    """可脚本化的 urlopen 响应：按调用序返回响应或抛异常。"""

    def __init__(self, chunks: list[bytes | Exception], *, status: int = 200):
        self._chunks = list(chunks)
        self.status = status
        self.headers = {"ETag": '"v1"'}

    def read(self, _n: int = -1):
        if not self._chunks:
            return b""
        item = self._chunks.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _materialize_simple(source, tmp_path, monkeypatch):
    from data_access.contracts import build_resource_ref

    resource = build_resource_ref(
        uri="https://example.com/sample.bin",
        source_kind="online",
        storage_backend="https",
    )
    return source.materialize(resource, target_dir=tmp_path)


def test_http_download_resumes_after_mid_stream_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """中途断连后保留 .part，重试经 Range 续传完成下载。"""
    from data_access.sources import http as http_mod
    from urllib.error import URLError

    requests_seen: list[dict] = []

    def fake_urlopen(req, timeout=None):
        headers = {k.lower(): v for k, v in req.header_items()}
        requests_seen.append(headers)
        if len(requests_seen) == 1:
            # 首次：写出 4 字节后连接被重置
            return _ScriptedResp([b"1234", URLError("connection reset")])
        # 重试：应携带 Range: bytes=4-，返回 206 与剩余字节
        assert headers.get("range") == "bytes=4-"
        return _ScriptedResp([b"56"], status=206)

    monkeypatch.setattr(http_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_mod.time, "sleep", lambda _s: None)

    out = _materialize_simple(http_mod.HttpSource(), tmp_path, monkeypatch)
    assert out.metadata.get("materialization_status") == "ready"
    local = Path(str(out.metadata["local_path"]))
    assert local.read_bytes() == b"123456"
    assert len(requests_seen) == 2
    # .part 半成品成功后被原子替换，不应残留
    assert not local.with_name(local.name + ".part").exists()


def test_http_download_full_rewrite_when_server_ignores_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.part 存在时请求带 Range；服务器忽略 Range（返回 200）必须整体重写而非追加。"""
    from data_access.sources import http as http_mod
    from urllib.error import URLError

    cache_key = http_mod.build_http_cache_key("https://example.com/sample.bin")
    part = tmp_path / f"{cache_key}.bin.part"
    part.write_bytes(b"1234")  # 上次失败的半成品

    requests_seen: list[dict] = []

    def fake_urlopen(req, timeout=None):
        headers = {k.lower(): v for k, v in req.header_items()}
        requests_seen.append(headers)
        if len(requests_seen) == 1:
            # 预置 .part 使首次尝试即带续传 Range
            assert headers.get("range") == "bytes=4-"
            # 服务器忽略 Range 返回 200 → 整体重写；写 2 字节后断连
            return _ScriptedResp([b"ab", URLError("reset")])
        # .part 现为 2 字节（整体重写后），重试从新偏移续传
        assert headers.get("range") == "bytes=2-"
        return _ScriptedResp([b"cdef"], status=206)

    monkeypatch.setattr(http_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_mod.time, "sleep", lambda _s: None)

    out = _materialize_simple(http_mod.HttpSource(), tmp_path, monkeypatch)
    local = Path(str(out.metadata["local_path"]))
    assert local.read_bytes() == b"abcdef"


def test_http_download_terminal_4xx_fails_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from data_access.sources import http as http_mod
    from urllib.error import HTTPError

    calls: list[int] = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise HTTPError(req.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(http_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_mod.time, "sleep", lambda _s: None)

    with pytest.raises(ValueError, match="404"):
        _materialize_simple(http_mod.HttpSource(), tmp_path, monkeypatch)
    assert len(calls) == 1  # 终态 4xx 不重试


def test_http_download_5xx_retries_then_raises_connection_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from data_access.sources import http as http_mod
    from urllib.error import HTTPError

    calls: list[int] = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise HTTPError(req.full_url, 503, "Service Unavailable", None, None)

    monkeypatch.setattr(http_mod, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_mod.time, "sleep", lambda _s: None)

    with pytest.raises(ConnectionError, match="transient"):
        _materialize_simple(http_mod.HttpSource(), tmp_path, monkeypatch)
    assert len(calls) == http_mod._MAX_DOWNLOAD_ATTEMPTS
