"""launcher 进程清扫回归测试。

背景（2026-08-16 事故）：``launch.py restart backend`` 依赖
``terminate_by_cmdline_patterns`` 的裸名 ``powershell``/``taskkill`` 枚举杀
进程；当运行终端 PATH 缺 System32 时枚举静默返回空，清扫变 no-op，旧世代
FastAPI/Worker 堆叠（单日 5 世代约 50 进程），端口 8000 由最老僵尸应答，
``wait_for_fastapi`` 被旧进程"HTTP 就绪"骗过，代码修复看似不生效。

本轮修复新增：枚举哨兵（区分「无匹配」与「枚举失败」）、整树击杀、
spawn 孤儿子进程清除、死亡验证与升级、端口属主核对、未清洁则中止重启。
"""

from __future__ import annotations

import argparse
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
    wait_for_pattern_exit,
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
    assert (
        ps.lower()
        == f"{sysroot}\\system32\\windowspowershell\\v1.0\\powershell.exe".lower()
    )
    tk = _resolve_windows_tool("taskkill")
    assert tk.lower() == f"{sysroot}\\system32\\taskkill.exe".lower()
    # 未知工具名回退裸名（交由 shell 解析）
    assert _resolve_windows_tool("some-tool") == "some-tool"


def test_terminate_uses_absolute_tools_under_stripped_path() -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0].endswith("powershell.exe"):
            row = (
                "999999|py.exe D:\\repo\\Code\\backend\\start_fastapi.py\n"
                "__ENUM__|OK"
            )
            return mock.Mock(stdout=row, returncode=0)
        calls.append(list(cmd))
        return mock.Mock(returncode=0)

    with mock.patch.dict(os.environ, _strip_system32_env(), clear=True):
        with mock.patch.object(subprocess, "run", side_effect=fake_run):
            killed = terminate_by_cmdline_patterns(["start_fastapi.py"])

    assert killed == 1, "枚举可信且命中 1 个进程"
    assert calls, "taskkill must be invoked through absolute path even without PATH"
    for cmd in calls:
        assert Path(cmd[0]).is_absolute(), f"taskkill 必须用绝对路径: {cmd[0]}"
        assert cmd[1:4] == ["/PID", "999999", "/T"]


def test_terminate_returns_minus1_when_enum_sentinel_missing() -> None:
    """PowerShell 无 OK 哨兵 = 枚举不可信，清扫必须显式 no-op 而非误报成功。"""

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0].endswith("powershell.exe"):
            # 模拟 2026-08-16：WMI 异常，只有行数据但无哨兵（不可信）
            return mock.Mock(stdout="999999|py.exe start_fastapi.py", returncode=0)
        raise AssertionError("枚举不可信时不得调用 taskkill")

    with mock.patch.dict(os.environ, _strip_system32_env(), clear=True):
        with mock.patch.object(subprocess, "run", side_effect=fake_run):
            killed = terminate_by_cmdline_patterns(["start_fastapi.py"])
    assert killed == -1


def test_terminate_skips_non_matching_rows() -> None:
    taskkill_calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0].endswith("powershell.exe"):
            return mock.Mock(
                stdout=(
                    "111|py.exe D:\\repo\\start_fastapi.py\n"
                    "222|py.exe D:\\repo\\unrelated_server.py\n"
                    "__ENUM__|OK"
                ),
                returncode=0,
            )
        taskkill_calls.append(list(cmd))
        return mock.Mock(returncode=0)

    with mock.patch.object(subprocess, "run", side_effect=fake_run):
        killed = terminate_by_cmdline_patterns(["start_fastapi.py"])

    assert killed == 1
    assert len(taskkill_calls) == 1
    assert taskkill_calls[0][2] == "111"


def test_wait_for_pattern_exit_states(monkeypatch) -> None:
    from launch import subprocess_utils as su

    # 清洁：立即返回空列表
    monkeypatch.setattr(su, "list_matching_processes", lambda pats: (True, []))
    assert wait_for_pattern_exit(["x"], timeout=0.1) == []
    # 存活：超时后返回存活 PID
    monkeypatch.setattr(
        su, "list_matching_processes", lambda pats: (True, [(111, "cmd x")])
    )
    assert wait_for_pattern_exit(["x"], timeout=0.1) == [111]
    # 枚举不可用：返回 None（不可信，调用方不得当作成功）
    monkeypatch.setattr(su, "list_matching_processes", lambda pats: (False, []))
    assert wait_for_pattern_exit(["x"], timeout=0.1) is None


