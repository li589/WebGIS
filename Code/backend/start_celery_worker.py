"""Celery worker 启动脚本，确保 shared 模块在 Python 路径中。"""
import sys
from pathlib import Path

# 将 Code/ 添加到 Python 路径（shared 是 Code/shared 下的包）
code_path = Path(__file__).parent.parent
if str(code_path) not in sys.path:
    sys.path.insert(0, str(code_path))

# 现在可以安全导入 celery_app
from app.core.celery_app import celery_app

if __name__ == "__main__":
    celery_app.worker_main(sys.argv[1:])
