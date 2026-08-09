"""CC-4: local_path_to_uri 跨平台 file:// URI 转换单测。

验证：
1. Windows 盘符路径字符串在任何平台都正确构造 file:///D:/... （核心修复）。
2. 与原 Path.resolve().as_uri() / Path.as_uri() 在当前平台行为一致（无回归）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from path_utils import local_path_to_uri


def test_windows_drive_path_backslash_any_platform():
    """D:\\foo\\bar.tif → file:///D:/foo/bar.tif（Linux 上 resolve 会破坏，此处手动构造）。"""
    assert local_path_to_uri(r"D:\foo\bar.tif") == "file:///D:/foo/bar.tif"


def test_windows_drive_path_forward_slash_any_platform():
    assert local_path_to_uri("D:/foo/bar.tif") == "file:///D:/foo/bar.tif"


def test_windows_drive_preserves_subdirs():
    assert (
        local_path_to_uri(r"E:\data\nested\file.mat")
        == "file:///E:/data/nested/file.mat"
    )


def test_resolve_true_matches_original_resolve_as_uri(tmp_path):
    """resolve=True 与原 path.resolve().as_uri() 在当前平台结果一致（行为保持）。"""
    p = tmp_path / "out.tif"
    p.write_bytes(b"II*\x00")
    assert local_path_to_uri(p, resolve=True) == str(p.resolve().as_uri())


def test_resolve_false_matches_bare_as_uri(tmp_path):
    """resolve=False 与原 path.as_uri() 一致（不强制 resolve，避免 Windows 8.3 风险）。"""
    p = tmp_path / "out.tif"
    p.write_bytes(b"II*\x00")
    assert local_path_to_uri(p, resolve=False) == p.as_uri()


def test_resolve_true_handles_relative(tmp_path, monkeypatch):
    """相对路径 + resolve=True 解析为基于 cwd 的绝对 URI（与原 resolve().as_uri() 一致）。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rel.tif").write_bytes(b"II*\x00")
    assert local_path_to_uri("rel.tif", resolve=True) == str(
        Path("rel.tif").resolve().as_uri()
    )


def test_windows_drive_not_double_slash():
    """盘符路径构造为 file:///D:/...（file:// + /D:/ 三斜杠前缀，路径内斜杠另计）。"""
    uri = local_path_to_uri(r"C:\x.tif")
    assert uri == "file:///C:/x.tif"
    assert uri.startswith("file:///")  # 三斜杠前缀


def test_posix_absolute_on_posix():
    """POSIX 绝对路径在非 Windows 平台走 as_uri 分支。Windows 跳过。"""
    if sys.platform.startswith("win"):
        return  # Windows 上 /abs 不是合法绝对路径，跳过
    assert local_path_to_uri("/tmp/x.tif") == Path("/tmp/x.tif").as_uri()
