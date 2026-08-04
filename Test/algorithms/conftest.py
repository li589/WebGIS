"""pytest 共享配置：算法包测试已从 Code/algorithms/providers/Python/tests/ 迁至 Test/algorithms/。

补齐算法包根目录与 Code/ 目录到 sys.path，确保 ``contracts`` / ``runner`` /
``algorithms`` / ``modules`` / ``shared`` 等模块可导入。

注意：本目录已移除 ``__init__.py``，避免 ``Test/algorithms`` 被当作名为 ``algorithms``
的包、与真实算法包 ``Code/algorithms/providers/Python/algorithms`` 命名冲突。
"""

import sys
from pathlib import Path

# conftest 位于 <repo>/Test/algorithms/conftest.py → parents[2] = 仓库根
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALGO_ROOT = _REPO_ROOT / "Code" / "algorithms" / "providers" / "Python"
_CODE_ROOT = _REPO_ROOT / "Code"

for _path in (str(_ALGO_ROOT), str(_CODE_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