def test_stop_backend_sweeps_pid_file_entries(monkeypatch, tmp_path) -> None:
    pid_file = tmp_path / "launcher_pids.json"
    pid_file.write_text(
        json.dumps(
            {"fastapi": 111, "worker-realtime": 222, "beat": 333, "frontend": 444}
        ),
        encoding="utf-8",
    )
    killed: list[int] = []

    monkeypatch.setattr(launch_commands, "PID_FILE", pid_file)
    monkeypatch.setattr(
        launch_commands, "terminate_by_cmdline_patterns", lambda pats: 0
    )
    monkeypatch.setattr(launch_commands, "_terminate_cgda_spawn_children", lambda: 0)
    monkeypatch.setattr(launch_commands, "_verify_backend_stop", lambda: True)

    def fake_kill(pid: int, sig) -> None:
        killed.append(pid)

    monkeypatch.setattr(os, "kill", fake_kill)
    assert launch_commands._stop_backend_app_processes() is True

    assert set(killed) == {111, 222, 333}, "backend 世代进程须按 PID 文件兜底 SIGTERM"
    remaining = (
        json.loads(pid_file.read_text(encoding="utf-8")) if pid_file.exists() else {}
    )
    assert remaining == {"frontend": 444}, "非 backend 条目（frontend）应保留"


def test_stop_backend_propagates_unclean_result(monkeypatch, tmp_path) -> None:
    """验证不通过时必须返回 False（restart 据此中止，防止世代堆叠）。"""
    pid_file = tmp_path / "launcher_pids.json"
    pid_file.write_text(json.dumps({"fastapi": 111}), encoding="utf-8")
    monkeypatch.setattr(launch_commands, "PID_FILE", pid_file)
    monkeypatch.setattr(
        launch_commands, "terminate_by_cmdline_patterns", lambda pats: 0
    )
    monkeypatch.setattr(launch_commands, "_terminate_cgda_spawn_children", lambda: 0)
    monkeypatch.setattr(launch_commands, "_verify_backend_stop", lambda: False)
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)

    assert launch_commands._stop_backend_app_processes() is False


def test_restart_backend_aborts_when_stop_unclean(monkeypatch) -> None:
    monkeypatch.setattr(launch_commands, "ensure_project_initialized", lambda: None)
    monkeypatch.setattr(launch_commands, "_stop_backend_app_processes", lambda: False)
    started: list[object] = []
    monkeypatch.setattr(
        launch_commands,
        "_start_backend_app_processes",
        lambda args: started.append(args) or 0,
    )
    args = argparse.Namespace(
        clean_cache=False, component="backend", debug=False, frontend_port=5175
    )
    rc = launch_commands.cmd_restart(args)
    assert rc == 1, "清扫未验证通过时必须中止重启"
    assert not started, "不得在脏进程面上启动新世代"


def test_verify_backend_stop_escalates_then_fails_on_survivors(monkeypatch) -> None:
    sweeps: list[list[str]] = []
    monkeypatch.setattr(
        launch_commands,
        "wait_for_pattern_exit",
        lambda pats, timeout=10.0: [111],
    )
    monkeypatch.setattr(
        launch_commands,
        "terminate_by_cmdline_patterns",
        lambda pats: sweeps.append(pats) or 0,
    )
    monkeypatch.setattr(launch_commands, "_terminate_cgda_spawn_children", lambda: 0)
    monkeypatch.setattr(launch_commands, "port_listening", lambda h, p: False)

    assert launch_commands._verify_backend_stop() is False
    assert sweeps, "存活时必须升级击杀一轮"


def test_verify_backend_stop_fails_when_port_still_busy(monkeypatch) -> None:
    monkeypatch.setattr(
        launch_commands, "wait_for_pattern_exit", lambda pats, timeout=10.0: []
    )
    monkeypatch.setattr(launch_commands, "port_listening", lambda h, p: True)
    monkeypatch.setattr(
        launch_commands, "_kill_port_owner_if_backend", lambda port: True
    )
    assert launch_commands._verify_backend_stop() is False


