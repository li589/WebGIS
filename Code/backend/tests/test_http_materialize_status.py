"""Ensure HTTP/MinIO materialize never returns deferred-as-ready without a local file."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PYTHON_PROVIDER = (
    Path(__file__).resolve().parents[2] / "algorithms" / "providers" / "Python"
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
