"""pytest 共享配置：补齐 backend、Code、GEE src 目录，确保 app/shared/webgis_gee 模块都可导入。"""
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_CODE_ROOT = _BACKEND_ROOT.parent
_GEE_SRC = _BACKEND_ROOT / "app" / "gee" / "core" / "src"

for path in (str(_BACKEND_ROOT), str(_CODE_ROOT), str(_GEE_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)
