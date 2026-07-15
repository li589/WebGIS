"""Celery Beat 定时任务调度器 — 驱动 weather_schedule_enabled 定时任务。"""
import sys
from pathlib import Path

backend_root = Path(__file__).parent
code_path = backend_root.parent
gee_src = backend_root / "app" / "gee" / "core" / "src"

for p in (str(code_path), str(gee_src)):
    if p not in sys.path:
        sys.path.insert(0, str(p))

from app.core.celery_app import celery_app

if __name__ == "__main__":
    # 显式传入 'beat' 子命令，避免 sys.argv[0]（脚本名）被 Celery 误判为命令名
    celery_app.start(["beat"] + sys.argv[1:])
