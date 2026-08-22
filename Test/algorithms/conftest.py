"""pytest 共享配置：算法包测试已从 Code/algorithms/providers/Python/tests/ 迁至 Test/algorithms/。

补齐算法包根目录与 Code/ 目录到 sys.path，确保 ``contracts`` / ``runner`` /
``algorithms`` / ``modules`` / ``shared`` 等模块可导入。

注意：本目录已移除 ``__init__.py``，避免 ``Test/algorithms`` 被当作名为 ``algorithms``
的包、与真实算法包 ``Code/algorithms/providers/Python/algorithms`` 命名冲突。
"""

import os
import sys
from pathlib import Path

# 测试隔离防御：剔除超出 Windows 环境变量合法上限（32767 字符）的巨型变量
# （如 AI 会话注入的 ACC_PRODUCT_CONFIG_V3 ~481KB）。它会让
# ``unittest.mock.patch.dict(os.environ, ...)`` 退出时写回超限炸
# ``ValueError: the environment variable is longer than 32767 characters``，
# 也会波及子进程 spawn（与 git 提交须 ``env -u`` 同源）。被测系统不消费该变量。
for _oversized_env_key in [k for k, v in os.environ.items() if len(v) > 32760]:
    os.environ.pop(_oversized_env_key, None)

# conftest 位于 <repo>/Test/algorithms/conftest.py → parents[2] = 仓库根
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALGO_ROOT = _REPO_ROOT / "Code" / "algorithms" / "providers" / "Python"
_CODE_ROOT = _REPO_ROOT / "Code"

os.environ.setdefault("BACKEND_ENV", "test")
os.environ.setdefault("ENVIRONMENT", "test")
# 数据根优先级：CGDA_TEST_DATA_ROOT（显式覆盖）> 已设 BACKEND_DATA_ROOT
# > 实验室盘存在则复用（向后兼容）> 仓库内临时目录。
if not os.environ.get("BACKEND_DATA_ROOT", "").strip():
    _explicit_test_root = os.environ.get("CGDA_TEST_DATA_ROOT", "").strip()
    if _explicit_test_root:
        os.environ["BACKEND_DATA_ROOT"] = _explicit_test_root
    else:
        _lab_root = Path(r"I:\Geograph_DataSet")
        os.environ["BACKEND_DATA_ROOT"] = str(
            _lab_root
            if _lab_root.exists()
            else _REPO_ROOT / "Code" / "backend" / ".pytest_tmp" / "data_root"
        )

# B-N8：合并收集（Test/backend 与 Test/algorithms 同一会话）时，Code 根可能已
# 被其它 conftest 加入 sys.path；若沿用 not-in 守卫，Code 根会被跳过而 provider
# 根插到 [0]，令 provider 本地 algorithms 包先入 sys.modules，遮蔽 Code/algorithms
# （后者经 __init__ 的 __path__ 合并垫片可同时解析内核算法与 providers 子包），
# 导致后端 22 个文件的 algorithms.providers 导入链断裂。故先移除已存在项，
# 再按「Code 根在前、provider 根紧随其后」的固定顺序重插。
for _path in (str(_ALGO_ROOT), str(_CODE_ROOT)):
    if _path in sys.path:
        sys.path.remove(_path)
    sys.path.insert(0, _path)