def test_verify_backend_stop_enum_unavailable_falls_back_to_pid_file(
    monkeypatch, tmp_path
) -> None:
    """枚举不可用时按 PID 文件条目树杀兜底；仍存活则判不清洁。"""
    pid_file = tmp_path / "launcher_pids.json"
    pid_file.write_text(json.dumps({"fastapi": 111, "frontend": 444}), encoding="utf-8")
    monkeypatch.setattr(launch_commands, "PID_FILE", pid_file)
    monkeypatch.setattr(
        launch_commands, "wait_for_pattern_exit", lambda pats, timeout=10.0: None
    )
    tree_killed: list[int] = []
    monkeypatch.setattr(
        launch_commands, "tree_kill_pid", lambda pid: tree_killed.append(pid)
    )
    monkeypatch.setattr(launch_commands, "pid_alive", lambda pid: True)
    monkeypatch.setattr(launch_commands, "port_listening", lambda h, p: False)

    assert launch_commands._verify_backend_stop() is False
    assert tree_killed == [111], "只兜底 backend 条目，不动 frontend"


def test_terminate_cgda_spawn_children_uses_marker_pair(monkeypatch) -> None:
    """spawn 孤儿判定 = spawn_main + Env/Python312 解释器，二者缺一不杀。"""
    monkeypatch.setattr(
        launch_commands,
        "python_executable",
        lambda: "D:\\repo\\Env\\Python312\\python.exe",
    )
    monkeypatch.setattr(
        launch_commands,
        "enumerate_cmdline_rows",
        lambda: (
            True,
            [
                (
                    1,
                    "D:\\repo\\Env\\Python312\\python.exe -c "
                    "from multiprocessing.spawn import spawn_main",
                ),
                (
                    2,
                    "C:\\Other\\python.exe -c "
                    "from multiprocessing.spawn import spawn_main",
                ),
                (3, "D:\\repo\\Env\\Python312\\python.exe -m pytest"),
            ],
        ),
    )
    tree_killed: list[int] = []
    monkeypatch.setattr(
        launch_commands, "tree_kill_pid", lambda pid: tree_killed.append(pid)
    )

    killed = launch_commands._terminate_cgda_spawn_children()
    assert killed == 1
    assert tree_killed == [1]


def test_kill_port_owner_skips_unrelated_process(monkeypatch) -> None:
    """端口属主是无关进程时只告警不击杀。"""
    monkeypatch.setattr(launch_commands, "IS_WINDOWS", True)
    monkeypatch.setattr(launch_commands, "netstat_listening_pids", lambda port: [777])
    monkeypatch.setattr(
        launch_commands,
        "enumerate_cmdline_rows",
        lambda: (True, [(777, "C:\\tools\\other-dev-server.exe --port 8000")]),
    )
    monkeypatch.setattr(
        launch_commands,
        "python_executable",
        lambda: "D:\\repo\\Env\\Python312\\python.exe",
    )
    tree_killed: list[int] = []
    monkeypatch.setattr(
        launch_commands, "tree_kill_pid", lambda pid: tree_killed.append(pid)
    )

    assert launch_commands._kill_port_owner_if_backend(8000) is False
    assert tree_killed == [], "无关进程不得自动击杀"


def test_kill_port_owner_kills_cgda_process(monkeypatch) -> None:
    monkeypatch.setattr(launch_commands, "IS_WINDOWS", True)
    monkeypatch.setattr(launch_commands, "netstat_listening_pids", lambda port: [888])
    monkeypatch.setattr(
        launch_commands,
        "enumerate_cmdline_rows",
        lambda: (
            True,
            [(888, "D:\\repo\\Env\\Python312\\python.exe -c spawn_main uvicorn")],
        ),
    )
    monkeypatch.setattr(
        launch_commands,
        "python_executable",
        lambda: "D:\\repo\\Env\\Python312\\python.exe",
    )
    tree_killed: list[int] = []
    monkeypatch.setattr(
        launch_commands, "tree_kill_pid", lambda pid: tree_killed.append(pid)
    )

    assert launch_commands._kill_port_owner_if_backend(8000) is True
    assert tree_killed == [888]


