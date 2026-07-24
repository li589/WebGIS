"""pytest 共享配置：补齐 Code/ 目录到 sys.path，确保 shared 模块可导入。

algorithms 包内的 ``data_access/sources/remote.py`` 依赖 ``shared.remote_sources``
（位于 ``Code/shared/``），但 pytest 默认仅将 algorithms 包根目录加入 sys.path，
不会包含上级的 ``Code/``。此 conftest 在 pytest 配置阶段（早于测试收集）补齐路径。
"""

import sys
from pathlib import Path

_PYTHON_ROOT = Path(__file__).resolve().parent
_CODE_ROOT = _PYTHON_ROOT.parent.parent.parent  # Code/

for path in (str(_PYTHON_ROOT), str(_CODE_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
