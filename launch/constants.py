"""Path constants, service definitions, and defaults for the CGDA launcher.

All module-level constants that were historically inline in ``launch.py``.
Centralising them here lets every ``launch/`` submodule reference the same
paths without re-declaring them, and makes it obvious which directories
the launcher touches.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ─── 路径常量 ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent.parent  # launch/ → project root
BACKEND_DIR = SCRIPT_DIR / "Code" / "backend"
FRONTEND_DIR = SCRIPT_DIR / "Code" / "frontend"
ALGORITHMS_DIR = SCRIPT_DIR / "Code" / "algorithms"
TEST_DIR = SCRIPT_DIR / "Test"
DATA_SYNC_DIR = SCRIPT_DIR / "Code" / "infra" / "data-sync"
GATEWAY_DIR = SCRIPT_DIR / "Code" / "infra" / "gateway"
VITE_CACHE_DIR = FRONTEND_DIR / "node_modules" / ".vite"
# Launcher 本地态（PID/日志/flush 天气缓存）固定在 Code/backend/.data/。
# 与 FastAPI 的 BACKEND_RUNTIME_ROOT（常指向数据盘 _runtime）是**双轨**：
# launch 管进程与联调缓存；算法/工作流产物以 BACKEND_*_ROOT 为准。
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
# Gateway --vite 剖面：对外仍 :5175，Vite 本机监听此端口，由 Nginx 反代 + HMR WS
VITE_BEHIND_GATEWAY_PORT = 5174
DEFAULT_OPEN_METEO_VOLUME = "backend_open-meteo-data"
IS_WINDOWS = sys.platform == "win32"

# ─── 服务定义 ────────────────────────────────────────────────────────────────
# 7 个 Celery Worker 队列（instances=该队列的并发 worker 进程数）。
#
# 并发设计（2026-08-21 需求4：工作流并发执行）：
# - Windows 下 celery prefork 不可用、默认 solo 池单进程串行 → 同队列一次
#   只能跑一个任务（用户观察「仅能运行单个工作流，其余排队」的根因）。
# - 解法：每队列按 instances 启动 N 个独立 worker 进程（进程级真并行，
#   规避 Windows pool 兼容性）。standard/heavy 是工作流主队列，默认 2。
# - 单实例保持旧 pid key（worker-{name}）；多实例为 worker-{name}-{i}。
# - env 覆盖：CGDA_WORKER_INSTANCES_{NAME}（如 CGDA_WORKER_INSTANCES_HEAVY=3）。
# - 节点级并行（层内同层节点）另有 CGDA_WORKFLOW_NODE_PARALLELISM（默认 1）；
#   资源分配统一经 resource_profile（heavy/standard）路由队列。
CELERY_WORKERS: list[dict[str, object]] = [
    {"name": "realtime", "queues": "realtime", "instances": 1},
    {"name": "standard", "queues": "standard", "instances": 2},
    {"name": "heavy", "queues": "heavy", "instances": 2},
    {"name": "batch", "queues": "batch", "instances": 1},
    {"name": "download", "queues": "download-realtime,download-standard", "instances": 1},
    {"name": "gee", "queues": "gee-realtime,gee-standard,gee-heavy,gee-batch", "instances": 1},
    {
        "name": "weather",
        "queues": "weather-realtime,weather-standard,weather-heavy,weather-batch",
        "instances": 1,
    },
]
VALID_WORKER_NAMES = [str(w["name"]) for w in CELERY_WORKERS]


def worker_instance_count(worker_name: str) -> int:
    """读取某队列的 worker 进程数（env CGDA_WORKER_INSTANCES_<NAME> 可覆盖）。"""
    for w in CELERY_WORKERS:
        if str(w["name"]) == worker_name:
            default = int(w.get("instances", 1) or 1)  # type: ignore[arg-type]
            raw = os.getenv(f"CGDA_WORKER_INSTANCES_{worker_name.upper()}")
            if raw and raw.strip():
                try:
                    return max(1, int(raw.strip()))
                except ValueError:
                    return default
            return default
    return 1

# ─── 日志系统常量 ────────────────────────────────────────────────────────────
_LAUNCHER_LOG_MAX_BYTES = 5 * 1024 * 1024
_LAUNCHER_LOG_BACKUP_COUNT = 3
_SUBPROCESS_LOG_ROTATE_THRESHOLD = 50 * 1024 * 1024  # 50 MB
