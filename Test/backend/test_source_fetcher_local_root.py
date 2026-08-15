"""LocalFileSourceFetcher 根约束测试（Wave 1 / G1-04）。

验证 ``BACKEND_DOWNLOAD_SOURCE_ROOT`` 对 file:// / local:// 源的约束：
1. 配置根后：绝对路径必须落在根内（防任意读/LFI），目录穿越归一后同样被拒
2. 配置根后：local:// 相对路径以根为基础解析（实现配置注释声明的语义）
3. 未配置根：production fail-closed 拒绝本地文件源；其余环境放行并保持联调可用
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


@contextmanager
def _settings_override(**overrides):
    """settings 为冻结 dataclass，须用 object.__setattr__ 覆写并恢复。"""
    from app.core.config import settings

    saved = {k: getattr(settings, k) for k in overrides}
    for key, value in overrides.items():
        object.__setattr__(settings, key, value)
    try:
        yield
    finally:
        for key, value in saved.items():
            object.__setattr__(settings, key, value)


def _fetcher():
    from app.services.source_fetcher import LocalFileSourceFetcher

    return LocalFileSourceFetcher()


def _stub_object_store():
    store = MagicMock()
    store.put_stream.return_value = SimpleNamespace(content_length=4, file_path=None)
    return store


def test_file_uri_inside_root_succeeds(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    payload = data_dir / "wind.json"
    payload.write_text("{}{}", encoding="utf-8")

    svc = _fetcher()
    with (
        _settings_override(download_source_root=str(tmp_path)),
        patch("app.services.source_fetcher.object_store", _stub_object_store()),
    ):
        result = svc.fetch(
            ref_id="r1",
            source_uri=payload.as_uri(),
            artifact_key_prefix="artifacts/test",
        )
    assert result.success is True
    assert result.fetched_bytes == 4


def test_file_uri_outside_root_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.env"
    secret.write_text("LEAK", encoding="utf-8")

    root = tmp_path / "root"
    root.mkdir()

    svc = _fetcher()
    with (
        _settings_override(download_source_root=str(root)),
        patch("app.services.source_fetcher.object_store", _stub_object_store()),
    ):
        result = svc.fetch(
            ref_id="r2",
            source_uri=secret.as_uri(),
            artifact_key_prefix="artifacts/test",
        )
    assert result.success is False
    assert "outside" in (result.error or "")
    assert "secret" not in (result.error or "")


def test_file_uri_traversal_resolved_and_rejected(tmp_path: Path) -> None:
    """file://root/data/../../x 归一后落在根外：必须拒绝。"""
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    target = tmp_path / "creds.txt"
    target.write_text("LEAK", encoding="utf-8")

    uri = (root / "data" / ".." / ".." / "creds.txt").as_uri()
    svc = _fetcher()
    with (
        _settings_override(download_source_root=str(root)),
        patch("app.services.source_fetcher.object_store", _stub_object_store()),
    ):
        result = svc.fetch(
            ref_id="r3",
            source_uri=uri,
            artifact_key_prefix="artifacts/test",
        )
    assert result.success is False
    assert "outside" in (result.error or "")


def test_local_uri_relative_resolves_under_root(tmp_path: Path) -> None:
    """local://相对路径 以根为基础（配置注释声明的语义）。"""
    root = tmp_path / "src_root"
    (root / "tiles").mkdir(parents=True)
    payload = root / "tiles" / "t.bin"
    payload.write_bytes(b"ABCD")

    svc = _fetcher()
    with (
        _settings_override(download_source_root=str(root)),
        patch("app.services.source_fetcher.object_store", _stub_object_store()),
    ):
        result = svc.fetch(
            ref_id="r4",
            source_uri="local://tiles/t.bin",
            artifact_key_prefix="artifacts/test",
        )
    assert result.success is True


def test_missing_root_production_fails_closed(tmp_path: Path) -> None:
    payload = tmp_path / "any.json"
    payload.write_text("{}", encoding="utf-8")

    svc = _fetcher()
    with (
        _settings_override(download_source_root="", environment="production"),
        patch("app.services.source_fetcher.object_store", _stub_object_store()),
    ):
        result = svc.fetch(
            ref_id="r5",
            source_uri=payload.as_uri(),
            artifact_key_prefix="artifacts/test",
        )
    assert result.success is False
    assert "DOWNLOAD_SOURCE_ROOT" in (result.error or "")


def test_missing_root_development_remains_usable(tmp_path: Path) -> None:
    payload = tmp_path / "any.json"
    payload.write_text("{}", encoding="utf-8")

    svc = _fetcher()
    with (
        _settings_override(download_source_root="", environment="development"),
        patch("app.services.source_fetcher.object_store", _stub_object_store()),
    ):
        result = svc.fetch(
            ref_id="r6",
            source_uri=payload.as_uri(),
            artifact_key_prefix="artifacts/test",
        )
    assert result.success is True


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    """根内符号链接指向根外文件：resolve() 归一后必须拒绝。"""
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.bin"
    secret.write_bytes(b"LEAK")
    link = root / "link.bin"
    link.symlink_to(secret)

    svc = _fetcher()
    with (
        _settings_override(download_source_root=str(root)),
        patch("app.services.source_fetcher.object_store", _stub_object_store()),
    ):
        result = svc.fetch(
            ref_id="r7",
            source_uri=link.as_uri(),
            artifact_key_prefix="artifacts/test",
        )
    assert result.success is False
    assert "outside" in (result.error or "")
