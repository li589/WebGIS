"""GDAL 可执行文件发现链跨平台测试（硬编码清理 2026-08-20 A1）。

覆盖：
- 平台后缀：Windows 拼 .exe；Linux 无后缀（env CGDA_GDAL_BIN 在 Linux 生效）
- Windows 专属探测（OSGeo4W/QGIS）在非 Windows 被跳过
- conda Linux 布局（$CONDA_PREFIX/bin）候选
- 全部失败时按平台给出可诊断报错
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import ingest.fy_preprocess as fp


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("CGDA_GDAL_BIN", "CONDA_PREFIX"):
        monkeypatch.delenv(key, raising=False)


def _make_fake_bins(directory: Path, suffix: str) -> Path:
    """在目录中放置 4 个假 GDAL 可执行文件。"""
    directory.mkdir(parents=True, exist_ok=True)
    for name in (
        "gdal_translate",
        "gdalbuildvrt",
        "gdalwarp",
        "gdalinfo",
    ):
        (directory / (name + suffix)).write_text("#!/bin/sh\n", encoding="utf-8")
    return directory


def test_env_bin_dir_effective_on_linux_layout(tmp_path, monkeypatch):
    """Linux 布局：CGDA_GDAL_BIN 指向无 .exe 后缀的 bin 目录也能命中。"""
    monkeypatch.setattr(fp, "_IS_WINDOWS", False)
    monkeypatch.setattr(fp, "_GDAL_SUFFIX", "")
    bin_dir = _make_fake_bins(tmp_path / "gdalbin", "")
    monkeypatch.setenv("CGDA_GDAL_BIN", str(bin_dir))
    t, b, w, i, prefix = fp._resolve_gdal_bins()
    assert Path(t).name == "gdal_translate"  # 无 .exe 后缀
    assert Path(prefix) == bin_dir


def test_windows_layout_still_uses_exe_suffix(tmp_path, monkeypatch):
    """Windows 布局：env 指向含 .exe 的目录照旧命中（行为回归）。"""
    monkeypatch.setattr(fp, "_IS_WINDOWS", True)
    monkeypatch.setattr(fp, "_GDAL_SUFFIX", ".exe")
    bin_dir = _make_fake_bins(tmp_path / "winbin", ".exe")
    monkeypatch.setenv("CGDA_GDAL_BIN", str(bin_dir))
    t, _, _, _, prefix = fp._resolve_gdal_bins()
    assert Path(t).name == "gdal_translate.exe"
    assert Path(prefix) == bin_dir


def test_env_bin_without_exe_files_not_matched_on_linux(tmp_path, monkeypatch):
    """Linux 下 env 目录只含 .exe 文件（Windows 布局）不应命中。"""
    monkeypatch.setattr(fp, "_IS_WINDOWS", False)
    monkeypatch.setattr(fp, "_GDAL_SUFFIX", "")
    bin_dir = _make_fake_bins(tmp_path / "mixed", ".exe")
    monkeypatch.setenv("CGDA_GDAL_BIN", str(bin_dir))
    with pytest.raises(FileNotFoundError) as exc_info:
        fp._resolve_gdal_bins()
    # 报错文案按平台：Linux 不提 OSGeo4W/QGIS
    assert "CGDA_GDAL_BIN" in str(exc_info.value)
    assert "OSGeo4W" not in str(exc_info.value)


def test_error_message_on_windows_lists_all_channels(monkeypatch):
    monkeypatch.setattr(fp, "_IS_WINDOWS", True)
    monkeypatch.setattr(fp, "_GDAL_SUFFIX", ".exe")
    # 真机上 QGIS/OSGeo4W 可能真实存在——mock 掉全部探测候选强制走失败分支
    monkeypatch.setattr(fp, "_FORCE_GDAL_BIN", r"Z:\nonexistent\gdal")
    monkeypatch.setattr(fp, "_qgis_candidates", lambda: [])
    monkeypatch.setattr(fp.shutil, "which", lambda _: None)
    with pytest.raises(FileNotFoundError) as exc_info:
        fp._resolve_gdal_bins()
    assert "OSGeo4W" in str(exc_info.value)
    assert "QGIS" in str(exc_info.value)


def test_conda_prefix_bin_candidate_on_linux(tmp_path, monkeypatch):
    """Linux conda 布局：$CONDA_PREFIX/bin 命中（无 env 显式指定时）。"""
    monkeypatch.setattr(fp, "_IS_WINDOWS", False)
    monkeypatch.setattr(fp, "_GDAL_SUFFIX", "")
    _make_fake_bins(tmp_path / "condaroot" / "bin", "")
    monkeypatch.setenv("CONDA_PREFIX", str(tmp_path / "condaroot"))
    # 解释器目录候选不存在假文件；which 关闭强制走 conda 分支
    monkeypatch.setattr(fp.shutil, "which", lambda _: None)
    t, _, _, _, prefix = fp._resolve_gdal_bins()
    assert Path(prefix) == tmp_path / "condaroot" / "bin"


def test_qgis_gdal_driver_path_set_when_hdf5_plugin_present(tmp_path, monkeypatch):
    """QGIS bin + apps/gdal/lib/gdalplugins/gdal_HDF5.dll → 写入 GDAL_DRIVER_PATH。"""
    monkeypatch.delenv("GDAL_DRIVER_PATH", raising=False)
    qgis_root = tmp_path / "QGIS"
    bin_dir = _make_fake_bins(qgis_root / "bin", ".exe")
    plugins = qgis_root / "apps" / "gdal" / "lib" / "gdalplugins"
    plugins.mkdir(parents=True)
    (plugins / "gdal_HDF5.dll").write_bytes(b"x")
    monkeypatch.setattr(fp, "_IS_WINDOWS", True)
    fp._maybe_set_qgis_gdal_driver_path(str(bin_dir))
    assert Path(os.environ["GDAL_DRIVER_PATH"]) == plugins


def test_qgis_gdal_driver_path_respects_existing_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GDAL_DRIVER_PATH", r"Z:\custom\plugins")
    qgis_root = tmp_path / "QGIS"
    bin_dir = _make_fake_bins(qgis_root / "bin", ".exe")
    plugins = qgis_root / "apps" / "gdal" / "lib" / "gdalplugins"
    plugins.mkdir(parents=True)
    (plugins / "gdal_HDF5.dll").write_bytes(b"x")
    fp._maybe_set_qgis_gdal_driver_path(str(bin_dir))
    assert os.environ["GDAL_DRIVER_PATH"] == r"Z:\custom\plugins"


def test_algorithms_fy_resolve_gdal_bins_uses_absolute_paths(tmp_path, monkeypatch):
    """ω / fy_execute 共用 resolve_gdal_bins：必须是绝对路径，禁止裸命令名。"""
    from algorithms.fy import resolve_gdal_bins

    monkeypatch.setattr(fp, "_IS_WINDOWS", True)
    monkeypatch.setattr(fp, "_GDAL_SUFFIX", ".exe")
    bin_dir = _make_fake_bins(tmp_path / "gdalbin", ".exe")
    monkeypatch.setenv("CGDA_GDAL_BIN", str(bin_dir))
    monkeypatch.delenv("GDAL_DRIVER_PATH", raising=False)
    bins = resolve_gdal_bins()
    assert Path(bins["gdal_translate"]).is_absolute()
    assert bins["gdal_translate"].endswith("gdal_translate.exe")
    assert Path(bins["gdal_translate"]).name != "gdal_translate"


def test_algorithms_fy_resolve_gdal_bins_force_bin(tmp_path, monkeypatch):
    from algorithms.fy import resolve_gdal_bins

    monkeypatch.setattr(fp, "_IS_WINDOWS", True)
    monkeypatch.setattr(fp, "_GDAL_SUFFIX", ".exe")
    bin_dir = _make_fake_bins(tmp_path / "forced", ".exe")
    monkeypatch.delenv("CGDA_GDAL_BIN", raising=False)
    bins = resolve_gdal_bins(force_bin=str(bin_dir))
    assert Path(bins["gdal_translate"]).parent == bin_dir


def test_module_platform_constants_consistent():
    """模块平台常量与 os.name 一致（防未来误改）。"""
    if os.name == "nt":
        assert fp._GDAL_SUFFIX == ".exe"
        assert fp._IS_WINDOWS is True
    else:
        assert fp._GDAL_SUFFIX == ""
        assert fp._IS_WINDOWS is False
    assert sys.platform  # sanity
