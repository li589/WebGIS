"""Celery Beat 定时任务调度器 — 驱动 weather_schedule_enabled 定时任务。"""
import sys
from pathlib import Path

code_path = Path(__file__).parent.parent
if str(code_path) not in sys.path:
    sys.path.insert(0, str(code_path))

from app.core.celery_app import celery_app

if __name__ == "__main__":
    # 显式传入 'beat' 子命令，避免 sys.argv[0]（脚本名）被 Celery 误判为命令名
    celery_app.start(["beat"] + sys.argv[1:])
