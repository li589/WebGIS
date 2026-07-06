"""pytest 共享配置：添加 Code 根目录到 sys.path，让 shared 模块可被导入。"""
import sys
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CODE_ROOT))
