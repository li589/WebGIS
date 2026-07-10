"""FastAPI 启动脚本，确保 shared 模块在 Python 路径中。"""
import sys
from pathlib import Path

# 添加 Code 目录到 sys.path，确保 shared 模块可导入
code_path = Path(__file__).resolve().parent.parent
if str(code_path) not in sys.path:
    sys.path.insert(0, str(code_path))

import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
