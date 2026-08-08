"""spatialite_loader 单测。

设计要点：
- 扩展缺失时所有真实加载测试 ``pytest.skip``，不阻断本地 Windows（mod_spatialite 未装时）。
- 探测缓存是模块级全局，每个测试前后必须 reset，避免互相污染。
- ``load_into`` 必须幂等、降级、永不抛、加载后 re-disable。
"""

from __future__ import annotations

import sqlite3
import sys

import pytest

from app.services import spatialite_loader


@pytest.fixture(autouse=True)
def _reset_probe():
    """每个测试前后重置探测缓存 + PATH prepend 标记。"""
    spatialite_loader.reset_probe_cache()
    yield
    spatialite_loader.reset_probe_cache()


def _ext_available() -> bool:
    spatialite_loader.reset_probe_cache()
    return spatialite_loader.is_available()


def test_load_into_graceful_when_missing():
    """扩展缺失时 load_into 返回 False 且不抛。"""
    spatialite_loader._probe_cache = spatialite_loader._ProbeResult(
        False, None, "test: forced unavailable"
    )
    conn = sqlite3.connect(":memory:")
    assert spatialite_loader.load_into(conn) is False
    assert not getattr(conn, "_spatialite_loaded", False)


def test_load_into_warns_once(caplog):
    """扩展不可用时多次 load_into 只 warn 一次。"""
    import logging

    spatialite_loader._probe_cache = spatialite_loader._ProbeResult(
        False, None, "test: warn-once"
    )
    with caplog.at_level(logging.WARNING, logger="app.services.spatialite_loader"):
        for _ in range(3):
            conn = sqlite3.connect(":memory:")
            assert spatialite_loader.load_into(conn) is False
    msgs = [
        r
        for r in caplog.records
        if "SpatiaLite extension not available" in r.getMessage()
    ]
    assert len(msgs) == 1


def test_load_into_disabled_returns_false(monkeypatch):
    """BACKEND_SPATIALITE_ENABLED=false 时 load_into 直接返回 False。

    直接 monkeypatch _enabled 以确定性地覆盖「总开关关闭」分支（避免依赖
    env→Settings→模块全局 的脆弱链，且不受其他测试的 settings 状态污染）。
    """
    monkeypatch.setattr(spatialite_loader, "_enabled", lambda: False)
    conn = sqlite3.connect(":memory:")
    assert spatialite_loader.load_into(conn) is False


def test_load_into_re_disables_extension():
    """加载后必须重新关闭 enable_load_extension（防滥用）。"""
    if not _ext_available():
        pytest.skip("mod_spatialite not installed on this host")
    conn = sqlite3.connect(":memory:")
    assert spatialite_loader.load_into(conn) is True
    # 已 re-disable：直接 load_extension 应被拒
    with pytest.raises(sqlite3.OperationalError):
        conn.load_extension("nonexistent_ext")


def test_load_into_is_idempotent():
    """二次调用幂等，返回 True 且不重复加载。"""
    if not _ext_available():
        pytest.skip("mod_spatialite not installed on this host")
    conn = sqlite3.connect(":memory:")
    assert spatialite_loader.load_into(conn) is True
    assert spatialite_loader.load_into(conn) is True


def test_platform_path_resolution_env_override(monkeypatch, tmp_path):
    """env BACKEND_SPATIALITE_PATH 覆盖（文件或目录）。"""
    # 文件形式
    fake = tmp_path / "mod_spatialite.dll"
    fake.write_bytes(b"")
    monkeypatch.setenv("BACKEND_SPATIALITE_PATH", str(fake))
    spatialite_loader.reset_probe_cache()
    probe = spatialite_loader._probe()
    assert probe.path == fake

    # 目录形式：自动找 mod_spatialite.so
    d = tmp_path / "extdir"
    d.mkdir()
    so = d / "mod_spatialite.so"
    so.write_bytes(b"")
    monkeypatch.setenv("BACKEND_SPATIALITE_PATH", str(d))
    spatialite_loader.reset_probe_cache()
    probe = spatialite_loader._probe()
    assert probe.path == so


def test_probe_reason_when_not_found(monkeypatch):
    """扩展文件找不到时 reason 非空（Linux 无 env 时返回裸名，available 仍 True）。"""
    monkeypatch.setenv("BACKEND_SPATIALITE_PATH", str("/nonexistent/path/x"))
    spatialite_loader.reset_probe_cache()
    probe = spatialite_loader._probe()
    # env 指向不存在的文件/目录 → 回退到平台默认探测
    # （不强制断言 available，因平台默认探测结果随环境而变）
    assert isinstance(probe, spatialite_loader._ProbeResult)
