"""Celery worker 启动脚本，确保 shared / webgis_gee 模块在 Python 路径中。"""

import sys
from pathlib import Path

backend_root = Path(__file__).parent
code_path = backend_root.parent
gee_src = backend_root / "app" / "gee" / "core" / "src"

for p in (str(code_path), str(gee_src)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.core.celery_app import celery_app

if __name__ == "__main__":
    celery_app.worker_main(sys.argv[1:])
