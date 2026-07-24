"""Path constants, service definitions, and defaults for the CGDA launcher.

All module-level constants that were historically inline in ``launch.py``.
Centralising them here lets every ``launch/`` submodule reference the same
paths without re-declaring them, and makes it obvious which directories
the launcher touches.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ─── 路径常量 ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent.parent  # launch/ → project root
BACKEND_DIR = SCRIPT_DIR / "Code" / "backend"
FRONTEND_DIR = SCRIPT_DIR / "Code" / "frontend"
DATA_SYNC_DIR = SCRIPT_DIR / "Code" / "infra" / "data-sync"
LOG_DIR = BACKEND_DIR / ".data" / "logs"
DATA_DIRS = [
    BACKEND_DIR / ".data" / "logs",
    BACKEND_DIR / ".data" / "workflow_state",
    BACKEND_DIR / ".data" / "artifacts",
    BACKEND_DIR / ".data" / "cache",
]
LAUNCHER_LOG = LOG_DIR / "launcher.log"
PID_FILE = LOG_DIR / "launcher_pids.json"
WEATHER_CACHE_DIR = BACKEND_DIR / ".data" / "cache" / "weather"
WEATHERENGINE_CACHE_DIR = BACKEND_DIR / ".data" / "cache" / "weatherengine"

# ─── workflow_state 重置相关路径 ─────────────────────────────────────────────
WORKFLOW_STATE_DIR = BACKEND_DIR / ".data" / "workflow_state"
WORKFLOW_STATE_DB_STEM = "workflow_state.sqlite3"
WORKFLOW_DEFINITIONS_DIR = BACKEND_DIR / ".data" / "workflow_definitions"
WORKFLOW_SEEDS_DIR = BACKEND_DIR / "workflow_seeds" / "system"
SNAPSHOT_ROOT = BACKEND_DIR / ".data" / "workflow_state_snapshots"
DEFAULT_MAX_SNAPSHOTS = 5

# ─── 默认值 ──────────────────────────────────────────────────────────────────
DEFAULT_FRONTEND_PORT = 5175
DEFAULT_OPEN_METEO_VOLUME = "backend_open-meteo-data"
IS_WINDOWS = sys.platform == "win32"

# ─── 服务定义 ────────────────────────────────────────────────────────────────
# 7 个 Celery Worker 队列
CELERY_WORKERS: list[dict[str, str]] = [
    {"name": "realtime", "queues": "realtime"},
    {"name": "standard", "queues": "standard"},
    {"name": "heavy", "queues": "heavy"},
    {"name": "batch", "queues": "batch"},
    {"name": "download", "queues": "download-realtime,download-standard"},
    {"name": "gee", "queues": "gee-realtime,gee-standard,gee-heavy,gee-batch"},
    {
        "name": "weather",
        "queues": "weather-realtime,weather-standard,weather-heavy,weather-batch",
    },
]
VALID_WORKER_NAMES = [w["name"] for w in CELERY_WORKERS]

# ─── 日志系统常量 ────────────────────────────────────────────────────────────
_LAUNCHER_LOG_MAX_BYTES = 5 * 1024 * 1024
_LAUNCHER_LOG_BACKUP_COUNT = 3
_SUBPROCESS_LOG_ROTATE_THRESHOLD = 50 * 1024 * 1024  # 50 MB
