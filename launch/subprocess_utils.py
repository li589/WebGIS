"""Cross-platform subprocess utilities for the CGDA launcher.

Extracted from the original ``launch.py``. Provides:

- Windows console-window hiding (``hidden_kwargs``).
- Python executable resolution (``python_executable``).
- Child environment construction with PYTHONPATH (``child_env``).
- Open-Meteo volume name resolution from ``data-sync/.env``.
- Docker named-volume ensure (``ensure_named_volume``).
- Project initialisation (``ensure_project_initialized``).
- Cross-platform process termination by command-line patterns
  (``terminate_by_cmdline_patterns``).
- PID liveness check (``pid_alive``).
- Node.js / Vite resolution (``resolve_nodejs``, ``frontend_dev_command``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
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
    """返回当前 Python 解释器路径，确保子进程使用同一环境。"""
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


def terminate_by_cmdline_patterns(patterns: list[str]) -> None:
    """按命令行子串终止进程（Windows: CIM/WMI/taskkill 回退；Linux: pkill -f）。"""
    if not patterns:
        return
    if IS_WINDOWS:
        ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$rows = @()
try {
  $rows = @(Get-CimInstance Win32_Process | Select-Object ProcessId, CommandLine)
} catch {
  try { $rows = @(Get-WmiObject Win32_Process | Select-Object ProcessId, CommandLine) } catch { $rows = @() }
}
$rows | ForEach-Object {
  if ($_.CommandLine) {
    '{0}|{1}' -f $_.ProcessId, ($_.CommandLine -replace '[\r\n]+',' ')
  }
}
"""
        try:
            r = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps_script,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                **hidden_kwargs(),
            )
            lines = (r.stdout or "").splitlines()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            lines = []

        my_pid = os.getpid()
        for line in lines:
            if "|" not in line:
                continue
            pid_s, _, cmdline = line.partition("|")
            try:
                pid = int(pid_s.strip())
            except ValueError:
                continue
            if pid == my_pid:
                continue
            if any(pat in cmdline for pat in patterns):
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    **hidden_kwargs(),
                )
        return

    for pat in patterns:
        subprocess.run(
            ["pkill", "-f", pat],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


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
