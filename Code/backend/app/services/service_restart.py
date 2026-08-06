"""调度 launch.py 重启 FastAPI + Celery Worker + Beat（不动 Docker/Vite）。"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from app.core.config import BACKEND_ROOT, settings

logger = logging.getLogger(__name__)

REPO_ROOT = BACKEND_ROOT.parent.parent
DEFAULT_RESTART_COMPONENTS = ("fastapi", "worker", "beat")
_ALLOWED = frozenset({"fastapi", "worker", "beat"})


def ui_restart_allowed() -> bool:
    return bool(getattr(settings, "ui_restart_enabled", False))


def _python_exe() -> Path:
    win = REPO_ROOT / "Env" / "Python312" / "python.exe"
    if win.is_file():
        return win
    for rel in (
        Path("Env") / "Python312" / "bin" / "python",
        Path("Env") / "Python312" / "bin" / "python3",
    ):
        candidate = REPO_ROOT / rel
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def _normalize_components(components: list[str] | None) -> list[str]:
    raw = components or list(DEFAULT_RESTART_COMPONENTS)
    cleaned: list[str] = []
    for item in raw:
        name = str(item or "").strip().lower()
        if not name:
            continue
        if name not in _ALLOWED:
            raise ValueError(
                f"unsupported restart component: {item!r} "
                f"(allowed: {', '.join(sorted(_ALLOWED))})"
            )
        if name not in cleaned:
            cleaned.append(name)
    if not cleaned:
        raise ValueError("components must not be empty")
    # Stable order: workers before beat before fastapi so API comes up last
    order = {"worker": 0, "beat": 1, "fastapi": 2}
    return sorted(cleaned, key=lambda n: order.get(n, 9))


def schedule_backend_restart(
    components: list[str] | None = None,
    *,
    delay_seconds: float = 1.5,
) -> dict[str, object]:
    """校验开关后异步调度重启；调用方应先返回 HTTP 202。"""
    if not ui_restart_allowed():
        raise PermissionError(
            "UI backend restart is disabled "
            "(set BACKEND_UI_RESTART_ENABLED=true or use BACKEND_ENV=development)"
        )
    planned = _normalize_components(components)
    py = str(_python_exe())
    launch_py = str(REPO_ROOT / "launch.py")
    if not Path(launch_py).is_file():
        raise RuntimeError(f"launch.py not found: {launch_py}")

    def _runner() -> None:
        try:
            time.sleep(max(0.5, float(delay_seconds)))
            logger.warning(
                "UI-triggered backend restart starting components=%s", planned
            )
            # Prefer dedicated launch target that does not touch Docker/Vite.
            cmd = [py, launch_py, "restart", "backend"]
            kwargs: dict = {
                "cwd": str(REPO_ROOT),
                "env": dict(os.environ),
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "close_fds": True,
            }
            if sys.platform == "win32":
                # Detach from FastAPI so the dying parent does not kill the child.
                flags = 0
                flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
                flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
                kwargs["creationflags"] = flags
            else:
                kwargs["start_new_session"] = True
            subprocess.Popen(cmd, **kwargs)
        except Exception:
            logger.exception("Failed to schedule backend restart")

    threading.Thread(target=_runner, name="ui-backend-restart", daemon=True).start()
    return {
        "accepted": True,
        "components": planned,
        "delay_seconds": delay_seconds,
        "message": "Backend restart scheduled (FastAPI + Worker + Beat; Docker/Vite untouched)",
    }
