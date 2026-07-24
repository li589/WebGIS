"""FastAPI 启动脚本，确保 shared / webgis_gee 模块在 Python 路径中。"""

import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parent
code_path = backend_root.parent
gee_src = backend_root / "app" / "gee" / "core" / "src"

for p in (str(code_path), str(gee_src)):
    if p not in sys.path:
        sys.path.insert(0, p)

import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