def test_start_backend_fails_when_fastapi_died_but_port_answers(monkeypatch) -> None:
    """新 fastapi 已死而端口仍被僵尸应答时，不得谎报启动成功。"""
    pm = mock.MagicMock()
    dead_proc = mock.MagicMock()
    dead_proc.poll.return_value = 1
    alive_proc = mock.MagicMock()
    alive_proc.poll.return_value = None
    pm.processes = {"fastapi": dead_proc, "beat": alive_proc}

    monkeypatch.setattr(launch_commands, "redis_running", lambda: True)
    monkeypatch.setattr(
        launch_commands.ProcessManager, "__new__", lambda cls, *a, **k: pm
    )
    monkeypatch.setattr(pm, "wait_for_fastapi", lambda max_wait=30: True)
    monkeypatch.setattr(pm, "save_pids", lambda merge=False: None)

    rc = launch_commands._start_backend_app_processes(
        argparse.Namespace(debug=False, frontend_port=5175)
    )
    assert rc != 0, "fastapi 进程已退出时须返回失败而非 0"


def test_stop_all_skips_exited_psutil_handle() -> None:
    """已退出的 psutil.Process 句柄：直接跳过，不得调 poll/terminate。"""
    import psutil as psutil_mod

    from launch.process_manager import ProcessManager

    exited = mock.Mock(spec=psutil_mod.Process)
    exited.is_running.return_value = False
    exited.pid = 9999

    # 用 object.__new__ 绕过 __init__：本文件前序测试 monkeypatch 过
    # ProcessManager.__new__，直接实例化会踩到撤销残留
    pm = object.__new__(ProcessManager)
    pm.processes = {"beat": exited}
    pm._awaiting_external_restart = {}
    pm.stop_all()

    exited.terminate.assert_not_called()
    exited.wait.assert_not_called()
    assert pm.processes == {}


def test_stop_all_terminates_alive_psutil_handle() -> None:
    """monitor 外部重启切到 psutil.Process 后，Ctrl+C 停止须能正常 terminate。"""
    import psutil as psutil_mod

    from launch.process_manager import ProcessManager

    alive = mock.Mock(spec=psutil_mod.Process)
    alive.is_running.return_value = True
    alive.pid = 1111
    alive.wait.side_effect = [0]  # terminate 后 10s 内正常退出

    pm = object.__new__(ProcessManager)
    pm.processes = {"fastapi": alive}
    pm._awaiting_external_restart = {}
    pm.stop_all()

    alive.terminate.assert_called_once()
    alive.kill.assert_not_called()
    assert pm.processes == {}


def test_stop_all_escalates_kill_on_psutil_timeout() -> None:
    """psutil wait 超时抛 psutil.TimeoutExpired 时必须升级 kill（回归：此前
    只捕获 subprocess.TimeoutExpired，psutil 句柄超时会二次崩溃）。"""
    import psutil as psutil_mod

    from launch.process_manager import ProcessManager

    alive = mock.Mock(spec=psutil_mod.Process)
    alive.is_running.return_value = True
    alive.pid = 2222
    alive.wait.side_effect = [
        psutil_mod.TimeoutExpired(10),  # terminate 后 10s 未退出
        None,  # kill 后退出
    ]

    pm = object.__new__(ProcessManager)
    pm.processes = {"fastapi": alive}
    pm._awaiting_external_restart = {}
    pm.stop_all()

    alive.terminate.assert_called_once()
    alive.kill.assert_called_once()
    assert pm.processes == {}


def test_stop_all_falls_back_to_tree_kill_on_psutil_access_denied(monkeypatch) -> None:
    """Windows 外部接管句柄 wait 抛 AccessDenied 时不得崩；改 taskkill。"""
    import psutil as psutil_mod

    from launch import process_manager as pm_mod
    from launch.process_manager import ProcessManager

    killed: list[int] = []
    monkeypatch.setattr(pm_mod, "tree_kill_pid", lambda pid: killed.append(pid))

    alive = mock.Mock(spec=psutil_mod.Process)
    alive.is_running.return_value = True
    alive.pid = 37448
    alive.wait.side_effect = psutil_mod.AccessDenied(pid=37448)

    pm = object.__new__(ProcessManager)
    pm.processes = {"fastapi": alive}
    pm._awaiting_external_restart = {}
    pm.stop_all()

    alive.terminate.assert_called_once()
    assert killed == [37448]
    assert pm.processes == {}


