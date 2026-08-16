"""launcher 进程清扫回归测试。

背景（2026-08-16 事故）：``launch.py restart backend`` 依赖
``terminate_by_cmdline_patterns`` 的裸名 ``powershell``/``taskkill`` 枚举杀
进程；当运行终端 PATH 缺 System32 时枚举静默返回空，清扫变 no-op，旧世代
FastAPI/Worker 堆叠（单日 5 世代约 50 进程），端口 8000 由最老僵尸应答，
``wait_for_fastapi`` 被旧进程"HTTP 就绪"骗过，代码修复看似不生效。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from launch import commands as launch_commands  # noqa: E402
from launch.subprocess_utils import (  # noqa: E402
    _resolve_windows_tool,
    terminate_by_cmdline_patterns,
)


def _strip_system32_env() -> dict[str, str]:
    """模拟缺 System32 的 PATH（保留 SystemRoot 供绝对路径推导）。"""
    env = {k: v for k, v in os.environ.items() if k.lower() != "path"}
    env["PATH"] = "C:\\nonexistent"
    env.setdefault("SystemRoot", "C:\\Windows")
    return env


def test_resolve_windows_tool_prefers_absolute_system32_path() -> None:
    sysroot = os.environ.get("SystemRoot", "C:\\Windows")
    ps = _resolve_windows_tool("powershell")
    assert ps.lower() == f"{sysroot}\\system32\\windowspowershell\\v1.0\\powershell.exe".lower()
    tk = _resolve_windows_tool("taskkill")
    assert tk.lower() == f"{sysroot}\\system32\\taskkill.exe".lower()
    # 未知工具名回退裸名（交由 shell 解析）
    assert _resolve_windows_tool("some-tool") == "some-tool"


def test_terminate_uses_absolute_tools_under_stripped_path() -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0].endswith("powershell.exe"):
            row = f"999999|py.exe D:\\repo\\Code\\backend\\start_fastapi.py"
            return mock.Mock(stdout=row, returncode=0)
        calls.append(list(cmd))
        return mock.Mock(returncode=0)

    with mock.patch.dict(os.environ, _strip_system32_env(), clear=True):
        with mock.patch.object(subprocess, "run", side_effect=fake_run):
            terminate_by_cmdline_patterns(["start_fastapi.py"])

    assert calls, "taskkill must be invoked through absolute path even without PATH"
    for cmd in calls:
        assert Path(cmd[0]).is_absolute(), f"taskkill 必须用绝对路径: {cmd[0]}"


def test_stop_backend_sweeps_pid_file_entries(monkeypatch, tmp_path) -> None:
    pid_file = tmp_path / "launcher_pids.json"
    pid_file.write_text(
        json.dumps({"fastapi": 111, "worker-realtime": 222, "beat": 333, "frontend": 444}),
        encoding="utf-8",
    )
    killed: list[int] = []

    monkeypatch.setattr(launch_commands, "PID_FILE", pid_file)
    monkeypatch.setattr(launch_commands, "terminate_by_cmdline_patterns", lambda pats: None)

    def fake_kill(pid: int, sig) -> None:
        killed.append(pid)

    monkeypatch.setattr(os, "kill", fake_kill)
    launch_commands._stop_backend_app_processes()

    assert set(killed) == {111, 222, 333}, "backend 世代进程须按 PID 文件兜底 SIGTERM"
    remaining = json.loads(pid_file.read_text(encoding="utf-8")) if pid_file.exists() else {}
    assert remaining == {"frontend": 444}, "非 backend 条目（frontend）应保留"


def test_start_backend_fails_when_fastapi_died_but_port_answers(monkeypatch) -> None:
    """新 fastapi 已死而端口仍被僵尸应答时，不得谎报启动成功。"""
    pm = mock.MagicMock()
    dead_proc = mock.MagicMock()
    dead_proc.poll.return_value = 1
    alive_proc = mock.MagicMock()
    alive_proc.poll.return_value = None
    pm.processes = {"fastapi": dead_proc, "beat": alive_proc}

    monkeypatch.setattr(launch_commands, "redis_running", lambda: True)
    monkeypatch.setattr(launch_commands.ProcessManager, "__new__", lambda cls, *a, **k: pm)
    monkeypatch.setattr(pm, "wait_for_fastapi", lambda max_wait=30: True)
    monkeypatch.setattr(pm, "save_pids", lambda merge=False: None)

    import argparse

    rc = launch_commands._start_backend_app_processes(
        argparse.Namespace(debug=False, frontend_port=5175)
    )
    assert rc != 0, "fastapi 进程已退出时须返回失败而非 0"
