"""remote_sync 健壮性测试：子目录结构保留、重试续传、walk 错误上浮、Windows 文件名消毒。"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ingest import remote_sync as rs


# ── Windows 文件名消毒 ────────────────────────────────────────────────────────


def test_sanitize_rel_path_reserved_and_illegal():
    assert rs.sanitize_rel_path("data/file<1>.mat") == "data/file_1_.mat"
    assert rs.sanitize_rel_path("CON.mat") == "_CON.mat"
    assert rs.sanitize_rel_path("COM1/data.mat") == "_COM1/data.mat"
    assert rs.sanitize_rel_path("aux/lpt3.nc") == "_aux/_lpt3.nc"
    assert rs.sanitize_rel_path("trailing.dot. ") == "trailing.dot"
    # 目录穿越段被消毒为占位段
    assert ".." not in rs.sanitize_rel_path("../escape.mat").split("/")


def test_sanitize_rel_path_never_empty():
    assert rs.sanitize_rel_path("///") == ""
    assert rs.sanitize_rel_path("???") == "___"


# ── _sftp_walk：子目录结构保留 + walk 错误收集 ────────────────────────────────


class _FakeSftpEntry:
    def __init__(self, name: str, is_dir: bool, size: int = 0):
        self.filename = name
        self.st_mode = (stat.S_IFDIR | 0o755) if is_dir else (stat.S_IFREG | 0o644)
        self.st_size = size


class _FakeSftp:
    def __init__(self, tree: dict[str, list[_FakeSftpEntry]]):
        self._tree = tree

    def listdir_attr(self, path: str):
        if path in self._tree:
            return self._tree[path]
        raise OSError(f"no such directory: {path}")


def test_sftp_walk_preserves_subdir_structure():
    tree = {
        "/data": [_FakeSftpEntry("a", True), _FakeSftpEntry("b", True)],
        "/data/a": [_FakeSftpEntry("same.mat", False, size=10)],
        "/data/b": [_FakeSftpEntry("same.mat", False, size=20)],
    }
    files = list(rs._sftp_walk(_FakeSftp(tree), "/data"))
    rels = sorted(rel for _, rel, _ in files)
    # 相对遍历根：子目录结构保留，同名文件不互相覆盖
    assert rels == ["a/same.mat", "b/same.mat"]


def test_sftp_walk_collects_unreadable_dirs():
    tree = {
        "/data": [_FakeSftpEntry("ok", True), _FakeSftpEntry("bad", True)],
        "/data/ok": [_FakeSftpEntry("f.mat", False, size=1)],
    }
    errors: list[str] = []
    files = list(rs._sftp_walk(_FakeSftp(tree), "/data", walk_errors=errors))
    assert [rel for _, rel, _ in files] == ["ok/f.mat"]
    assert len(errors) == 1
    assert "/data/bad" in errors[0]


def test_filebrowser_walk_preserves_subdir_structure(monkeypatch):
    tree = {
        "/data": [rs.RemoteFile("/data/a", "a", 0, True), rs.RemoteFile("/data/b", "b", 0, True)],
        "/data/a": [rs.RemoteFile("/data/a/same.mat", "same.mat", 10, False)],
        "/data/b": [rs.RemoteFile("/data/b/same.mat", "same.mat", 20, False)],
    }
    monkeypatch.setattr(rs, "_filebrowser_list_dir", lambda _u, _t, p: tree[p])
    files = list(rs._filebrowser_walk("http://nas", "tok", "/data"))
    rels = sorted(rel for _, rel, _ in files)
    assert rels == ["a/same.mat", "b/same.mat"]


def test_filebrowser_walk_collects_unreadable_dirs(monkeypatch):
    def fake_list(_u, _t, path):
        if path == "/data/bad":
            raise rs.URLError("timeout")
        if path == "/data":
            return [rs.RemoteFile("/data/ok", "ok", 0, True), rs.RemoteFile("/data/bad", "bad", 0, True)]
        if path == "/data/ok":
            return [rs.RemoteFile("/data/ok/f.mat", "f.mat", 1, False)]
        return []

    monkeypatch.setattr(rs, "_filebrowser_list_dir", fake_list)
    errors: list[str] = []
    files = list(rs._filebrowser_walk("http://nas", "tok", "/data", walk_errors=errors))
    assert [rel for _, rel, _ in files] == ["ok/f.mat"]
    assert len(errors) == 1
    assert "/data/bad" in errors[0]


# ── _sync_one_file：增量跳过 / 断点续传 / 单文件重试 ─────────────────────────


def _make_result() -> rs.SyncResult:
    return rs.SyncResult(local_path="/tmp/x")


def _no_sleep(monkeypatch):
    monkeypatch.setattr(rs.time, "sleep", lambda _s: None)


def test_sync_one_file_skips_equal(tmp_path: Path):
    local = tmp_path / "f.mat"
    local.write_bytes(b"12345")
    result = _make_result()
    rs._sync_one_file(
        None, "/r/f.mat", local, 5, result,
        None, False, lambda *_a, **_k: pytest.fail("不应下载"),
        date_range=None, rel="f.mat",
    )
    assert result.skipped == 1
    assert result.downloaded == 0


def test_sync_one_file_partial_resumes(tmp_path: Path):
    local = tmp_path / "f.mat"
    local.write_bytes(b"12345")
    offsets: list[int] = []

    def download(_rp, _lp, _rs, offset, _cb):
        offsets.append(offset)
        with _lp.open("ab") as fh:
            fh.write(b"67890")
        return True

    result = _make_result()
    rs._sync_one_file(
        None, "/r/f.mat", local, 10, result, None, False,
        download, date_range=None, rel="f.mat",
    )
    assert offsets == [5]
    assert result.resumed == 1
    assert result.downloaded == 1
    assert local.read_bytes() == b"1234567890"


def test_sync_one_file_retry_recomputes_resume_offset(tmp_path, monkeypatch):
    """首次失败后按本地已落盘字节重算续传偏移，不整文件重来。"""
    _no_sleep(monkeypatch)
    local = tmp_path / "f.mat"
    calls: list[int] = []

    def flaky_download(_rp, lp, _rs, offset, _cb):
        calls.append(offset)
        if len(calls) == 1:
            with lp.open("ab") as fh:
                fh.write(b"1234")
            return False  # 中途断连
        with lp.open("ab") as fh:
            fh.write(b"56")
        return True

    result = _make_result()
    rs._sync_one_file(
        None, "/r/f.mat", local, 6, result, None, False,
        flaky_download, date_range=None, rel="f.mat",
    )
    # 第 1 次从 0 开始；失败后本地已有 4 字节 → 第 2 次从 4 续传
    assert calls == [0, 4]
    assert result.downloaded == 1
    assert result.failed == 0
    assert local.read_bytes() == b"123456"


def test_sync_one_file_retry_success_after_equalized(tmp_path, monkeypatch):
    """失败但本地已达完整大小（远端提前关闭）应视为成功，不再重试。"""
    _no_sleep(monkeypatch)
    local = tmp_path / "f.mat"
    calls: list[int] = []

    def download(_rp, lp, _rs, _offset, _cb):
        calls.append(1)
        with lp.open("wb") as fh:
            fh.write(b"abcdef")
        return False

    result = _make_result()
    rs._sync_one_file(
        None, "/r/f.mat", local, 6, result, None, False,
        download, date_range=None, rel="f.mat",
    )
    assert len(calls) == 1
    assert result.downloaded == 1
    assert result.failed == 0


def test_sync_one_file_exhausted_retries(tmp_path, monkeypatch):
    _no_sleep(monkeypatch)
    local = tmp_path / "f.mat"

    def always_fail(_rp, _lp, _rs, _offset, _cb):
        return False

    result = _make_result()
    rs._sync_one_file(
        None, "/r/f.mat", local, 6, result, None, False,
        always_fail, date_range=None, rel="f.mat",
    )
    assert result.failed == 1
    assert result.downloaded == 0
    assert result.errors == ["/r/f.mat"]


def test_sync_one_file_date_filter_skips_out_of_range(tmp_path: Path):
    local = tmp_path / "FY20250101x.mat"
    result = _make_result()
    rs._sync_one_file(
        None, "/r/FY20250101x.mat", local, 5, result,
        None, False, lambda *_a, **_k: pytest.fail("不应下载"),
        date_range=("20240101", "20241231"), rel="FY20250101x.mat",
    )
    assert result.total_files == 0 and result.skipped == 0 and result.downloaded == 0


# ── sync_dataset：walk 错误上浮到 result.errors ──────────────────────────────


def test_sync_dataset_surfaces_walk_errors(tmp_path, monkeypatch):
    _no_sleep(monkeypatch)
    tree = {
        "/data": [_FakeSftpEntry("ok", True), _FakeSftpEntry("bad", True)],
        "/data/ok": [_FakeSftpEntry("f.mat", False, size=3)],
    }

    class _FakeSftpFile:
        def __init__(self, data: bytes):
            self._data = data
            self._pos = 0

        def seek(self, off: int):
            self._pos = off

        def read(self, n: int = -1):
            end = len(self._data) if n < 0 else min(len(self._data), self._pos + n)
            chunk = self._data[self._pos : end]
            self._pos = end
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _FakeSSH:
        def close(self):
            pass

    class _FakeSftpClient(_FakeSftp):
        def close(self):
            pass

        def open(self, path: str, _mode: str = "rb"):
            assert path == "/data/ok/f.mat"
            return _FakeSftpFile(b"abc")

    monkeypatch.setattr(
        rs, "_sftp_connect", lambda _cfg: (_FakeSSH(), _FakeSftpClient(tree))
    )
    config = rs.ServerConfig(
        server_type="hpc", host="hpc", port=22, username="u", password="p"
    )
    result = rs.sync_dataset(config, "/data", tmp_path)
    assert result.total_files == 1
    assert result.downloaded == 1
    assert (tmp_path / "ok" / "f.mat").read_bytes() == b"abc"
    assert any("/data/bad" in e for e in result.errors)


# ── ssh_sync 模块：file_filter 字符串/列表 双形态解析（模板 vs 表单对齐） ────


def _ssh_sync_ctx(workspace: Path):
    from types import SimpleNamespace
    from workflow.schemas import NodeExecutionContext

    class _FakeStore:
        items: dict[str, object] = {}

        def put(self, artifact, payload=None):
            self.items[artifact.artifact_id] = payload
            return artifact

    request = SimpleNamespace(
        job_id="j1", datasource_selection={}, region=None, time_range=None
    )
    runtime = SimpleNamespace(run_id="r1", workspace=str(workspace))
    return NodeExecutionContext(
        workflow_id="wf",
        node_id="n1",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=_FakeStore(),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "raw",
    [".mat,.h5", "mat;h5", ".mat .h5", ["mat", ".h5"]],
)
def test_ssh_sync_file_filter_accepts_string_and_list(
    tmp_path: Path, monkeypatch, raw
) -> None:
    import contracts.job  # noqa: F401
    from modules.download_nodes import SshSyncModule

    captured: dict[str, object] = {}

    def _fake_sync_dataset(**kwargs):
        captured.update(kwargs)
        return rs.SyncResult(
            total_files=1, downloaded=1, local_path=str(kwargs["local_path"])
        )

    monkeypatch.setattr(
        "ingest.remote_sync.sync_dataset", lambda **kw: _fake_sync_dataset(**kw)
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    out = SshSyncModule().execute(
        inputs={},
        params={
            "server_type": "hpc",
            "host": "hpc",
            "username": "u",
            "password": "p",
            "remote_path": "/data",
            "local_path": str(local_dir),
            "file_filter": raw,
        },
        ctx=_ssh_sync_ctx(workspace),
    )
    assert captured["file_filter"] == frozenset({".mat", ".h5"})
    assert Path(out["path"]) == local_dir
