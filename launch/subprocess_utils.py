"""Cross-platform subprocess utilities for the CGDA launcher.

Extracted from the original ``launch.py``. Provides:

- Windows console-window hiding (``hidden_kwargs``).
- Python executable resolution (``python_executable``).
- Child environment construction with PYTHONPATH (``child_env``).
- Open-Meteo volume name resolution from ``data-sync/.env``.
- Docker named-volume ensure (``ensure_named_volume``).
- Project initialisation (``ensure_project_initialized``).
- Cross-platform process enumeration by command line
  (``enumerate_cmdline_rows``, ``list_matching_processes``).
- Cross-platform process termination by command-line patterns
  (``terminate_by_cmdline_patterns``, ``tree_kill_pid``).
- Termination verification (``wait_for_pattern_exit``).
- Port liveness / owner lookup (``port_listening``, ``netstat_listening_pids``).
- PID liveness check (``pid_alive``).
- Node.js / Vite resolution (``resolve_nodejs``, ``frontend_dev_command``).
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from launch.constants import (
    BACKEND_DIR,
    DATA_DIRS,
    DATA_SYNC_DIR,
    DEFAULT_OPEN_METEO_VOLUME,
    FRONTEND_DIR,
    IS_WINDOWS,
)
from launch.logging_setup import log


def hidden_kwargs() -> dict[str, Any]:
    """返回在 Windows 上隐藏控制台窗口的 subprocess 参数。"""
    kwargs: dict[str, Any] = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def python_executable() -> str:
    """返回子进程应使用的 Python：优先 ``Env/Python312``，否则当前解释器。"""
    try:
        from launch.env_python import env_python312_path

        env_py = env_python312_path()
        if env_py is not None:
            return str(env_py)
    except Exception:
        pass
    return sys.executable


def child_env() -> dict[str, str]:
    """子进程环境：UTF-8 + PYTHONPATH（backend / Code）。"""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    code_root = str(BACKEND_DIR.parent)
    paths = [str(BACKEND_DIR), code_root]
    prev = env.get("PYTHONPATH", "").strip()
    if prev:
        paths.append(prev)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def resolve_open_meteo_volume_name() -> str:
    """从 data-sync/.env 读取 volume 名，缺省 backend_open-meteo-data。"""
    env_file = DATA_SYNC_DIR / ".env"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                key, _, val = s.partition("=")
                if key.strip() == "OPEN_METEO_DATA_VOLUME":
                    name = val.strip().strip('"').strip("'")
                    if name:
                        return name
        except OSError:
            pass
    return DEFAULT_OPEN_METEO_VOLUME


def ensure_named_volume(name: str) -> bool:
    """确保 Docker named volume 存在（不落项目目录）。"""
    try:
        r = subprocess.run(
            ["docker", "volume", "inspect", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            **hidden_kwargs(),
        )
        if r.returncode == 0:
            return True
        log.info("Docker", f"创建 named volume: {name}")
        c = subprocess.run(
            ["docker", "volume", "create", name],
            capture_output=True,
            text=True,
            timeout=30,
            **hidden_kwargs(),
        )
        return c.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warn("Docker", f"volume 检查失败: {exc}")
        return False


def ensure_project_initialized() -> None:
    """跨平台初始化：数据目录、data-sync .env、前端依赖提示。"""
    for d in DATA_DIRS:
        d.mkdir(parents=True, exist_ok=True)

    if DATA_SYNC_DIR.is_dir():
        ds_env = DATA_SYNC_DIR / ".env"
        ds_ex = DATA_SYNC_DIR / ".env.example"
        if not ds_env.is_file() and ds_ex.is_file():
            shutil.copyfile(ds_ex, ds_env)
            log.info("Init", "已生成 data-sync .env ← .env.example")

    if not (FRONTEND_DIR / "node_modules").is_dir():
        log.warn(
            "Init", "前端 node_modules 缺失，请先在 Code/frontend 执行: npm install"
        )


def _is_editor_bundled_node(path: str) -> bool:
    """Cursor/VS Code 自带的 helpers/node，不适合作为 Vite 运行时。"""
    normalized = path.replace("\\", "/").lower()
    return "/resources/app/resources/helpers/" in normalized


def resolve_nodejs() -> str | None:
    """解析可用的 Node.js：优先系统安装，回退到编辑器自带 helpers。"""
    names = ("node.exe", "node") if IS_WINDOWS else ("node",)
    fallback: str | None = None
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        for name in names:
            candidate = Path(directory) / name
            if not candidate.is_file():
                continue
            resolved = (
                str(candidate.resolve()) if candidate.exists() else str(candidate)
            )
            if _is_editor_bundled_node(resolved):
                fallback = fallback or resolved
                continue
            return resolved
    which_hit = shutil.which("node.exe" if IS_WINDOWS else "node")
    if which_hit:
        return which_hit
    return fallback


def frontend_dev_command(port: int) -> list[str] | None:
    """解析前端启动命令。

    优先直接跑 node_modules/vite（避开 pnpm exec 的 deps-status / approve-builds 失败），
    其次 npx，最后 pnpm。
    """
    port_s = str(port)
    vite_js = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if vite_js.is_file():
        node = resolve_nodejs()
        if node:
            return [node, str(vite_js), "--port", port_s, "--host"]
    npx_candidates = ("npx.cmd", "npx.exe", "npx") if IS_WINDOWS else ("npx",)
    for cand in npx_candidates:
        if shutil.which(cand):
            return [cand, "vite", "--port", port_s, "--host"]
    pnpm_candidates = ("pnpm.cmd", "pnpm.exe", "pnpm") if IS_WINDOWS else ("pnpm",)
    for cand in pnpm_candidates:
        if shutil.which(cand):
            return [cand, "exec", "vite", "--port", port_s, "--host"]
    return None


def _resolve_windows_tool(name: str) -> str:
    """解析 System32 工具的绝对路径（PATH 缺 System32 时裸名会静默失败）。

    2026-08-16 事故：清扫用裸名 ``powershell``/``taskkill``，在 PATH 缺
    System32 的终端里枚举返回空 → 清扫 no-op → 旧世代进程堆叠。
    未知工具名原样返回，交由调用方处理。
    """
    if not IS_WINDOWS:
        return name
    sysroot = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    candidates: dict[str, list[str]] = {
        "powershell": [
            rf"{sysroot}\System32\WindowsPowerShell\v1.0\powershell.exe",
            rf"{sysroot}\SysWOW64\WindowsPowerShell\v1.0\powershell.exe",
        ],
        "pwsh": [rf"{sysroot}\System32\WindowsPowerShell\v1.0\powershell.exe"],
        "taskkill": [rf"{sysroot}\System32\taskkill.exe"],
        "docker": [rf"{sysroot}\System32\docker.exe"],
        "netstat": [rf"{sysroot}\System32\netstat.exe"],
    }
    for cand in candidates.get(name, []):
        if Path(cand).is_file():
            return cand
    return name


_ENUM_OK_SENTINEL = "__ENUM__|OK"
_ENUM_FAIL_SENTINEL = "__ENUM__|FAIL"


def _run_capture_text(cmd: list[str], timeout: float) -> str | None:
    """运行命令并解码 stdout（容错 zh-CN 控制台 GBK 输出）。

    ``subprocess.run(text=True)`` 强制 UTF-8 解码，在 OEM 代码页为 cp936 的
    中文 Windows 上会让读取线程抛 ``UnicodeDecodeError``、stdout 全损——
    2026-08-16 世代堆积事故的又一诱因（枚举输出被吞 → 清扫 no-op）。
    此处按字节捕获：先严格 UTF-8，失败回退本地 ANSI 代码页 + replace。
    """
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, **hidden_kwargs())
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    data = r.stdout or b""
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        import locale

        return data.decode(locale.getpreferredencoding(False), errors="replace")


def enumerate_cmdline_rows() -> tuple[bool, list[tuple[int, str]]]:
    """枚举全部进程，返回 ``(枚举是否可信, [(pid, cmdline), ...])``。

    Windows 经 PowerShell CIM/WMI；PowerShell 脚本开头强制 UTF-8 输出、
    末尾输出哨兵行（``__ENUM__|OK`` / ``__ENUM__|FAIL``），用于区分
    「无匹配」与「枚举本身失败（PATH 缺 System32 / WMI 异常 / 解码失败）」
    ——后者在 2026-08-16 事故中曾让清扫静默 no-op。
    POSIX 用 ``ps -eo pid=,args=``。
    """
    rows: list[tuple[int, str]] = []
    if IS_WINDOWS:
        ps_script = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'SilentlyContinue'
$rows = @()
try {
  $rows = @(Get-CimInstance Win32_Process | Select-Object ProcessId, CommandLine)
} catch { $rows = @() }
if (-not $rows -or $rows.Count -eq 0) {
  try { $rows = @(Get-WmiObject Win32_Process | Select-Object ProcessId, CommandLine) } catch { $rows = @() }
}
$rows | ForEach-Object {
  if ($_.CommandLine) {
    '{0}|{1}' -f $_.ProcessId, ($_.CommandLine -replace '[\r\n]+',' ')
  }
}
if ($rows -and $rows.Count -gt 0) { '__ENUM__|OK' } else { '__ENUM__|FAIL' }
"""
        out = _run_capture_text(
            [
                _resolve_windows_tool("powershell"),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script,
            ],
            timeout=30,
        )
        if out is None:
            return False, []
        lines = out.splitlines()
        ok = False
        for line in lines:
            stripped = line.strip()
            if stripped == _ENUM_OK_SENTINEL:
                ok = True
                continue
            if stripped == _ENUM_FAIL_SENTINEL:
                continue
            if "|" not in stripped:
                continue
            pid_s, _, cmdline = stripped.partition("|")
            try:
                pid = int(pid_s.strip())
            except ValueError:
                continue
            rows.append((pid, cmdline))
        return ok, rows

    try:
        r = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False, []
    for line in (r.stdout or "").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            rows.append((int(parts[0]), parts[1]))
        except ValueError:
            continue
    return True, rows


