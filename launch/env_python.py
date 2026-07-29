"""强制 / 解析仓库内 ``Env/Python312`` 解释器。

本地联调约定：**唯一** Python 运行时为 ``Env/Python312``（Windows:
``Env\\Python312\\python.exe``）。勿使用系统 PATH 中的其它 Python，
否则依赖（如 rarfile）与后端不一致。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# launch/env_python.py → 仓库根
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_MARKER = "CGDA_USING_ENV_PYTHON312"


def env_python312_path(repo_root: Path | None = None) -> Path | None:
    """返回 Env/Python312 解释器路径；不存在则 None。"""
    root = repo_root or _REPO_ROOT
    if sys.platform in ("win32", "win"):
        candidate = root / "Env" / "Python312" / "python.exe"
        return candidate if candidate.is_file() else None
    for rel in (
        Path("Env") / "Python312" / "bin" / "python",
        Path("Env") / "Python312" / "bin" / "python3",
        Path("Env") / "Python312" / "python",
    ):
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def is_running_env_python312(repo_root: Path | None = None) -> bool:
    env_py = env_python312_path(repo_root)
    if env_py is None:
        return False
    try:
        return Path(sys.executable).resolve() == env_py.resolve()
    except OSError:
        return False


def ensure_env_python312(*, reexec: bool = True) -> Path | None:
    """若存在 Env/Python312 且当前不是它，则 ``os.execv`` 切换到该解释器。

    返回最终应使用的解释器路径（可能为 None，表示仓库内未找到 Env）。
    """
    env_py = env_python312_path()
    if env_py is None:
        return None
    if is_running_env_python312():
        os.environ[_ENV_MARKER] = "1"
        return env_py
    if not reexec:
        return env_py
    if os.environ.get(_ENV_MARKER) == "1":
        # 已尝试切换仍不一致时避免死循环
        return env_py
    os.environ[_ENV_MARKER] = "1"
    os.execv(str(env_py), [str(env_py), *sys.argv])
    return env_py  # pragma: no cover


def require_env_python312_message() -> str:
    return (
        "本仓库本地联调必须使用 Env/Python312 解释器。\n"
        "  Windows: Env\\Python312\\python.exe（请用 start.bat / stop.bat）\n"
        "  或: Env\\Python312\\python.exe launch.py start\n"
        "勿使用系统 PATH 中的 python，以免依赖与后端不一致。"
    )
