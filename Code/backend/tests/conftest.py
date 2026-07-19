"""pytest 共享配置：补齐 backend、Code、GEE src 目录，确保 app/shared/webgis_gee 模块都可导入。

并重定向 ``tmp_path`` 到项目内可写目录，规避 Windows ACL 限制：
默认 ``C:\\Users\\likr\\AppData\\Local\\Temp\\pytest-of-likr`` 在某些 Windows 环境下
有 ACL 限制（WinError 5），导致 ``tmp_path`` fixture 报 ``PermissionError``。
通过设置 ``PYTEST_DEBUG_TEMPROOT`` 环境变量到项目内 ``.pytest_tmp`` 子目录绕过。
"""
import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_CODE_ROOT = _BACKEND_ROOT.parent
_GEE_SRC = _BACKEND_ROOT / "app" / "gee" / "core" / "src"

for path in (str(_BACKEND_ROOT), str(_CODE_ROOT), str(_GEE_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

# ── 重定向 pytest tmp_path 到项目内可写目录 ──────────────────────────────
# 必须在 pytest 初始化 ``tmp_path_factory`` 之前设置 ``PYTEST_DEBUG_TEMPROOT``
# 环境变量。conftest.py 在 pytest 配置阶段加载，早于 session fixture 初始化，
# 因此模块级设置能生效。
_PROJECT_TMP = _BACKEND_ROOT / ".pytest_tmp"
_PROJECT_TMP.mkdir(parents=True, exist_ok=True)
# 仅当用户未显式覆盖时设置（避免与 --basetemp CLI 冲突）
if "PYTEST_DEBUG_TEMPROOT" not in os.environ:
    os.environ["PYTEST_DEBUG_TEMPROOT"] = str(_PROJECT_TMP)