def list_matching_processes(patterns: list[str]) -> tuple[bool, list[tuple[int, str]]]:
    """按命令行子串筛选存活进程（不击杀）。返回 ``(枚举是否可信, 匹配行)``。"""
    ok, rows = enumerate_cmdline_rows()
    if not ok:
        return False, []
    my_pid = os.getpid()
    return True, [
        (pid, cmdline)
        for pid, cmdline in rows
        if pid != my_pid and any(pat in cmdline for pat in patterns)
    ]


def tree_kill_pid(pid: int) -> None:
    """按 PID 整树强杀（Windows: taskkill /T /F；POSIX: SIGKILL）。"""
    if IS_WINDOWS:
        subprocess.run(
            [_resolve_windows_tool("taskkill"), "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **hidden_kwargs(),
        )
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def terminate_by_cmdline_patterns(patterns: list[str]) -> int:
    """按命令行子串终止进程树（Windows: taskkill /T /F；POSIX: pkill -f）。

    返回已对其发出击杀命令的进程数；Windows 枚举不可用时返回 ``-1``
    （此时清扫为 no-op，调用方须用 :func:`wait_for_pattern_exit` 复核）。
    """
    if not patterns:
        return 0
    if IS_WINDOWS:
        ok, matches = list_matching_processes(patterns)
        if not ok:
            log.error(
                "Sweep",
                "进程枚举失败（powershell CIM/WMI 均不可用），本轮命令行清扫 no-op",
            )
            return -1
        for pid, _cmdline in matches:
            tree_kill_pid(pid)
        return len(matches)

    killed = 0
    for pat in patterns:
        try:
            r = subprocess.run(
                ["pkill", "-f", pat],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError):
            continue
        if r.returncode == 0:
            killed += 1
    return killed


def wait_for_pattern_exit(
    patterns: list[str], timeout: float = 10.0
) -> list[int] | None:
    """轮询等待匹配进程全部退出。

    返回仍存活的 PID 列表（空列表 = 已清洁）；枚举不可用（无法验证）时
    返回 ``None``，调用方应视为「不可信」而非「成功」。
    """
    deadline = time.monotonic() + timeout
    while True:
        ok, matches = list_matching_processes(patterns)
        if not ok:
            return None
        if not matches:
            return []
        if time.monotonic() >= deadline:
            return [pid for pid, _cmdline in matches]
        time.sleep(0.5)


def port_listening(host: str, port: int) -> bool:
    """TCP 探测端口是否被监听（connect 成功即视为监听）。"""
    import socket

    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def netstat_listening_pids(port: int) -> list[int]:
    """Windows netstat 查询端口监听属主 PID（去重；非 Windows 返回空）。"""
    if not IS_WINDOWS:
        return []
    out = _run_capture_text(
        [_resolve_windows_tool("netstat"), "-ano", "-p", "tcp"], timeout=20
    )
    if out is None:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING":
            local = parts[1]
            if local.rsplit(":", 1)[-1] == str(port):
                try:
                    pids.append(int(parts[4]))
                except ValueError:
                    continue
    return list(dict.fromkeys(pids))


def pid_alive(pid: int) -> bool:
    """检查进程是否存活（Windows: OpenProcess；Linux: os.kill(pid, 0)）。"""
    if IS_WINDOWS:
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
