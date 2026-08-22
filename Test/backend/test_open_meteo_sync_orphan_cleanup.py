"""C-5（2026-08-23）：Open-Meteo sync 孤儿容器清理回归测试。

背景（docker 实验实证）：
1. ``subprocess.run(timeout=...)`` 超时只杀 ``docker compose run`` 客户端，
   run 容器在 daemon 里继续跑（客户端 SIGKILL 后容器仍 Up）；
2. ``docker compose stop/rm <service>`` 对 run 创建的容器**无效**（compose 只
   管理 up 创建的服务容器）——只能按 compose label 定位 + ``docker rm -f``；
3. 孤儿与下轮 sync 并发写同一 volume。

修复：超时路径 + 拿锁后防御性清理（两个调用点均在持锁状态，正常 sync 的
容器不会被误杀——互斥锁保证拿锁时不存在合法进行中的 sync）。
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from app.tasks import open_meteo_sync_tasks as sync_mod


class _FakeCompleted:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# ── kill_orphan_sync_containers 单元行为 ────────────────────────────────────


def test_orphan_cleanup_removes_listed_containers(monkeypatch) -> None:
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["docker", "ps", "-q"]:
            return _FakeCompleted(stdout="abc123\ndef456\n")
        if cmd[:3] == ["docker", "rm", "-f"]:
            return _FakeCompleted(returncode=0)
        raise AssertionError(f"unexpected cmd: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    removed = sync_mod.kill_orphan_sync_containers()

    assert removed == 2
    rm_calls = [c for c in calls if c[:3] == ["docker", "rm", "-f"]]
    assert rm_calls == [
        ["docker", "rm", "-f", "abc123"],
        ["docker", "rm", "-f", "def456"],
    ]
    # 定位命令按 project + service label 过滤
    list_cmd = next(c for c in calls if c[:3] == ["docker", "ps", "-q"])
    assert any("label=com.docker.compose.project=" in part for part in list_cmd)
    assert any(
        "label=com.docker.compose.service=open-meteo-sync" in part for part in list_cmd
    )


def test_orphan_cleanup_noop_when_none(monkeypatch) -> None:
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompleted(stdout="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert sync_mod.kill_orphan_sync_containers() == 0
    assert not any(c[:3] == ["docker", "rm", "-f"] for c in calls)


def test_orphan_cleanup_docker_missing_silent(monkeypatch) -> None:
    def _fake_run(cmd, **kwargs):
        raise FileNotFoundError("docker not found")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert sync_mod.kill_orphan_sync_containers() == 0  # 不抛


def test_orphan_cleanup_partial_failure_still_counts_attempt(monkeypatch) -> None:
    def _fake_run(cmd, **kwargs):
        if cmd[:3] == ["docker", "ps", "-q"]:
            return _FakeCompleted(stdout="abc\ndef\n")
        # 第一个 rm 成功，第二个失败
        if cmd[3] == "abc":
            return _FakeCompleted(returncode=0)
        return _FakeCompleted(returncode=1, stderr="boom")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    removed = sync_mod.kill_orphan_sync_containers()
    assert removed == 2  # 报告尝试清除的数量（含失败者）


# ── execute_open_meteo_sync 集成（超时路径 + 防御性清理）──────────────────


@pytest.fixture()
def sync_env(monkeypatch, tmp_path):
    """隔离 settings 与 redis 锁，记录全部 subprocess 调用。"""
    calls: list[list[str]] = []
    timeout_first = {"armed": True}

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        is_compose_run = (
            len(cmd) > 5 and cmd[0] == "docker" and cmd[1] == "compose" and "run" in cmd
        )
        if is_compose_run and timeout_first["armed"]:
            timeout_first["armed"] = False
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)
        if cmd[:3] == ["docker", "ps", "-q"]:
            return _FakeCompleted(stdout="")
        if cmd[:3] == ["docker", "rm", "-f"]:
            return _FakeCompleted(returncode=0)
        if cmd[:3] == ["docker", "volume", "inspect"]:
            return _FakeCompleted(returncode=0)  # volume 已存在
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    # frozen settings 不可 setattr——整体替换模块级 settings 引用
    fake_settings = SimpleNamespace(
        open_meteo_sync_compose_project="data-sync-test",
        open_meteo_sync_domains="ecmwf_ifs025",
        open_meteo_sync_compose_dir=str(tmp_path),
        open_meteo_sync_variables="temperature_2m",
    )
    monkeypatch.setattr(sync_mod, "settings", fake_settings)

    # 无 redis：进程内锁兜底（每次测试独立进程内 holder 集合，直接清空防串扰）
    monkeypatch.setattr(sync_mod, "get_redis_client", lambda: None)
    sync_mod._sync_local_holders.clear()

    recorded: list[dict] = []

    def _fake_record(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(
        "app.services.weather_engine_settings.record_open_meteo_sync_result",
        _fake_record,
    )
    return {"calls": calls, "recorded": recorded}


def test_timeout_path_cleans_orphan_before_unlock(sync_env) -> None:
    """C-5 核心：超时（客户端被杀）→ 先清孤儿 → 再抛错（finally 释锁在后）。"""
    with pytest.raises(RuntimeError, match="timed out"):
        sync_mod.execute_open_meteo_sync()

    calls = sync_env["calls"]
    # compose run 客户端（超时源）
    assert any(c[0] == "docker" and c[1] == "compose" and "run" in c for c in calls)
    # 超时后立即出现孤儿定位命令（docker ps -q + label 过滤）
    list_calls = [c for c in calls if c[:3] == ["docker", "ps", "-q"]]
    assert len(list_calls) >= 1
    # 顺序：compose run 在前，第一次孤儿定位在其后
    run_idx = next(i for i, c in enumerate(calls) if c[0] == "docker" and "run" in c)
    assert any(
        i > run_idx for i, c in enumerate(calls) if c[:3] == ["docker", "ps", "-q"]
    )
    # 失败被记录
    assert any("timed out" in str(r.get("message", "")) for r in sync_env["recorded"])
    # 锁已释放（进程内 holders 清空）
    assert not sync_mod._sync_local_holders


def test_sync_start_cleans_leftover_orphans_defensively(sync_env, monkeypatch) -> None:
    """C-5 防御：拿锁成功后先清残留孤儿（覆盖 worker 被杀遗留场景）。"""
    # 禁用超时注入：compose run 直接成功
    compose_calls = {"armed": False}

    def _fake_run_ok(cmd, **kwargs):
        if cmd[0] == "docker" and cmd[1] == "compose" and "run" in cmd:
            return _FakeCompleted(returncode=0, stdout="done")
        if cmd[:3] == ["docker", "ps", "-q"]:
            return _FakeCompleted(stdout="orphan1\n")
        if cmd[:3] == ["docker", "rm", "-f"]:
            return _FakeCompleted(returncode=0)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run_ok)

    result = sync_mod.execute_open_meteo_sync()
    assert result["status"] == "succeeded"
    calls = sync_env["calls"]  # 未被本测试使用（monkeypatch 二次覆盖）
    # orphan1 被防御性清除
    # （_fake_run_ok 内无法记录，改为验证顺序语义：直接断言 rm 调用过）
    # 重新断言：清理先于 compose run（防御语义）——通过独立探针验证
    probe: list[str] = []

    def _fake_run_probe(cmd, **kwargs):
        probe.append(
            "rm"
            if cmd[:3] == ["docker", "rm", "-f"]
            else "run"
            if ("compose" in cmd[:3] or (len(cmd) > 2 and cmd[1] == "compose"))
            else "other"
        )
        return _FakeCompleted(
            returncode=0,
            stdout="" if cmd[:3] != ["docker", "ps", "-q"] else "orphan1\n",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run_probe)
    sync_mod.execute_open_meteo_sync()
    # 孤儿清除（rm）发生在 compose run 之前
    first_rm = probe.index("rm")
    first_run = next(i for i, p in enumerate(probe) if p == "run")
    assert first_rm < first_run


def test_lock_held_skips_entirely(sync_env) -> None:
    """锁被持（另一入口同步中）→ 不清孤儿不起 sync（既有行为回归）。"""
    token = sync_mod.acquire_open_meteo_sync_lock("ecmwf_ifs025")
    assert token is not None
    try:
        result = sync_mod.execute_open_meteo_sync()
        assert result["status"] == "skipped"
        # 未触发任何 docker compose run
        assert not any(
            c[0] == "docker" and c[1] == "compose" and "run" in c
            for c in sync_env["calls"]
        )
    finally:
        sync_mod.release_open_meteo_sync_lock("ecmwf_ifs025", token)
