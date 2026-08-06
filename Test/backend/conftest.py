"""pytest 共享配置：补齐 backend、Code、GEE src 目录，确保 app/shared/webgis_gee 模块都可导入。

并重定向 ``tmp_path`` 到项目内可写目录，规避 Windows ACL 限制：
默认 ``C:\\Users\\likr\\AppData\\Local\\Temp\\pytest-of-likr`` 在某些 Windows 环境下
有 ACL 限制（WinError 5），导致 ``tmp_path`` fixture 报 ``PermissionError``。
通过设置 ``PYTEST_DEBUG_TEMPROOT`` 环境变量到项目内 ``.pytest_tmp`` 子目录绕过。
"""

import os
import sys
from pathlib import Path

os.environ["ENVIRONMENT"] = "test"
os.environ["BACKEND_ENV"] = "test"
os.environ["BACKEND_WORKFLOW_EXECUTOR"] = "sync"

# 测试套件已从 Code/backend/tests/ 迁至 Test/backend/，路径需回归仓库根再定位。
# conftest 位于 <repo>/Test/backend/conftest.py → parents[2] = 仓库根。
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "Code" / "backend"
_CODE_ROOT = _REPO_ROOT / "Code"
_GEE_SRC = _BACKEND_ROOT / "app" / "gee" / "core" / "src"

# 去硬编码批 1：算法/后端不再默认 I:；测试注入 DATA_ROOT（实验室盘存在则复用）
if not os.environ.get("BACKEND_DATA_ROOT", "").strip():
    _lab_root = Path(r"I:\Geograph_DataSet")
    os.environ["BACKEND_DATA_ROOT"] = str(
        _lab_root if _lab_root.exists() else _BACKEND_ROOT / ".pytest_tmp" / "data_root"
    )

try:
    import app.core.config
    app.core.config.settings = app.core.config.Settings()
except Exception:
    pass

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

# SpatiaLite 测试隔离：默认 spatial DB 落到项目 tmp，避免污染开发库
if not os.environ.get("BACKEND_SPATIALITE_DB_PATH", "").strip():
    os.environ["BACKEND_SPATIALITE_DB_PATH"] = str(_PROJECT_TMP / "spatial_test.sqlite")