def test_monitor_adopts_new_pid_from_file_on_external_restart(
    monkeypatch, tmp_path
) -> None:
    """外部 restart 写新 PID 后，旧进程退出应 INFO 接管，不得 ERROR。"""
    import psutil as psutil_mod

    from launch import process_manager as pm_mod
    from launch.process_manager import ProcessManager

    pid_file = tmp_path / "launcher_pids.json"
    pid_file.write_text(json.dumps({"fastapi": 99901}), encoding="utf-8")
    monkeypatch.setattr(pm_mod, "PID_FILE", pid_file)

    old = mock.Mock()
    old.poll.return_value = 1
    old.pid = 10001

    new_proc = mock.Mock(spec=psutil_mod.Process)
    new_proc.pid = 99901
    new_proc.is_running.return_value = True

    monkeypatch.setattr(
        pm_mod.psutil, "Process", lambda pid: new_proc if pid == 99901 else mock.Mock()
    )
    # 避免走 cmdline 枚举
    monkeypatch.setattr(
        ProcessManager, "_discover_backend_process", lambda self, name: None
    )

    errors: list[str] = []
    infos: list[str] = []
    monkeypatch.setattr(
        pm_mod.log, "error", lambda *a, **k: errors.append(str(a))
    )
    monkeypatch.setattr(pm_mod.log, "info", lambda *a, **k: infos.append(str(a)))

    pm = object.__new__(ProcessManager)
    pm.processes = {"fastapi": old}
    pm._awaiting_external_restart = {}
    pm._shutting_down = False
    pm.monitor()

    assert pm.processes["fastapi"] is new_proc
    assert not errors
    assert any("外部重启" in msg for msg in infos)


def test_monitor_grace_then_adopting_via_cmdline(monkeypatch, tmp_path) -> None:
    """PID 文件空窗：先宽限；下次 poll 用 cmdline 发现新进程并接管。"""
    import psutil as psutil_mod

    from launch import process_manager as pm_mod
    from launch.process_manager import ProcessManager

    pid_file = tmp_path / "launcher_pids.json"
    # stop 已清掉 backend 条目
    pid_file.write_text(json.dumps({"frontend": 1}), encoding="utf-8")
    monkeypatch.setattr(pm_mod, "PID_FILE", pid_file)
    monkeypatch.setattr(pm_mod, "_EXTERNAL_RESTART_GRACE_S", 90.0)

    old = mock.Mock()
    old.poll.return_value = 1
    old.pid = 10001

    infos: list[str] = []
    errors: list[str] = []
    monkeypatch.setattr(pm_mod.log, "info", lambda *a, **k: infos.append(str(a)))
    monkeypatch.setattr(
        pm_mod.log, "error", lambda *a, **k: errors.append(str(a))
    )
    monkeypatch.setattr(
        ProcessManager, "_discover_backend_process", lambda self, name: None
    )

    pm = object.__new__(ProcessManager)
    pm.processes = {"fastapi": old}
    pm._awaiting_external_restart = {}
    pm._shutting_down = False
    pm.monitor()

    assert "fastapi" not in pm.processes
    assert "fastapi" in pm._awaiting_external_restart
    assert not errors
    assert any("等待外部重启" in msg for msg in infos)

    new_proc = mock.Mock(spec=psutil_mod.Process)
    new_proc.pid = 20002
    new_proc.is_running.return_value = True
    monkeypatch.setattr(
        ProcessManager, "_discover_backend_process", lambda self, name: new_proc
    )

    pm.monitor()
    assert pm.processes["fastapi"] is new_proc
    assert "fastapi" not in pm._awaiting_external_restart
    assert not errors


def test_monitor_grace_timeout_reports_error(monkeypatch, tmp_path) -> None:
    """宽限超时仍无替换进程 → 才报异常退出。"""
    from launch import process_manager as pm_mod
    from launch.process_manager import ProcessManager

    pid_file = tmp_path / "launcher_pids.json"
    pid_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(pm_mod, "PID_FILE", pid_file)
    monkeypatch.setattr(
        ProcessManager, "_discover_backend_process", lambda self, name: None
    )
    monkeypatch.setattr(
        ProcessManager, "_external_pid_for", lambda self, name: None
    )

    errors: list[str] = []
    monkeypatch.setattr(
        pm_mod.log, "error", lambda *a, **k: errors.append(" ".join(str(x) for x in a))
    )
    monkeypatch.setattr(pm_mod.log, "info", lambda *a, **k: None)

    pm = object.__new__(ProcessManager)
    pm.processes = {}
    pm._awaiting_external_restart = {"beat": 0.0}  # 已过期
    pm._shutting_down = False
    pm.monitor()

    assert any("宽限已过" in e or "异常退出" in e for e in errors)
