"""Backend startup helper with correct sys.path setup."""

import os
import sys
from pathlib import Path

backend_root = Path(
    r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend"
)
code_path = backend_root.parent
gee_src = backend_root / "app" / "gee" / "core" / "src"

for p in (str(code_path), str(gee_src), str(backend_root)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.chdir(backend_root)

import uvicorn
from app.main import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
