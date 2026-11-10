"""NAS 按需补帧的「本地共享盘直读」通道（2026-11-10）。

背景
────
按需补帧原先只有一条路：FileBrowser（``nasfile.personaltunnel.dpdns.org``）。
那条隧道挂在 Cloudflare 后面，隧道一断（530 / 1033）所有补帧请求整片失败，
前端看到的就是「取数服务暂时不可用」，而数据本体在局域网共享盘上一直好好的。

现在加了第二条通道：直接读 UNC 路径。红线不变 ——
· 仍然先过 ``assert_nas_path_readable()`` 白名单和 ``assert_mat_filename()``；
· 本地路径只能由「远程白名单路径」推导，调用方无法直接传本地路径；
· 只读。

本文件锁住的正是这几条边界，防止以后为了「跑通」把校验绕过去。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = "/Liuzheng/omega_final"
_PRODUCT_DIR = f"{_ROOT}/fy_avg_smvod"


@pytest.fixture()
def fake_share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """在 tmp 下造一个与线上同构的共享盘根：<root>/Liuzheng/omega_final/fy_avg_smvod。

    用 tmp 而不是真共享盘，是为了让测试在没有 NAS 的机器上也能跑；
    真机联调时的映射关系由 ``test_local_root_matches_remote_prefix`` 之外
    的手工核对保证（远程 ``/Liuzheng/...`` 对应 ``<ROOT>\\Liuzheng\\...``）。
    """
    root = tmp_path / "group_nas"
    product = root / "Liuzheng" / "omega_final" / "fy_avg_smvod"
    product.mkdir(parents=True)
    (product / "20250101.mat").write_bytes(b"fake-mat-2025-01-01")
    (product / "20250102.mat").write_bytes(b"fake-mat-2025-01-02")
    (product / "notes.txt").write_text("not a mat", encoding="utf-8")

    monkeypatch.setenv("CGDA_FY_NAS_LOCAL_ROOT", str(root))
    monkeypatch.setenv("CGDA_FY_NAS_ACCESS_MODE", "local")

    from app.services.nas_ondemand import fetcher

    fetcher.reset_local_probe()
    yield root
    fetcher.reset_local_probe()


def test_local_root_maps_remote_prefix(fake_share: Path):
    """远程白名单路径 → 本地路径，层级必须一比一对齐。"""
    from app.services.nas_ondemand import fetcher

    mapped = fetcher._local_path(str(fake_share), f"{_PRODUCT_DIR}/20250101.mat")
    assert mapped == fake_share / "Liuzheng" / "omega_final" / "fy_avg_smvod" / "20250101.mat"
    assert mapped.is_file()


def test_list_dir_reads_local_files(fake_share: Path):
    """本地列举返回 name/isDir/size，调用方（has_date_file 等）只依赖这些。"""
    from app.services.nas_ondemand import fetcher

    items = fetcher.list_dir(_PRODUCT_DIR)
    names = {it["name"] for it in items}
    assert {"20250101.mat", "20250102.mat", "notes.txt"} <= names
    for it in items:
        assert isinstance(it["name"], str)
        assert isinstance(it["isDir"], bool)
        assert isinstance(it["size"], int)


def test_has_date_file_only_counts_mat(fake_share: Path):
    """判「有没有这一天」只认 .mat 文件名，notes.txt 之类不算。"""
    from app.services.nas_ondemand import fetcher

    assert fetcher.has_date_file(_PRODUCT_DIR, "20250101") is True
    assert fetcher.has_date_file(_PRODUCT_DIR, "20250103") is False


def test_download_mat_copies_bytes(fake_share: Path, tmp_path: Path):
    """下载内容与源文件逐字节一致，且不留下 .part 残骸。"""
    from app.services.nas_ondemand import fetcher

    dest = tmp_path / "out" / "20250101.mat"
    written = fetcher.download_mat(_PRODUCT_DIR, "20250101", dest)
    assert written == len(b"fake-mat-2025-01-01")
    assert dest.read_bytes() == b"fake-mat-2025-01-01"
    assert not (tmp_path / "out" / "20250101.mat.part").exists()


def test_missing_file_raises_missing_not_unavailable(fake_share: Path, tmp_path: Path):
    """缺文件是「正常业务情况」，不能被报成服务故障（否则前端会建议重试）。"""
    from app.services.nas_ondemand import fetcher

    with pytest.raises(fetcher.NasFileMissing):
        fetcher.download_mat(_PRODUCT_DIR, "20250103", tmp_path / "20250103.mat")


def test_path_whitelist_still_blocks_escape(fake_share: Path, tmp_path: Path):
    """白名单先于本地通路生效：越界路径在「碰盘之前」就被拒。"""
    from app.services.nas_ondemand import fetcher

    for bad in (f"{_ROOT}/../secret/", "/etc/passwd", f"{_ROOT}/other_dataset/"):
        with pytest.raises(fetcher.NasPathDenied):
            fetcher.assert_nas_path_readable(bad)

    # 即便有人绕过上层直接调 list_dir，也必须被白名单拦住
    with pytest.raises(fetcher.NasPathDenied):
        fetcher.list_dir("/Liuzheng/omega_final/../../etc/")


def test_filename_whitelist_still_blocks(fake_share: Path, tmp_path: Path):
    """只允许三种已核对的 .mat 命名。"""
    from app.services.nas_ondemand import fetcher

    with pytest.raises(fetcher.NasPathDenied):
        fetcher.download_file(_PRODUCT_DIR, "notes.txt", tmp_path / "notes.txt")
    with pytest.raises(fetcher.NasPathDenied):
        fetcher.download_file(_PRODUCT_DIR, "20250101.mat.exe", tmp_path / "x.exe")


def test_local_path_rejects_prefix_sibling(tmp_path: Path):
    """同前缀的兄弟目录不算命中（normpath 之后必须真在根下）。"""
    from app.services.nas_ondemand import fetcher

    root = str(tmp_path / "group_nas")
    (tmp_path / "group_nas").mkdir()
    (tmp_path / "group_nas_evil").mkdir()
    with pytest.raises(fetcher.NasPathDenied):
        fetcher._local_path(root, "../group_nas_evil/secret.mat")


def test_auto_mode_falls_back_when_root_unreachable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """auto：根不可达 ⇒ 返回 None，交回 HTTP 通道，不报错。"""
    from app.services.nas_ondemand import fetcher

    monkeypatch.setenv("CGDA_FY_NAS_LOCAL_ROOT", str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("CGDA_FY_NAS_ACCESS_MODE", "auto")
    fetcher.reset_local_probe()
    assert fetcher._local_root_or_none() is None
    fetcher.reset_local_probe()


def test_local_mode_fails_loudly_when_root_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """local：根不可达 ⇒ 直接报错。不能悄悄回落隧道，否则排障会被误导。"""
    from app.services.nas_ondemand import fetcher

    monkeypatch.setenv("CGDA_FY_NAS_LOCAL_ROOT", str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("CGDA_FY_NAS_ACCESS_MODE", "local")
    fetcher.reset_local_probe()
    with pytest.raises(fetcher.NasUnavailable):
        fetcher._local_root_or_none()
    fetcher.reset_local_probe()


def test_local_mode_requires_root_configured(monkeypatch: pytest.MonkeyPatch):
    """local 模式但没配根目录 ⇒ 报错并点名缺哪个环境变量。"""
    from app.services.nas_ondemand import fetcher

    monkeypatch.delenv("CGDA_FY_NAS_LOCAL_ROOT", raising=False)
    monkeypatch.setenv("CGDA_FY_NAS_ACCESS_MODE", "local")
    with pytest.raises(fetcher.NasUnavailable) as exc:
        fetcher._local_root_or_none()
    assert "CGDA_FY_NAS_LOCAL_ROOT" in str(exc.value)


def test_http_mode_never_touches_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """http 模式：即使配了本地根也不用它（保持旧行为，便于回滚）。"""
    from app.services.nas_ondemand import fetcher

    root = tmp_path / "group_nas"
    root.mkdir()
    monkeypatch.setenv("CGDA_FY_NAS_LOCAL_ROOT", str(root))
    monkeypatch.setenv("CGDA_FY_NAS_ACCESS_MODE", "http")
    fetcher.reset_local_probe()
    assert fetcher._local_root_or_none() is None


def test_unknown_mode_falls_back_to_auto(monkeypatch: pytest.MonkeyPatch):
    """模式写错不该把功能打死：按 auto 处理。"""
    from app.services.nas_ondemand import config

    monkeypatch.setenv("CGDA_FY_NAS_ACCESS_MODE", "locall")
    assert config.nas_access_mode() == config.NAS_ACCESS_AUTO


def test_status_reports_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """排障用状态里要能看出「到底走没走本地」。"""
    from app.services.nas_ondemand import fetcher

    root = tmp_path / "group_nas"
    root.mkdir()
    monkeypatch.setenv("CGDA_FY_NAS_LOCAL_ROOT", str(root))
    monkeypatch.setenv("CGDA_FY_NAS_ACCESS_MODE", "auto")
    fetcher.reset_local_probe()
    status = fetcher.local_access_status()
    assert status["mode"] == "auto"
    assert status["local_root"] == str(root)
    assert status["local_root_reachable"] is True
